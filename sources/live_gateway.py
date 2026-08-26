"""LiveMarketDataGateway — a real, network-backed implementation of
core.orchestrator.MarketDataGateway (§10 step 3, extended). Every gateway
used elsewhere in this codebase (all of tests/) is a fake; this is the one
piece of code that actually calls external APIs when it's used.

**Composite by design, not a single provider.** The first live run
discovered that this account's FMP plan gates the `quote` endpoint to a
small set of large-cap tickers — every ETF and several smaller holdings
402'd, which silently understated NAV (positions with no price contribute
nothing to it). Current price and historical bars come from
sources/yfinance_source.py (free, no key, confirmed to cover every ticker
FMP's quote endpoint rejected) — `get_quote` is not called at all anymore
(see below for why that's also correctness, not just budget).

**Fundamentals source order, and why it flipped.** A second live run found
the SAME plan also gates `income-statement`/`cash-flow-statement` for the
same tickers — and exhausted the 250-calls/day budget in one run of just 16
positions. `_income_statement`/`_cash_flow_statement` now try **yfinance
first, FMP as fallback** — inverted from an earlier version of this module
that tried FMP first. yfinance is free and uncapped, proven reliable for
every real ticker tested (see sources/yfinance_source.py's verified field
map), and a *failed* FMP call still counts against the 250/day budget with
nothing cached to show for it (FileCache only caches successes) — trying
FMP first meant paying that cost on every gated ticker, every run, forever.
Earnings surprises, analyst estimates, price targets, and 13F/insider data
stay FMP-only — no yfinance equivalent to fall back to, and no gating
observed there (yet). `get_sector` stays on FMP's profile endpoint too.

**A real bug this surfaced, fixed alongside it**: `quote.get("pe")`,
`quote.get("avgVolume")`, and `profile.get("volAvg")` were all wrong field
names against the current stable API — checked directly against real
cached responses. FMP's `quote` has neither `pe` nor `avgVolume` at all;
`profile` has `averageVolume` (not `volAvg`) and no `pe` field either. This
meant `avg_daily_volume_usd` (liquidity-gate-blocking) and `trailing_pe`
(valuation-band, flag-only) had silently been None for every ticker in
every prior run — harmless for held positions (held_override bypasses the
liquidity gate) but would have wrongly excluded any new, non-held candidate
on a broken ADV check. Fixed: `avg_daily_volume_usd` now reads
`profile["averageVolume"]`; `trailing_pe` is computed from
`price / income_statement[0]["eps"]` (eps is already fetched for the
revenue-growth calc, and verified to match FMP exactly — see
sources/yfinance_source.py) since no FMP/yfinance field supplies P/E
directly.

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
  computed normally, from yfinance bars.
* Every FMP field access uses `.get()` with a None fallback rather than
  asserting a field exists — the free tier's exact response shape wasn't
  verified line-by-line before this was written (the pe/avgVolume bug above
  is exactly that risk materializing once). A missing field degrades to a
  failed gate or a None in the research context, not a crash — the same
  "surface, don't hide" philosophy as the rest of this codebase.
"""

from __future__ import annotations

from agents.screener import ScreenerInput
from core.orchestrator import MarketDataGateway
from sources.fmp import FMPClient
from sources.prices import compute_technical_snapshot
from sources.yfinance_source import YFinanceClient


def _latest_revenue_growth_pct(income_statements: list[dict]) -> float | None:
    """YoY growth from the two most recent annual periods, if both are present."""
    if len(income_statements) < 2:
        return None
    latest = income_statements[0].get("revenue")
    prior = income_statements[1].get("revenue")
    if latest is None or prior in (None, 0):
        return None
    return (latest - prior) / prior * 100


def _trailing_pe(price: float | None, income_statements: list[dict]) -> float | None:
    """price / most-recent EPS — neither FMP's quote/profile nor yfinance
    expose P/E directly (see module docstring), but both sources' income
    statements carry eps, already fetched for the revenue-growth calc."""
    if not price or not income_statements:
        return None
    eps = income_statements[0].get("eps")
    if not eps or eps <= 0:
        return None
    return price / eps


class LiveMarketDataGateway:
    def __init__(
        self,
        fmp_client: FMPClient,
        yf_client: YFinanceClient,
        cluster_overrides: dict[str, str] | None = None,
        etf_tickers: list[str] | None = None,
    ):
        self.fmp = fmp_client
        self.yf = yf_client
        self.cluster_overrides = {k.upper(): v for k, v in (cluster_overrides or {}).items()}
        self.etf_tickers = {t.upper() for t in (etf_tickers or [])}
        self._spy_bars_cache = None  # YFinanceClient itself caches the fetch; this avoids re-parsing per ticker

    def _spy_bars(self):
        if self._spy_bars_cache is None:
            self._spy_bars_cache = self.yf.get_historical_bars("SPY")
        return self._spy_bars_cache

    @staticmethod
    def _safe(fetch_fn, default):
        """Run one call; on failure, return `default` with the error folded
        in (a dict gets an "error" key, a list gets one error entry) rather
        than propagating — a single unavailable field must not take down
        the whole research context."""
        try:
            return fetch_fn()
        except Exception as exc:  # noqa: BLE001
            if isinstance(default, dict):
                return {**default, "error": str(exc)}
            if isinstance(default, list):
                return [*default, {"error": str(exc)}]
            return default

    def _income_statement(self, ticker: str, limit: int) -> tuple[list[dict], str]:
        """yfinance first (free, uncapped, verified reliable); FMP fallback
        only if yfinance itself has nothing — see module docstring for why
        this order flipped from an FMP-first original. Returns (rows,
        source) so callers can note in the research context which one
        actually served the data."""
        try:
            return self.yf.get_income_statement(ticker, limit=limit), "yfinance"
        except Exception as yf_exc:  # noqa: BLE001
            try:
                return self.fmp.get_income_statement(ticker, limit=limit), "fmp_fallback"
            except Exception as fmp_exc:  # noqa: BLE001
                raise RuntimeError(
                    f"income statement unavailable for {ticker}: yfinance failed ({yf_exc}), "
                    f"FMP fallback also failed ({fmp_exc})"
                ) from fmp_exc

    def _cash_flow_statement(self, ticker: str, limit: int) -> tuple[list[dict], str]:
        try:
            return self.yf.get_cash_flow_statement(ticker, limit=limit), "yfinance"
        except Exception as yf_exc:  # noqa: BLE001
            try:
                return self.fmp.get_cash_flow_statement(ticker, limit=limit), "fmp_fallback"
            except Exception as fmp_exc:  # noqa: BLE001
                raise RuntimeError(
                    f"cash flow statement unavailable for {ticker}: yfinance failed ({yf_exc}), "
                    f"FMP fallback also failed ({fmp_exc})"
                ) from fmp_exc

    # ------------------------------------------------------------ screener

    def get_screener_input(self, ticker: str, is_held: bool) -> ScreenerInput:
        is_etf = ticker.upper() in self.etf_tickers
        profile = self.fmp.get_profile(ticker)
        # No FMP `quote` call here at all — price comes from yfinance below,
        # and quote has neither `pe` nor `avgVolume` on the current stable
        # API anyway (see module docstring), so it bought nothing but budget
        # spent on a heavily-gated endpoint.
        # ETFs skip the fundamentals fetch entirely — no income statement
        # exists to try yfinance-then-FMP on, so attempting it would just be
        # two guaranteed failures before falling through to the same result
        # ScreenerInput(is_etf=True) already produces.
        if is_etf:
            free_cash_flow = None
            revenue_growth_pct = None
            income = []
        else:
            income, _ = self._income_statement(ticker, limit=2)
            cash_flow, _ = self._cash_flow_statement(ticker, limit=1)
            free_cash_flow = cash_flow[0].get("freeCashFlow") if cash_flow else None
            revenue_growth_pct = _latest_revenue_growth_pct(income)
        bars = self.yf.get_historical_bars(ticker)

        technical = compute_technical_snapshot(bars, spy_bars=self._spy_bars(), sector_bars=None)

        price = self.yf.get_current_price(ticker)
        avg_volume = profile.get("averageVolume")
        adv_usd = (avg_volume * price) if (avg_volume and price) else None

        return ScreenerInput(
            ticker=ticker,
            market_cap_usd=profile.get("mktCap"),
            avg_daily_volume_usd=adv_usd,
            technical=technical,
            trailing_pe=_trailing_pe(price, income),
            free_cash_flow=free_cash_flow,
            revenue_growth_pct=revenue_growth_pct,
            days_to_earnings=None,  # see module docstring
            is_held=is_held,
            is_etf=is_etf,
        )

    # ------------------------------------------------------------ research

    def get_research_context(self, ticker: str) -> str:
        # Every field fetch is defensive — confirmed empirically during
        # development that even "core" resources (earnings-surprises,
        # insider-trading, quote itself) can fail on a real account while
        # others (profile, income-statement) work fine. One bad sub-fetch
        # degrades that field to an error note, not a crashed memo — this is
        # what makes it safe for the orchestrator to call this per-ticker
        # without its own try/except around every field.
        is_etf = ticker.upper() in self.etf_tickers
        profile = self._safe(lambda: self.fmp.get_profile(ticker), {})
        current_price = self._safe(lambda: self.yf.get_current_price(ticker), None)

        if is_etf:
            # An ETF has no income statement, earnings surprises, analyst
            # estimates, or insider trades in any meaningful sense — these
            # aren't "unavailable data", they're the wrong question to ask
            # of a fund. Skip the fetches rather than attempt-and-degrade.
            fundamentals_lines = ["Fundamentals: not applicable — this is an ETF (technicals-only)."]
        else:
            income, income_source = self._safe(lambda: self._income_statement(ticker, limit=3), ([], "unavailable"))
            cash_flow, cash_flow_source = self._safe(lambda: self._cash_flow_statement(ticker, limit=3), ([], "unavailable"))
            earnings = self._safe(lambda: self.fmp.get_earnings_surprises(ticker, limit=4), [])
            estimates = self._safe(lambda: self.fmp.get_analyst_estimates(ticker, limit=2), [])
            price_target = self._safe(lambda: self.fmp.get_price_target_summary(ticker), {})
            ownership = self._safe(lambda: self.fmp.get_institutional_ownership(ticker), [])
            insider = self._safe(lambda: self.fmp.get_insider_trading(ticker, limit=20), [])
            fundamentals_lines = [
                f"P/E: {_trailing_pe(current_price, income)}",
                f"Income statements (most recent first, source={income_source}): {income}",
                f"Cash flow statements (most recent first, source={cash_flow_source}): {cash_flow}",
                f"Earnings surprises (most recent first): {earnings}",
                f"Analyst estimates: {estimates}",
                f"Price target summary: {price_target}",
                f"13F institutional ownership: {ownership}",
                f"Insider trading (last 20): {insider}",
            ]

        bars = self.yf.get_historical_bars(ticker)
        technical = compute_technical_snapshot(bars, spy_bars=self._spy_bars(), sector_bars=None)

        lines = [
            f"Company: {profile.get('companyName', ticker)} ({ticker})",
            f"Sector: {profile.get('sector')} / Industry: {profile.get('industry')}",
            f"Market cap: {profile.get('mktCap')}",
            f"Price: {current_price}",  # current_price from yfinance, not FMP quote
            f"Description: {profile.get('description', '')[:1000]}",
            "",
            *fundamentals_lines,
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
        return self.yf.get_current_price(ticker)

    # ------------------------------------------------------- sector/cluster

    def get_sector(self, ticker: str) -> str | None:
        return self.fmp.get_profile(ticker).get("sector")

    def get_cluster(self, ticker: str) -> str | None:
        return self.cluster_overrides.get(ticker.upper())
