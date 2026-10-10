"""Full US common-stock universe, plus the cheap liquidity pre-gate that makes
scanning it affordable.

Two free, key-less sources, each doing one job:

* **Membership** — NASDAQ Trader's symbol directory files (`nasdaqlisted.txt`
  and `otherlisted.txt`) list every security on NASDAQ, NYSE, NYSE American,
  NYSE Arca and Cboe. Filtered here to common-stock-shaped rows: not an ETF,
  not a test issue, a plain alphabetic symbol, and a security name that isn't
  a warrant / unit / right / preferred / note / fund / trust. Measured
  2026-09-09: ~5,060 symbols after filtering, refreshed weekly (listings
  change slowly).

* **Pre-gate** — yfinance's equity screener returns market cap, 3-month
  average volume and last price for every US-listed equity in pages of 250
  (~31 requests, ~17s for ~7,500 rows, measured 2026-09-09). Stage 1's
  liquidity and market-cap gates are applied to that before any per-name
  work happens, so history and fundamentals are only ever fetched for names
  that could pass. At config.yaml's $20M ADV / $2B market cap floors that is
  ~1,900 of ~7,500 — the expensive work scales with survivors, not with the
  size of the listing.

The screener rows also seed YFinanceClient's quote cache (see
`YFinanceClient.prefetch_quotes`), so Stage 1 makes zero per-name fast_info
calls for pre-gated names.

Every network call is behind an injectable fetcher; tests supply text/dicts.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Callable

from core.cache import FileCache

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
TTL_LISTING = 7 * 24 * 3600
TTL_SCREEN = 20 * 3600  # same cadence as a daily quote
LISTING_CACHE_KEY = "listing:us:common"
SCREEN_CACHE_KEY = "yf:screen:us-equities"
MIN_PLAUSIBLE_LISTING = 3000

# Exchange codes in otherlisted.txt: N=NYSE, A=NYSE American, P=NYSE Arca,
# Z=Cboe. (Q would be NASDAQ duplicates; V=IEX has no primary listings.)
OTHER_EXCHANGES = {"N", "A", "P", "Z"}

_NOT_COMMON = re.compile(
    r"warrant|preferred|\bunit\b|\bright|depositary|notes?\b|debenture|\bfund\b|\btrust\b|acquisition corp|\bETN\b",
    re.I,
)

DirectoryFetcher = Callable[[], tuple[str, str]]
ScreenPageFetcher = Callable[[int, int], tuple[list[dict], int]]  # (offset, size) -> (rows, total)


def _is_common_symbol(symbol: str) -> bool:
    return symbol.isalpha() and 1 <= len(symbol) <= 5


def parse_us_common_stocks(nasdaq_listed: str, other_listed: str) -> list[str]:
    import pandas as pd

    n = pd.read_csv(io.StringIO(nasdaq_listed), sep="|", dtype=str).fillna("")
    n = n[~n["Symbol"].str.startswith("File Creation")]
    n = n[(n["ETF"] == "N") & (n["Test Issue"] == "N") & n["Symbol"].map(_is_common_symbol)]
    n = n[~n["Security Name"].str.contains(_NOT_COMMON)]

    o = pd.read_csv(io.StringIO(other_listed), sep="|", dtype=str).fillna("")
    o = o[~o["ACT Symbol"].str.startswith("File Creation")]
    o = o[(o["ETF"] == "N") & (o["Test Issue"] == "N") & o["ACT Symbol"].map(_is_common_symbol)]
    o = o[o["Exchange"].isin(OTHER_EXCHANGES)]
    o = o[~o["Security Name"].str.contains(_NOT_COMMON)]

    return sorted(set(n["Symbol"].str.upper()) | set(o["ACT Symbol"].str.upper()))


def _default_directory_fetcher() -> tuple[str, str]:
    import requests

    headers = {"User-Agent": "z-money/0.1 (personal research tool; contact: local user)"}
    a = requests.get(NASDAQ_LISTED_URL, headers=headers, timeout=30)
    b = requests.get(OTHER_LISTED_URL, headers=headers, timeout=30)
    if a.status_code != 200 or b.status_code != 200:
        raise RuntimeError(f"NASDAQ symbol directory returned HTTP {a.status_code}/{b.status_code}")
    return a.text, b.text


@dataclass
class USListingSource:
    cache: FileCache
    fetcher: DirectoryFetcher = _default_directory_fetcher

    def get_symbols(self) -> list[str]:
        def fetch() -> list[str]:
            symbols = parse_us_common_stocks(*self.fetcher())
            if len(symbols) < MIN_PLAUSIBLE_LISTING:
                raise RuntimeError(
                    f"US listing parse produced {len(symbols)} symbols (expected ~5,000); refusing to use it"
                )
            return symbols

        symbols, _ = self.cache.get_or_fetch(LISTING_CACHE_KEY, TTL_LISTING, fetch)
        return list(symbols)


# ------------------------------------------------------------- pre-gate


def _default_screen_page_fetcher(offset: int, size: int) -> tuple[list[dict], int]:
    import yfinance as yf

    query = yf.EquityQuery(
        "and",
        [
            yf.EquityQuery("eq", ["region", "us"]),
            yf.EquityQuery("is-in", ["exchange", "NMS", "NYQ", "NGM", "NCM", "ASE", "PCX"]),
        ],
    )
    result = yf.screen(query, sortField="intradaymarketcap", sortAsc=False, size=size, offset=offset)
    return result.get("quotes", []) or [], int(result.get("total", 0) or 0)


def screen_rows_to_quotes(rows: list[dict]) -> dict[str, dict]:
    """Screener rows -> the fast_info-shaped dict YFinanceClient's quote
    cache stores (see sources/yfinance_source.py `_default_quote_fetcher`)."""
    quotes: dict[str, dict] = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        if not symbol or row.get("quoteType") != "EQUITY":
            continue
        quotes[symbol] = {
            "market_cap": row.get("marketCap"),
            "three_month_avg_volume": row.get("averageDailyVolume3Month"),
            "last_price": row.get("regularMarketPrice"),
            "quote_type": "EQUITY",
        }
    return quotes


@dataclass
class USEquityScreen:
    """All US-listed equities with market cap / 3-month volume / price, in
    ~30 paged requests, cached for the day."""

    cache: FileCache
    page_fetcher: ScreenPageFetcher = _default_screen_page_fetcher
    page_size: int = 250
    max_pages: int = 60

    def get_quotes(self) -> dict[str, dict]:
        def fetch() -> dict[str, dict]:
            rows: list[dict] = []
            offset = 0
            for _ in range(self.max_pages):
                page, total = self.page_fetcher(offset, self.page_size)
                rows.extend(page)
                offset += self.page_size
                if not page or offset >= total:
                    break
            return screen_rows_to_quotes(rows)

        quotes, _ = self.cache.get_or_fetch(SCREEN_CACHE_KEY, TTL_SCREEN, fetch)
        return dict(quotes)


def apply_liquidity_pregate(
    symbols: list[str], quotes: dict[str, dict], *, min_market_cap_usd: float, min_avg_daily_volume_usd: float
) -> list[str]:
    """Stage 1's two exclusion gates, applied from screener data before any
    per-name fetch. A symbol with no screener row is dropped — it can't be
    priced by the same source the rest of the pipeline uses."""
    passing: list[str] = []
    for symbol in symbols:
        q = quotes.get(symbol.upper())
        if not q:
            continue
        mcap = q.get("market_cap") or 0
        volume = q.get("three_month_avg_volume") or 0
        price = q.get("last_price") or 0
        if mcap >= min_market_cap_usd and volume * price >= min_avg_daily_volume_usd:
            passing.append(symbol.upper())
    return passing
