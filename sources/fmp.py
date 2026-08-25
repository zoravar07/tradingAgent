"""FMP source — §10 step 3: "fundamentals, earnings, prices, analysts, 13F,
insider. Cache hard; free tier is 250 calls/day."

`FMPClient` is a thin, cached wrapper over the handful of Financial Modeling
Prep endpoints Zopro needs. `FMPFactorSource` adapts it to the §8.2
`FactorSource` interface so it plugs into the pipeline like any other source.

Two things worth knowing if you're extending this:

* The HTTP layer is injected (`session`), not imported directly, so tests
  never make real network calls or spend real API quota — see
  tests/test_fmp_client.py for the fake-session pattern.
* 13F institutional ownership and insider trading are FMP endpoints that have
  moved between plan tiers before. If either 402/403s on your account, that's
  a plan-tier issue, not a bug here — the error surfaces through
  `FactorData.error` rather than crashing a run.
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

BASE_URL = "https://financialmodelingprep.com/api"

# TTLs, in seconds — how long a cached response is trusted before refetching.
TTL_PROFILE = 7 * 24 * 3600
TTL_QUOTE = 20 * 3600
TTL_FUNDAMENTALS = 30 * 24 * 3600
TTL_HISTORICAL_PRICES = 20 * 3600
TTL_EARNINGS = 7 * 24 * 3600
TTL_ANALYST = 3 * 24 * 3600
TTL_OWNERSHIP_13F = 30 * 24 * 3600
TTL_INSIDER = 3 * 24 * 3600


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

    def _get(self, path: str, params: dict | None = None, ttl_seconds: float = TTL_QUOTE) -> Any:
        params = dict(params or {})
        cache_key = "fmp:" + path + ":" + json.dumps(params, sort_keys=True)

        def do_fetch() -> Any:
            self.budget.check_and_increment()
            response = self.session.get(
                self.base_url + path,
                params={**params, "apikey": self.api_key},
                timeout=10,
            )
            if response.status_code != 200:
                raise FMPError(f"FMP {path} returned HTTP {response.status_code}: {response.text[:200]}")
            data = response.json()
            if isinstance(data, dict) and "Error Message" in data:
                raise FMPError(f"FMP {path} error: {data['Error Message']}")
            return data

        value, _ = self.cache.get_or_fetch(cache_key, ttl_seconds, do_fetch)
        return value

    # --------------------------------------------------------- fundamentals

    def get_profile(self, ticker: str) -> dict:
        data = self._get(f"/v3/profile/{ticker}", ttl_seconds=TTL_PROFILE)
        return data[0] if isinstance(data, list) and data else (data or {})

    def get_quote(self, ticker: str) -> dict:
        data = self._get(f"/v3/quote/{ticker}", ttl_seconds=TTL_QUOTE)
        return data[0] if isinstance(data, list) and data else (data or {})

    def get_income_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._get(
            f"/v3/income-statement/{ticker}",
            params={"period": period, "limit": limit},
            ttl_seconds=TTL_FUNDAMENTALS,
        ) or []

    def get_cash_flow_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._get(
            f"/v3/cash-flow-statement/{ticker}",
            params={"period": period, "limit": limit},
            ttl_seconds=TTL_FUNDAMENTALS,
        ) or []

    # --------------------------------------------------------------- prices

    def get_historical_prices(
        self, ticker: str, from_date: str | None = None, to_date: str | None = None
    ) -> list[dict]:
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        data = self._get(
            f"/v3/historical-price-full/{ticker}", params=params, ttl_seconds=TTL_HISTORICAL_PRICES
        )
        return (data or {}).get("historical", [])

    # -------------------------------------------------------------- earnings

    def get_earnings_surprises(self, ticker: str, limit: int = 8) -> list[dict]:
        data = self._get(
            f"/v3/earnings-surprises/{ticker}", params={"limit": limit}, ttl_seconds=TTL_EARNINGS
        )
        return data or []

    # -------------------------------------------------------------- analysts

    def get_analyst_estimates(self, ticker: str, period: str = "annual", limit: int = 4) -> list[dict]:
        return self._get(
            f"/v3/analyst-estimates/{ticker}",
            params={"period": period, "limit": limit},
            ttl_seconds=TTL_ANALYST,
        ) or []

    def get_price_target_summary(self, ticker: str) -> dict:
        data = self._get("/v4/price-target-summary", params={"symbol": ticker}, ttl_seconds=TTL_ANALYST)
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    # ------------------------------------------------------------------ 13F

    def get_institutional_ownership(self, ticker: str) -> list[dict]:
        data = self._get(
            "/v4/institutional-ownership/symbol-ownership",
            params={"symbol": ticker, "includeCurrentQuarter": "false"},
            ttl_seconds=TTL_OWNERSHIP_13F,
        )
        return data or []

    # --------------------------------------------------------------- insider

    def get_insider_trading(self, ticker: str, limit: int = 50) -> list[dict]:
        data = self._get(
            "/v4/insider-trading", params={"symbol": ticker, "limit": limit}, ttl_seconds=TTL_INSIDER
        )
        return data or []


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
