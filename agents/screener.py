"""Screener — §10 step 4: Stage 1 only (pure quant, no LLM, no cost). Stage 2
(Haiku triage, §5.1) is build-order step 6 — the first LLM integration — and
deliberately isn't started here.

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

from dataclasses import dataclass
from typing import Literal

from core.config import Stage1Config
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
