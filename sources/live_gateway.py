"""FmpMarketDataGateway — a real, network-backed implementation of
core.orchestrator.MarketDataGateway, wired to a real FMPClient (§10 step 3).
Every gateway used elsewhere in this codebase (all of tests/) is a fake;
this is the one piece of code that actually calls FMP when it's used.

Known gaps, flagged rather than silently guessed at:

* `days_to_earnings` is always None. FMP's earnings-calendar endpoint shape
  wasn't verified against a real account before this was written, and a
  wrong guess here would silently do the wrong thing rather than degrade
  gracefully — screener.py already treats a missing earnings date as "not
  soon" (§5.1's earnings-proximity flag just doesn't fire), which is a safe
  default, not a crash. Add real earnings-date fetching once the correct
  endpoint/shape is confirmed against your plan.
* Sector relative strength (`relative_strength_vs_sector_pct`) is always
  None — there's no ticker-to-sector-ETF mapping anywhere in the spec or
  config. `relative_strength_vs_spy_pct` (the other §5.1 benchmark) is
  computed normally.
* Every FMP field access uses `.get()` with a None fallback rather than
  asserting a field exists — the free tier's exact response shape wasn't
  verified line-by-line before this was written. A missing field degrades
  to a failed gate or a None in the research context, not a crash — the
  same "surface, don't hide" philosophy as the rest of this codebase.
"""

from __future__ import annotations

from agents.screener import ScreenerInput
from core.orchestrator import MarketDataGateway
from sources.fmp import FMPClient
from sources.prices import compute_technical_snapshot, fetch_bars

HISTORICAL_LOOKBACK_DAYS = 400  # enough trading history for a 200-DMA + a year of ATR percentile


def _latest_revenue_growth_pct(income_statements: list[dict]) -> float | None:
    """YoY growth from the two most recent annual periods, if both are present."""
    if len(income_statements) < 2:
        return None
    latest = income_statements[0].get("revenue")
    prior = income_statements[1].get("revenue")
    if latest is None or prior in (None, 0):
        return None
    return (latest - prior) / prior * 100


class FmpMarketDataGateway:
    def __init__(self, client: FMPClient, cluster_overrides: dict[str, str] | None = None):
        self.client = client
        self.cluster_overrides = {k.upper(): v for k, v in (cluster_overrides or {}).items()}
        self._spy_bars_cache = None  # FMPClient itself caches the HTTP call; this avoids re-parsing per ticker

    def _spy_bars(self):
        if self._spy_bars_cache is None:
            self._spy_bars_cache = fetch_bars(self.client, "SPY")
        return self._spy_bars_cache

    @staticmethod
    def _safe(fetch_fn, default):
        """Run one FMP call; on failure, return `default` with the error
        folded in (a dict gets an "error" key, a list gets one error entry)
        rather than propagating — a single unavailable field must not take
        down the whole research context."""
        try:
            return fetch_fn()
        except Exception as exc:  # noqa: BLE001
            if isinstance(default, dict):
                return {**default, "error": str(exc)}
            if isinstance(default, list):
                return [*default, {"error": str(exc)}]
            return default

    # ------------------------------------------------------------ screener

    def get_screener_input(self, ticker: str, is_held: bool) -> ScreenerInput:
        profile = self.client.get_profile(ticker)
        quote = self.client.get_quote(ticker)
        income = self.client.get_income_statement(ticker, limit=2)
        cash_flow = self.client.get_cash_flow_statement(ticker, limit=1)
        bars = fetch_bars(self.client, ticker)

        technical = compute_technical_snapshot(bars, spy_bars=self._spy_bars(), sector_bars=None)

        price = quote.get("price") or profile.get("price")
        avg_volume = profile.get("volAvg") or quote.get("avgVolume")
        adv_usd = (avg_volume * price) if (avg_volume and price) else None

        free_cash_flow = cash_flow[0].get("freeCashFlow") if cash_flow else None

        return ScreenerInput(
            ticker=ticker,
            market_cap_usd=profile.get("mktCap"),
            avg_daily_volume_usd=adv_usd,
            technical=technical,
            trailing_pe=profile.get("pe") or quote.get("pe"),
            free_cash_flow=free_cash_flow,
            revenue_growth_pct=_latest_revenue_growth_pct(income),
            days_to_earnings=None,  # see module docstring
            is_held=is_held,
        )

    # ------------------------------------------------------------ research

    def get_research_context(self, ticker: str) -> str:
        # Every field fetch is defensive — confirmed empirically during
        # development that even "core" resources (earnings-surprises,
        # insider-trading) can 404 on a real account while others (profile,
        # income-statement) work fine, and 13F can 402 on a free-tier plan.
        # One bad sub-fetch degrades that field to an error note, not a
        # crashed memo — this is what makes it safe for the orchestrator to
        # call this per-ticker without its own try/except around every field.
        profile = self._safe(lambda: self.client.get_profile(ticker), {})
        quote = self._safe(lambda: self.client.get_quote(ticker), {})
        income = self._safe(lambda: self.client.get_income_statement(ticker, limit=3), [])
        cash_flow = self._safe(lambda: self.client.get_cash_flow_statement(ticker, limit=3), [])
        earnings = self._safe(lambda: self.client.get_earnings_surprises(ticker, limit=4), [])
        estimates = self._safe(lambda: self.client.get_analyst_estimates(ticker, limit=2), [])
        price_target = self._safe(lambda: self.client.get_price_target_summary(ticker), {})
        ownership = self._safe(lambda: self.client.get_institutional_ownership(ticker), [])
        insider = self._safe(lambda: self.client.get_insider_trading(ticker, limit=20), [])

        bars = fetch_bars(self.client, ticker)
        technical = compute_technical_snapshot(bars, spy_bars=self._spy_bars(), sector_bars=None)

        lines = [
            f"Company: {profile.get('companyName', ticker)} ({ticker})",
            f"Sector: {profile.get('sector')} / Industry: {profile.get('industry')}",
            f"Market cap: {profile.get('mktCap')}",
            f"Price: {quote.get('price')}  P/E: {profile.get('pe')}",
            f"Description: {profile.get('description', '')[:1000]}",
            "",
            f"Income statements (most recent first): {income}",
            f"Cash flow statements (most recent first): {cash_flow}",
            f"Earnings surprises (most recent first): {earnings}",
            f"Analyst estimates: {estimates}",
            f"Price target summary: {price_target}",
            f"13F institutional ownership: {ownership}",
            f"Insider trading (last 20): {insider}",
            "",
            f"Technical snapshot: price={technical.last_price}, 50DMA={technical.sma_50}, "
            f"200DMA={technical.sma_200}, price_vs_50DMA_pct={technical.price_vs_sma_50_pct}, "
            f"price_vs_200DMA_pct={technical.price_vs_sma_200_pct}, ATR14={technical.atr_14}, "
            f"ATR_pct_of_price={technical.atr_pct_of_price}, ATR_percentile_252d={technical.atr_percentile_252d}, "
            f"relative_strength_vs_SPY_63d_pct={technical.relative_strength_vs_spy_pct}",
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------- prices

    def get_current_price(self, ticker: str) -> float:
        quote = self.client.get_quote(ticker)
        price = quote.get("price")
        if price is None:
            raise ValueError(f"no price in FMP quote for {ticker}")
        return float(price)

    # ------------------------------------------------------- sector/cluster

    def get_sector(self, ticker: str) -> str | None:
        return self.client.get_profile(ticker).get("sector")

    def get_cluster(self, ticker: str) -> str | None:
        return self.cluster_overrides.get(ticker.upper())
