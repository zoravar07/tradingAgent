"""Screener — Stage 1 (§10 step 4: pure quant, no LLM, no cost) and Stage 2
(§10 step 6: Haiku triage — the first LLM integration).

§5.1's Stage 1 gates:
  liquidity (min ADV, min market cap) · price vs 50/200 DMA · relative
  strength vs sector ETF and SPY · ATR percentile · valuation bands (flag,
  don't auto-exclude) · earnings proximity flag · fundamental floor
  (positive FCF or revenue growth above threshold)

Only liquidity and the fundamental floor actually exclude a candidate — the
spec is explicit that valuation is "flag, don't auto-exclude" and earnings
proximity is a flag (used later to block new adds, §5.4's MP example), not a
gate. Price-vs-MA / relative-strength / ATR-percentile aren't framed as
gates anywhere in §5.1 either — they're characterization carried through for
Stage 2 triage, research context, and scoring's technical_momentum subscore.

§5's "held positions always enter the pipeline regardless of screener
output" is implemented as a hard override: a held position's `passed` is
forced True, but its actual gate results are preserved in `held_override`
so a decaying/illiquid held name is visible, not silently laundered through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from core.config import Stage1Config, Stage2Config
from core.llm import LLMClient, UsageRecord
from sources.prices import TechnicalSnapshot

ValuationBand = Literal["cheap", "fair", "expensive", "unknown"]


@dataclass
class ScreenerInput:
    ticker: str
    market_cap_usd: float | None
    avg_daily_volume_usd: float | None
    technical: TechnicalSnapshot
    trailing_pe: float | None = None
    free_cash_flow: float | None = None
    revenue_growth_pct: float | None = None
    days_to_earnings: int | None = None
    is_held: bool = False
    # User-requested, not in §5.1: an ETF has no income statement to have a
    # floor on — judging one on FCF/revenue growth is a category error, not
    # a data gap. Explicit flag (config.universe.etf_tickers), not inferred
    # from a data source, matching cluster_overrides' pattern — see
    # sources/live_gateway.py.
    is_etf: bool = False


@dataclass
class Stage1GateResults:
    liquidity_pass: bool
    fundamental_floor_pass: bool
    valuation_band: ValuationBand
    earnings_soon: bool


@dataclass
class Stage1Result:
    ticker: str
    passed: bool
    held_override: bool
    reasons: list[str]
    gates: Stage1GateResults
    rank_score: float | None
    is_held: bool


def _valuation_band(trailing_pe: float | None, config: Stage1Config) -> ValuationBand:
    if trailing_pe is None or trailing_pe <= 0:
        return "unknown"
    if trailing_pe <= config.valuation_pe_cheap_max:
        return "cheap"
    if trailing_pe >= config.valuation_pe_expensive_min:
        return "expensive"
    return "fair"


def _rank_score(technical: TechnicalSnapshot) -> float | None:
    """Composite used only to order non-held survivors when trimming to
    max_survivors — not a conviction score (that's scoring.py, step 5)."""
    if technical.relative_strength_vs_spy_pct is not None:
        return technical.relative_strength_vs_spy_pct
    if technical.price_vs_sma_200_pct is not None:
        return technical.price_vs_sma_200_pct
    return None


def evaluate_stage1(item: ScreenerInput, config: Stage1Config) -> Stage1Result:
    reasons: list[str] = []

    liquidity_pass = (
        item.market_cap_usd is not None
        and item.market_cap_usd >= config.min_market_cap_usd
        and item.avg_daily_volume_usd is not None
        and item.avg_daily_volume_usd >= config.min_avg_daily_volume_usd
    )
    if not liquidity_pass:
        if item.market_cap_usd is None or item.market_cap_usd < config.min_market_cap_usd:
            reasons.append("market cap below floor")
        if item.avg_daily_volume_usd is None or item.avg_daily_volume_usd < config.min_avg_daily_volume_usd:
            reasons.append("avg daily volume below floor")

    if item.is_etf:
        fundamental_floor_pass = True  # a fund has no P&L to have a floor on — exempt, not failing
        reasons.append("ETF — fundamental floor not applicable")
    else:
        positive_fcf = item.free_cash_flow is not None and item.free_cash_flow > 0
        growth_above_threshold = (
            item.revenue_growth_pct is not None and item.revenue_growth_pct >= config.min_revenue_growth_pct
        )
        fundamental_floor_pass = positive_fcf or growth_above_threshold
        if not fundamental_floor_pass:
            reasons.append("no positive FCF and revenue growth below threshold")

    gates = Stage1GateResults(
        liquidity_pass=liquidity_pass,
        fundamental_floor_pass=fundamental_floor_pass,
        valuation_band=_valuation_band(item.trailing_pe, config),
        earnings_soon=item.days_to_earnings is not None and item.days_to_earnings <= config.earnings_proximity_days,
    )

    raw_passed = liquidity_pass and fundamental_floor_pass
    passed = raw_passed or item.is_held
    held_override = item.is_held and not raw_passed
    if held_override:
        reasons.insert(0, "held — included despite failing gates")

    return Stage1Result(
        ticker=item.ticker,
        passed=passed,
        held_override=held_override,
        reasons=reasons,
        gates=gates,
        rank_score=_rank_score(item.technical),
        is_held=item.is_held,
    )


def run_stage1(items: list[ScreenerInput], config: Stage1Config) -> list[Stage1Result]:
    """Evaluate every candidate. Returns one result per input, pass or fail —
    trimming to max_survivors is a separate step (`select_survivors`) so
    callers can audit the full universe, not just what made the cut."""
    return [evaluate_stage1(item, config) for item in items]


def select_survivors(results: list[Stage1Result], config: Stage1Config) -> list[Stage1Result]:
    """Held positions always survive (§5), on top of — not counted against —
    the max_survivors cap on newly-screened candidates. Non-held survivors
    are ranked by `rank_score` (relative strength, falling back to price vs
    200-DMA) and trimmed to `max_survivors`."""
    held = [r for r in results if r.is_held]
    non_held_passed = [r for r in results if not r.is_held and r.passed]
    ranked = sorted(
        non_held_passed,
        key=lambda r: (r.rank_score is not None, r.rank_score if r.rank_score is not None else float("-inf")),
        reverse=True,
    )
    return held + ranked[: config.max_survivors]


# ---------------------------------------------------------------- Stage 2

STAGE2_SYSTEM_PROMPT = (
    "You are a quantitative pre-screen for an equity research desk. You receive one line of "
    "Stage 1 data per candidate — liquidity, momentum versus the index and moving averages, "
    "volatility regime, valuation band, revenue growth and free cash flow — and you rank the "
    "candidates by how much each merits a full research memo tonight. Use only the numbers "
    "given: no outside knowledge, no news, no recollection of the company. Score every "
    "candidate 0-100 and give a one-sentence reason that cites the figures that drove it, written in "
    "plain English a beginner can follow — say 'has gone up 20% more than the S&P 500 over three months' "
    "rather than 'RS +20%', and explain any term you must use. Return every ticker you were given, exactly once."
)

# Stage 2's job is prioritisation, not fact-finding (it decides which names
# spend a Sonnet memo), so it runs on cached Stage 1 numbers in one batched
# Haiku call per chunk — no web search. A grounded, per-name triage was
# tried (runs 6-7) and cost ~$2.60/run, ten times the memos it was
# steering; the news it found reaches the pipeline through the research
# digest instead, only for names that actually get a memo.
STAGE2_BATCH_SIZE = 40


class Stage2Score(BaseModel):
    ticker: str
    score: float = Field(ge=0, le=100)
    reason: str


class Stage2Ranking(BaseModel):
    items: list[Stage2Score]


class Stage2Verdict(BaseModel):
    """Kept for callers/tests that build a verdict directly."""

    verdict: str
    material: bool


@dataclass
class Stage2Result:
    ticker: str
    verdict: str
    material: bool  # shortlisted for a memo (non-held); held names are always researched on their own cadence
    passed: bool
    is_held: bool
    score: float | None = None
    usage: UsageRecord | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _fmt(value: float | None, spec: str = ".1f", scale: float = 1.0, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value / scale:{spec}}{suffix}"


def describe_candidate(item: ScreenerInput, result: Stage1Result) -> str:
    """One data line per candidate — the only thing Stage 2 sees."""
    t = item.technical
    return (
        f"{item.ticker}: mcap ${_fmt(item.market_cap_usd, '.1f', 1e9)}B, ADV ${_fmt(item.avg_daily_volume_usd, '.0f', 1e6)}M, "
        f"RS vs SPY 63d {_fmt(t.relative_strength_vs_spy_pct, '+.1f', 1, '%')}, "
        f"px vs 50DMA {_fmt(t.price_vs_sma_50_pct, '+.1f', 1, '%')}, px vs 200DMA {_fmt(t.price_vs_sma_200_pct, '+.1f', 1, '%')}, "
        f"ATR {_fmt(t.atr_pct_of_price, '.1f', 1, '% of price')} (pctile {_fmt(t.atr_percentile_252d, '.0f')}), "
        f"valuation {result.gates.valuation_band}, P/E {_fmt(item.trailing_pe, '.0f')}, "
        f"rev growth {_fmt(item.revenue_growth_pct, '+.0f', 1, '%')}, FCF {'positive' if (item.free_cash_flow or 0) > 0 else 'not positive'}"
        f"{', earnings within window' if result.gates.earnings_soon else ''}"
    )


def run_stage2_batch(
    llm: LLMClient,
    stage1_results: list[Stage1Result],
    config: Stage2Config,
    screener_inputs: dict[str, ScreenerInput] | None = None,
) -> list[Stage2Result]:
    """Held names never go to the model — they are researched on their own
    cadence regardless (§5). Non-held survivors are ranked in chunks of
    STAGE2_BATCH_SIZE, one structured call each; the top `max_survivors`
    by score are shortlisted. A failed chunk drops its names (surfaced as
    `error`), never the run."""
    screener_inputs = screener_inputs or {}
    held = [r for r in stage1_results if r.is_held]
    non_held = [r for r in stage1_results if not r.is_held]

    results: list[Stage2Result] = [
        Stage2Result(ticker=r.ticker, verdict="held — researched on the holdings cadence", material=False, passed=True, is_held=True)
        for r in held
    ]

    scored: dict[str, tuple[float, str, UsageRecord | None]] = {}
    failed: dict[str, str] = {}
    for start in range(0, len(non_held), config.batch_size):
        chunk = non_held[start : start + config.batch_size]
        lines = []
        for r in chunk:
            item = screener_inputs.get(r.ticker)
            lines.append(describe_candidate(item, r) if item else f"{r.ticker}: (no Stage 1 data available)")
        user_message = "Candidates:\n" + "\n".join(lines) + "\n\nRank them."
        try:
            call = llm.call_structured(
                model=config.model, system=STAGE2_SYSTEM_PROMPT, user_message=user_message,
                output_model=Stage2Ranking, max_tokens=max(600, 60 * len(chunk)),
            )
        except Exception as exc:  # noqa: BLE001 — one bad chunk must not kill the run
            for r in chunk:
                failed[r.ticker] = str(exc)
            continue
        by_ticker = {s.ticker.upper(): s for s in call.parsed.items}
        for r in chunk:
            s = by_ticker.get(r.ticker.upper())
            if s is None:
                failed[r.ticker] = "ticker missing from the ranking reply"
            else:
                scored[r.ticker] = (s.score, s.reason, call.usage)

    shortlist = {t for t, _ in sorted(scored.items(), key=lambda kv: -kv[1][0])[: config.max_survivors]}
    for r in non_held:
        if r.ticker in scored:
            score, reason, usage = scored[r.ticker]
            chosen = r.ticker in shortlist
            results.append(Stage2Result(ticker=r.ticker, verdict=reason, material=chosen, passed=chosen, is_held=False, score=score, usage=usage))
        else:
            results.append(Stage2Result(ticker=r.ticker, verdict="", material=False, passed=False, is_held=False, error=failed.get(r.ticker)))
    return results


def select_stage2_survivors(
    results: list[Stage2Result], stage1_by_ticker: dict[str, Stage1Result], config: Stage2Config
) -> list[Stage2Result]:
    """Held names always pass through (as in Stage 1); the shortlisted
    non-held names follow, best score first (Stage 1's rank breaks ties or
    stands in when a score is missing), trimmed to `max_survivors`."""
    held = [r for r in results if r.is_held]
    non_held_passed = [r for r in results if not r.is_held and r.passed]
    ranked = sorted(
        non_held_passed,
        key=lambda r: (r.score if r.score is not None else -1.0, stage1_by_ticker[r.ticker].rank_score or float("-inf")),
        reverse=True,
    )
    return held + ranked[: config.max_survivors]
