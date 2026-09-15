"""Sleeve bookkeeping — pure functions, no I/O, no ORM coupling. Mirrors
core/risk_rules.py's style: everything here is a deterministic calculation
over plain values, called by core/portfolio.py (assignment), core/risk_rules.py
(exit gating), and core/orchestrator.py (wiring, persistence).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.config import SleeveConfig, SleevesConfig, SpeculativeLookConfig


def resolve_sleeve(ticker: str, config: SleevesConfig) -> str:
    """CORE/HEDGE_CASH/SPECULATIVE are closed ticker lists (config-driven,
    same pattern as UniverseConfig.cluster_overrides); anything else falls
    back to default_sleeve (SWING) — every organically-screened new BUY
    lands there unless explicitly added to one of the closed lists."""
    ticker = ticker.upper()
    for name, sleeve in config.definitions.items():
        if sleeve.tickers and ticker in {t.upper() for t in sleeve.tickers}:
            return name
    return config.default_sleeve


@dataclass(frozen=True)
class SleeveDrift:
    ticker: str
    stored_sleeve: str
    resolved_sleeve: str


def find_sleeve_drift(holdings: list[tuple[str, str]], config: SleevesConfig) -> list[SleeveDrift]:
    """Startup reconciliation check: sleeve is assigned once at position-open
    time and never auto-corrected, so editing config.yaml's ticker lists
    afterward can silently orphan a position's stored sleeve. This never
    fixes anything — it only surfaces the mismatch (run_live_briefing.py
    and api/server.py log it as a warning) so the user decides."""
    drift = []
    for ticker, stored in holdings:
        resolved = resolve_sleeve(ticker, config)
        if resolved != stored:
            drift.append(SleeveDrift(ticker=ticker, stored_sleeve=stored, resolved_sleeve=resolved))
    return drift


def sleeve_room(current_pct: float, sleeve_config: SleeveConfig) -> float:
    """Same shape as size_new_position's sector_room/cluster_room: how much
    more this sleeve can absorb before hitting its upper band. Over the
    band -> zero room -> size_new_position's min_order_value_usd floor
    rejects the BUY entirely, which is "blocks new BUYs into that sleeve,"
    not a separate hard gate."""
    return max(0.0, sleeve_config.band_high_pct - current_pct)


BreachDirection = Literal["OVER", "UNDER"]


@dataclass(frozen=True)
class SleeveBreachStatus:
    direction: BreachDirection | None
    streak_days: int


def update_breach_streak(
    previous: SleeveBreachStatus, weight_pct: float, sleeve_config: SleeveConfig, margin_pct: float
) -> SleeveBreachStatus:
    """A breach only counts once it's more than margin_pct beyond the
    nearest band edge (Part 2: "a breach of more than 5 percentage points").
    The streak continues only if today's direction matches yesterday's;
    anything else (cleared, or flipped to the opposite edge) restarts it."""
    if weight_pct > sleeve_config.band_high_pct + margin_pct:
        direction: BreachDirection | None = "OVER"
    elif weight_pct < sleeve_config.band_low_pct - margin_pct:
        direction = "UNDER"
    else:
        direction = None

    if direction is None:
        return SleeveBreachStatus(direction=None, streak_days=0)
    if previous.direction == direction:
        return SleeveBreachStatus(direction=direction, streak_days=previous.streak_days + 1)
    return SleeveBreachStatus(direction=direction, streak_days=1)


def speculative_look_reasons(
    market_cap_usd: float | None,
    free_cash_flow: float | None,
    trailing_pe: float | None,
    config: SpeculativeLookConfig,
) -> list[str]:
    """Informational only — never blocks a BUY, never reclassifies it.
    Surfaced on a new BUY that defaulted to SWING so the user can manually
    reclassify to SPECULATIVE before placing the order, per explicit
    request. Missing data (None) is never treated as a positive signal —
    same "exclude, don't impute" philosophy as scoring.py's null handling."""
    reasons: list[str] = []
    if market_cap_usd is not None and market_cap_usd < config.market_cap_below_usd:
        reasons.append(
            f"market cap ${market_cap_usd:,.0f} is below the ${config.market_cap_below_usd:,.0f} speculative-look threshold"
        )
    if free_cash_flow is not None and free_cash_flow < 0:
        reasons.append("negative free cash flow")
    if trailing_pe is None:
        reasons.append("no earnings (no positive trailing P/E)")
    return reasons


def averaging_down_blocked(current_price: float, avg_cost: float) -> bool:
    """SPECULATIVE: "never averaged down" — a BUY that would add to an
    already-held SPECULATIVE position at a price below its cost basis is
    blocked outright. No caller wires this in yet: core/orchestrator.py's
    new-candidate loop already skips every ticker in held_set before sizing
    runs (see its `if ticker in held_set: continue`), so there is currently
    no code path that proposes topping up an existing position at all. This
    function exists so the rule is enforced the moment such a path is
    added, not before."""
    return current_price < avg_cost
