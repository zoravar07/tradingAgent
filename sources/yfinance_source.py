"""yfinance price source — free, no API key, no plan-tier gating.

Added after the first live run discovered that this account's FMP plan
restricts the `quote` endpoint to a small set of tickers (large-cap stocks
only — every ETF and several smaller-cap holdings 402'd). yfinance covers
all of it: confirmed against the real Yahoo Finance API during development
for both a gated large-cap (AMD) and every ticker FMP couldn't quote (VTI,
IAU, CEG, NBIS).

Scope, deliberately narrow: **prices and historical bars only.**
Fundamentals, earnings, analyst estimates, and 13F/insider data stay on
FMPClient (sources/fmp.py) — that part of the FMP integration worked fine
and there's no reason to replace it. This means `LiveMarketDataGateway`
(sources/live_gateway.py) is a composite of two data sources, not a single
provider — current price and bars come from here, everything else from FMP.

The actual yfinance calls are wrapped behind two injectable functions
(`price_fetcher`, `history_fetcher`), not called directly by `YFinanceClient`
— tests supply fakes, so nothing in the test suite hits Yahoo Finance's
real (undocumented, rate-limited) API. See tests/test_yfinance_source.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.cache import FileCache
from sources.prices import Bar

TTL_QUOTE = 20 * 3600  # matches sources/fmp.py's TTL_QUOTE — daily nightly-run cadence
TTL_HISTORICAL = 20 * 3600

PriceFetcher = Callable[[str], float]
HistoryFetcher = Callable[[str, str], list[dict]]


class YFinanceError(RuntimeError):
    pass


def _default_price_fetcher(ticker: str) -> float:
    import yfinance as yf

    fast_info = yf.Ticker(ticker).fast_info
    price = fast_info.get("lastPrice") if hasattr(fast_info, "get") else None
    if price is None:
        raise YFinanceError(f"no lastPrice in yfinance fast_info for {ticker}")
    return float(price)


def _default_history_fetcher(ticker: str, period: str) -> list[dict]:
    import yfinance as yf

    df = yf.Ticker(ticker).history(period=period, interval="1d")
    if df is None or df.empty:
        raise YFinanceError(f"no historical data from yfinance for {ticker}")
    rows = []
    for date, row in df.iterrows():
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
        )
    return rows  # yfinance's history() is already chronological ascending


@dataclass
class YFinanceClient:
    cache: FileCache
    price_fetcher: PriceFetcher = _default_price_fetcher
    history_fetcher: HistoryFetcher = _default_history_fetcher

    def get_current_price(self, ticker: str) -> float:
        def fetch() -> float:
            return self.price_fetcher(ticker)

        value, _ = self.cache.get_or_fetch(f"yf:price:{ticker}", TTL_QUOTE, fetch)
        return value

    def get_historical_bars(self, ticker: str, period: str = "2y") -> list[Bar]:
        def fetch() -> list[dict]:
            return self.history_fetcher(ticker, period)

        rows, _ = self.cache.get_or_fetch(f"yf:hist:{ticker}:{period}", TTL_HISTORICAL, fetch)
        bars = [Bar(**row) for row in rows]
        return sorted(bars, key=lambda b: b.date)  # defensive; fetcher should already be ascending
