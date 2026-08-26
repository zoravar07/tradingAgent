"""yfinance price + fundamentals-fallback source — free, no API key, no
plan-tier gating.

Added after the first live run discovered that this account's FMP plan
restricts the `quote` endpoint to a small set of tickers (large-cap stocks
only — every ETF and several smaller-cap holdings 402'd), and then that a
*second* run discovered `income-statement`/`cash-flow-statement` are gated
the same way for the same tickers. yfinance covers all of it: confirmed
live for a gated large-cap (AMD) and every ticker FMP's quote rejected
(VTI, IAU, CEG, NBIS).

**Prices and historical bars**: `get_current_price` / `get_historical_bars`
are the primary source now — `LiveMarketDataGateway` always uses these, not
a fallback. FMP's quote endpoint is unreliable enough on this plan that
"try FMP first" would just re-add the original bug.

**Fundamentals**: `get_income_statement` / `get_cash_flow_statement` exist
as an explicit *fallback* — `LiveMarketDataGateway` still tries FMP first
(it has a richer field set and worked fine for names it wasn't gated on)
and only calls into this module when FMP 402s or errors. The field mapping
below (yfinance's `Ticker.income_stmt`/`.cashflow` row names → FMP's JSON
key names) was verified, not assumed: every mapped field was checked for
exact numeric equality against FMP's real response for both AMD and MSFT
during development (see tests/test_yfinance_fundamentals.py, which re-runs
that check against frozen real fixtures rather than live data). One field
was dropped because it did NOT match: FMP's `incomeBeforeTax` and
yfinance's "Pretax Income" disagree by a small amount for AMD (a genuine
derivation difference between providers, not a mapping bug) — it's simply
not in the map rather than being included with unverified accuracy.

Every actual yfinance call is wrapped behind injectable fetcher functions,
never called directly by `YFinanceClient` — tests supply fakes/fixtures, so
nothing in the test suite hits Yahoo Finance's real (undocumented,
rate-limited) API.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from core.cache import FileCache
from sources.prices import Bar

TTL_QUOTE = 20 * 3600  # matches sources/fmp.py's TTL_QUOTE — daily nightly-run cadence
TTL_HISTORICAL = 20 * 3600
TTL_FUNDAMENTALS = 30 * 24 * 3600  # matches sources/fmp.py's TTL_FUNDAMENTALS

PriceFetcher = Callable[[str], float]
HistoryFetcher = Callable[[str, str], list[dict]]
RawStatementFetcher = Callable[[str], list[dict]]

# yfinance row name -> FMP JSON key. Only fields verified to match FMP
# EXACTLY, for both AMD and MSFT, across BOTH periods checked (the most
# recent fiscal year and the one before it) are included — see module
# docstring. Checking only the latest period was not enough: several
# fields below matched for the latest year but diverged on the prior one
# (a real provider restatement/reclassification difference, most likely —
# not a bug in this mapping), and are deliberately excluded rather than
# mapped with unverified accuracy:
#
#   income:    sellingGeneralAndAdministrativeExpenses, operatingIncome,
#              ebitda, incomeBeforeTax
#   cashflow:  depreciationAndAmortization
#
# See tests/test_yfinance_fundamentals.py for the fixture-backed checks
# that produced this list.
INCOME_STATEMENT_FIELD_MAP: dict[str, str] = {
    "revenue": "Total Revenue",
    "costOfRevenue": "Cost Of Revenue",
    "grossProfit": "Gross Profit",
    "researchAndDevelopmentExpenses": "Research And Development",
    "netIncome": "Net Income",
    "eps": "Basic EPS",
    "epsDiluted": "Diluted EPS",
    "incomeTaxExpense": "Tax Provision",
}

CASH_FLOW_FIELD_MAP: dict[str, str] = {
    "operatingCashFlow": "Operating Cash Flow",
    "capitalExpenditure": "Purchase Of PPE",
    "freeCashFlow": "Free Cash Flow",
    "stockBasedCompensation": "Stock Based Compensation",
    "netIncome": "Net Income From Continuing Operations",
}


class YFinanceError(RuntimeError):
    pass


def _clean(value) -> float | None:
    """None/NaN -> None; anything else -> float. yfinance uses pandas NaN
    for missing values, which is not JSON-serializable — core/cache.py's
    FileCache would choke on it if this weren't cleaned first."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def map_statement_row(raw_row: dict, field_map: dict[str, str]) -> dict:
    """Pure mapping function — no yfinance/pandas dependency, so it's
    directly testable against frozen fixtures. `raw_row` is one period's
    data keyed by yfinance row name (plus a "date" key, passed through
    unchanged); returns an FMP-shaped dict keyed by FMP's field names."""
    out: dict = {"date": raw_row.get("date")}
    for fmp_key, yf_key in field_map.items():
        out[fmp_key] = _clean(raw_row.get(yf_key))
    return out


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


def _dataframe_to_raw_rows(df) -> list[dict]:
    """Transposes a yfinance statement DataFrame (rows=line items,
    columns=period end dates, most-recent-first) into a list of one plain
    dict per period, keyed by yfinance row name plus "date"."""
    rows = []
    for col in df.columns:
        row = {idx: df.at[idx, col] for idx in df.index}
        row["date"] = col.strftime("%Y-%m-%d")
        rows.append(row)
    return rows


def _default_income_statement_raw_fetcher(ticker: str) -> list[dict]:
    import yfinance as yf

    df = yf.Ticker(ticker).income_stmt
    if df is None or df.empty:
        raise YFinanceError(f"no income statement data from yfinance for {ticker}")
    return _dataframe_to_raw_rows(df)


def _default_cash_flow_raw_fetcher(ticker: str) -> list[dict]:
    import yfinance as yf

    df = yf.Ticker(ticker).cashflow
    if df is None or df.empty:
        raise YFinanceError(f"no cash flow data from yfinance for {ticker}")
    return _dataframe_to_raw_rows(df)


@dataclass
class YFinanceClient:
    cache: FileCache
    price_fetcher: PriceFetcher = _default_price_fetcher
    history_fetcher: HistoryFetcher = _default_history_fetcher
    income_statement_raw_fetcher: RawStatementFetcher = _default_income_statement_raw_fetcher
    cash_flow_raw_fetcher: RawStatementFetcher = _default_cash_flow_raw_fetcher

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

    def get_income_statement(self, ticker: str, limit: int = 5) -> list[dict]:
        def fetch() -> list[dict]:
            return self.income_statement_raw_fetcher(ticker)

        raw_rows, _ = self.cache.get_or_fetch(f"yf:income:{ticker}", TTL_FUNDAMENTALS, fetch)
        return [map_statement_row(row, INCOME_STATEMENT_FIELD_MAP) for row in raw_rows[:limit]]

    def get_cash_flow_statement(self, ticker: str, limit: int = 5) -> list[dict]:
        def fetch() -> list[dict]:
            return self.cash_flow_raw_fetcher(ticker)

        raw_rows, _ = self.cache.get_or_fetch(f"yf:cashflow:{ticker}", TTL_FUNDAMENTALS, fetch)
        return [map_statement_row(row, CASH_FLOW_FIELD_MAP) for row in raw_rows[:limit]]
