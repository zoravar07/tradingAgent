"""FMP source — §10 step 3: "fundamentals, earnings, prices, analysts, 13F,
insider. Cache hard; free tier is 250 calls/day."

`FMPClient` is a thin, cached wrapper over the handful of Financial Modeling
Prep endpoints Z Money needs. `FMPFactorSource` adapts it to the §8.2
`FactorSource` interface so it plugs into the pipeline like any other source.

**API generation: `/stable/`, not `/api/v3/`.** FMP retired the old
path-segment API (`/api/v3/profile/AAPL`) in favor of a flat `/stable/`
generation where the resource is a plain path component and the symbol is a
query parameter (`/stable/profile?symbol=AAPL`) — confirmed by hitting the
real API during development (`/v3/sp500_constituent` now 403s with "Legacy
Endpoint... only available for legacy users with valid subscriptions prior
August 31, 2025"). This module targets `/stable/` throughout. Endpoint
resource names below fall into two confidence tiers:

* **Confirmed** (profile, quote, income-statement, cash-flow-statement,
  historical-price-eod/full, analyst-estimates, sp500-constituent) — checked
  against FMP's current docs/an actively-maintained third-party client
  during development.
* **Best-effort, not independently confirmed** (earnings-surprises,
  price-target-summary, institutional-ownership, insider-trading) — FMP's
  13F/insider/estimates surface has been renamed and restructured
  repeatedly (e.g. 13F now also exists as a CIK+year+quarter "extract" API,
  a separate "positions-summary" API, and a legacy per-symbol API), and
  the exact current resource path for a couple of these wasn't confirmed
  before writing this. If one 404s/403s on your account, that's this
  module's guess being wrong, not a plan-tier issue — check FMP's docs for
  the resource's current name and update the constant below. Every one of
  these calls already degrades gracefully (`FactorData.error` /
  `FmpMarketDataGateway`'s try/except) rather than crashing a run either way.
* The HTTP layer is injected (`session`), not imported directly, so tests
  never make real network calls or spend real API quota — see
  tests/test_fmp_client.py for the fake-session pattern.
* Caching is deliberately per-endpoint-per-ticker with a TTL matched to how
  often that data actually changes (fundamentals: monthly; quotes/prices:
  daily; ownership: monthly). This is what makes "250 calls/day" survive a
  universe bigger than 250 tickers — but step 4 (screener) still needs to be
  deliberate about *which* tickers get a full FMP fetch and when; this module
  doesn't solve that budget problem on its own, it just makes each call as
  cheap as possible to repeat.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Protocol

from core.cache import DailyCallBudget, FileCache
from sources.base import FactorData, FactorSource, RunContext

BASE_URL = "https://financialmodelingprep.com/stable"

# TTLs, in seconds — how long a cached response is trusted before refetching.
TTL_PROFILE = 7 * 24 * 3600
TTL_QUOTE = 20 * 3600
TTL_FUNDAMENTALS = 30 * 24 * 3600
TTL_EARNINGS = 7 * 24 * 3600
TTL_ANALYST = 3 * 24 * 3600
TTL_OWNERSHIP_13F = 30 * 24 * 3600
TTL_INSIDER = 3 * 24 * 3600

# Best-effort resource names — see module docstring's confidence tiers.
RESOURCE_EARNINGS_SURPRISES = "earnings-surprises"
RESOURCE_PRICE_TARGET_SUMMARY = "price-target-summary"
RESOURCE_INSTITUTIONAL_OWNERSHIP = "institutional-ownership/symbol-positions-summary"
RESOURCE_INSIDER_TRADING = "insider-trading"


class FMPError(RuntimeError):
    pass


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...
    @property
    def text(self) -> str: ...


class HttpSession(Protocol):
    def get(self, url: str, params: dict, timeout: float) -> HttpResponse: ...


@dataclass
class FMPClient:
    api_key: str
    cache: FileCache
    budget: DailyCallBudget
    session: HttpSession
    base_url: str = BASE_URL

    # ------------------------------------------------------------- transport

    def _get(self, resource: str, params: dict | None = None, ttl_seconds: float = TTL_QUOTE) -> Any:
        """`resource` is a stable-API resource path, e.g. "profile" or
        "institutional-ownership/symbol-positions-summary" — no leading
        slash, no symbol segment (pass `symbol` in `params` instead)."""
        params = dict(params or {})
        cache_key = "fmp:" + resource + ":" + json.dumps(params, sort_keys=True)

        def do_fetch() -> Any:
            self.budget.check_and_increment()
            response = self.session.get(
                f"{self.base_url}/{resource}",
                params={**params, "apikey": self.api_key},
                timeout=10,
            )
            if response.status_code != 200:
                raise FMPError(f"FMP {resource} returned HTTP {response.status_code}: {response.text[:200]}")
            data = response.json()
            if isinstance(data, dict) and "Error Message" in data:
                raise FMPError(f"FMP {resource} error: {data['Error Message']}")
            return data

        value, _ = self.cache.get_or_fetch(cache_key, ttl_seconds, do_fetch)
        return value

    # --------------------------------------------------------- fundamentals

    def get_profile(self, ticker: str) -> dict:
        data = self._get("profile", params={"symbol": ticker}, ttl_seconds=TTL_PROFILE)
        return data[0] if isinstance(data, list) and data else (data or {})

    def get_quote(self, ticker: str) -> dict:
        data = self._get("quote", params={"symbol": ticker}, ttl_seconds=TTL_QUOTE)
        return data[0] if isinstance(data, list) and data else (data or {})

    def get_income_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._get(
            "income-statement",
            params={"symbol": ticker, "period": period, "limit": limit},
            ttl_seconds=TTL_FUNDAMENTALS,
        ) or []

    def get_cash_flow_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._get(
            "cash-flow-statement",
            params={"symbol": ticker, "period": period, "limit": limit},
            ttl_seconds=TTL_FUNDAMENTALS,
        ) or []

    # -------------------------------------------------------------- earnings

    def get_earnings_surprises(self, ticker: str, limit: int = 8) -> list[dict]:
        data = self._get(
            RESOURCE_EARNINGS_SURPRISES, params={"symbol": ticker, "limit": limit}, ttl_seconds=TTL_EARNINGS
        )
        return data or []

    # -------------------------------------------------------------- analysts

    def get_analyst_estimates(self, ticker: str, period: str = "annual", limit: int = 4) -> list[dict]:
        return self._get(
            "analyst-estimates",
            params={"symbol": ticker, "period": period, "limit": limit},
            ttl_seconds=TTL_ANALYST,
        ) or []

    def get_price_target_summary(self, ticker: str) -> dict:
        data = self._get(RESOURCE_PRICE_TARGET_SUMMARY, params={"symbol": ticker}, ttl_seconds=TTL_ANALYST)
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    # ------------------------------------------------------------------ 13F

    def get_institutional_ownership(self, ticker: str) -> list[dict]:
        data = self._get(
            RESOURCE_INSTITUTIONAL_OWNERSHIP,
            params={"symbol": ticker},
            ttl_seconds=TTL_OWNERSHIP_13F,
        )
        return data if isinstance(data, list) else ([data] if data else [])

    # --------------------------------------------------------------- insider

    def get_insider_trading(self, ticker: str, limit: int = 50) -> list[dict]:
        data = self._get(
            RESOURCE_INSIDER_TRADING, params={"symbol": ticker, "limit": limit}, ttl_seconds=TTL_INSIDER
        )
        return data or []

    # ---------------------------------------------------------------- index

    def get_sp500_constituents(self) -> list[str]:
        """One call regardless of universe size — the rotating-pool source
        for the day-to-day universe (see core/orchestrator.py's
        resolve_universe). Membership changes rarely, hence the long TTL."""
        data = self._get("sp500-constituent", ttl_seconds=TTL_OWNERSHIP_13F)  # reuse the ~30-day TTL
        return sorted({row["symbol"].upper() for row in (data or []) if row.get("symbol")})


class FMPFactorSource(FactorSource):
    """Adapts FMPClient to the §8.2 FactorSource interface. Pulls a broad
    slice of fields per ticker; scoring/research decide what to use — this
    layer doesn't compute anything, it just fetches and shapes."""

    name = "fmp"

    def __init__(self, client: FMPClient):
        self.client = client

    def fetch(self, ticker: str, ctx: RunContext) -> FactorData:
        now = ctx.as_of if ctx else dt.datetime.utcnow()
        try:
            profile = self.client.get_profile(ticker)
            quote = self.client.get_quote(ticker)
            income = self.client.get_income_statement(ticker)
            cash_flow = self.client.get_cash_flow_statement(ticker)
            earnings = self.client.get_earnings_surprises(ticker)
            estimates = self.client.get_analyst_estimates(ticker)
            price_target = self.client.get_price_target_summary(ticker)
            ownership = self.client.get_institutional_ownership(ticker)
            insider = self.client.get_insider_trading(ticker)
        except FMPError as exc:
            return FactorData(source=self.name, ticker=ticker, fetched_at=now, error=str(exc))

        return FactorData(
            source=self.name,
            ticker=ticker,
            fetched_at=now,
            fields={
                "profile": profile,
                "quote": quote,
                "income_statement": income,
                "cash_flow_statement": cash_flow,
                "earnings_surprises": earnings,
                "analyst_estimates": estimates,
                "price_target_summary": price_target,
                "institutional_ownership": ownership,
                "insider_trading": insider,
            },
        )
