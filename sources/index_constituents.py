"""S&P 500 membership — the rotating-pool source for the day-to-day universe
(core/orchestrator.py's `resolve_universe`).

Why this exists: FMP's `sp500-constituent` endpoint returns HTTP 402 on this
account's plan, so every run before this module had an empty pool and the
"screener" only ever re-screened the positions already held (run 5 was the
one that made this visible: "S&P 500 pool: 0 names"). yfinance has no index-
membership API at all (checked against yfinance 1.6.0: nothing under
Ticker/Market/Sector/screen returns constituents), so the free, key-less
source is Wikipedia's "List of S&P 500 companies" page, parsed here.

Symbols are normalised to yfinance's spelling (`BRK.B` -> `BRK-B`) because
every downstream price/fundamentals fetch goes through yfinance. Membership
changes a handful of times a year, so the parsed list is cached for 30 days.

The HTTP fetch is behind an injectable `fetcher` — tests supply HTML, nothing
in the test suite hits the network (same pattern as sources/yfinance_source.py).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Callable

from core.cache import FileCache

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
TTL_CONSTITUENTS = 30 * 24 * 3600
CACHE_KEY = "index:sp500:constituents"

HtmlFetcher = Callable[[], str]


def normalise_symbol(raw: str) -> str:
    """Wikipedia's `BRK.B` is Yahoo's `BRK-B`; everything else is just upper-cased."""
    return raw.strip().upper().replace(".", "-")


def parse_wikipedia_symbols(html: str) -> list[str]:
    """Reads the `id="constituents"` table only — the page also carries a
    "changes" table of additions/removals that must not leak into the pool."""
    import pandas as pd

    try:
        tables = pd.read_html(io.StringIO(html), attrs={"id": "constituents"}, flavor="lxml")
    except ValueError:  # "No tables found" — lxml flavor pinned so pandas never falls back to an uninstalled parser
        return []
    if not tables:
        return []
    table = tables[0]
    if "Symbol" not in table.columns:
        return []
    return sorted({normalise_symbol(str(s)) for s in table["Symbol"].tolist() if str(s).strip()})


def _default_wikipedia_fetcher() -> str:
    import requests

    response = requests.get(
        WIKIPEDIA_URL,
        headers={"User-Agent": "z-money/0.1 (personal research tool; contact: local user)"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Wikipedia S&P 500 page returned HTTP {response.status_code}")
    return response.text


@dataclass
class SP500ConstituentsSource:
    cache: FileCache
    fetcher: HtmlFetcher = _default_wikipedia_fetcher

    def get_constituents(self) -> list[str]:
        def fetch() -> list[str]:
            symbols = parse_wikipedia_symbols(self.fetcher())
            if len(symbols) < 400:
                # A silently-empty or truncated pool is exactly the failure
                # mode this module replaces — refuse rather than cache it.
                raise RuntimeError(
                    f"S&P 500 constituents parse produced {len(symbols)} symbols (expected ~500); "
                    "refusing to use it as the scan pool"
                )
            return symbols

        symbols, _ = self.cache.get_or_fetch(CACHE_KEY, TTL_CONSTITUENTS, fetch)
        return list(symbols)
