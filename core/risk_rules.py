"""Risk Manager — §10 step 5, deterministic, pure functions, no I/O, no LLM
(§5.3). "Any of these generates a SELL or TRIM" — this module decides that;
Order Builder (not yet built — not a numbered §10 step) turns a decision into
an actual limit order.

§5.3's gate order for a new position: kill switches (daily loss, drawdown) →
daily proposal cap → position sizing from conviction and volatility,
hard-capped → concentration limits → correlated cluster cap → cash
available. That ordering is implemented as a pipeline in `size_new_position`
plus the two run-level checks (`check_kill_switches`,
`enforce_daily_proposal_cap`) that apply once per run rather than per
candidate.

Two formulas §5.3 names but doesn't specify numerically — flagged here and
in config.yaml, not silently guessed:

* **Volatility-adjusted sizing.** The conviction-implied target size
  (`activation_threshold_pct`, conviction-scaled per §5.3's table) is scaled
  down when a name's ATR-as-%-of-price exceeds a "normal" reference level
  (`risk.reference_atr_pct_of_price`), and never scaled up for low
  volatility — conviction alone sets the ceiling. The multiplier is floored
  at `risk.min_volatility_size_multiplier` so an extremely volatile name
  still gets some allocation rather than being sized to near-zero.
* **Thesis decay.** A conviction drop since entry of at least
  `risk.thesis_decay_trigger_pts` counts as decay. §3's NBIS example (peak
  conviction 68 → 61, an 7-point drop, still just "decaying" in the
  watchlist, not yet a forced exit) is consistent with a double-digit
  trigger threshold, but the spec never states one.

Both are conservative, reviewable defaults — change them in config.yaml,
not by editing this file, per §8.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from core.config import ConvictionScalingConfig, RiskConfig


def lerp_by_conviction(score: float, at_0: float, at_100: float) -> float:
    score = max(0.0, min(100.0, score))
    return at_0 + (score / 100.0) * (at_100 - at_0)


def update_peak_price(
    current_peak: float | None,
    current_price: float,
    avg_cost: float,
    conviction_score: float | None,
    scaling: ConvictionScalingConfig,
) -> float | None:
    """§6: "peak_price_since_activation must be updated every run and
    persisted... Never recompute it from scratch." This is that one-step
    update — call it once per run per held position and persist the result
    to positions.peak_price_since_activation; don't rebuild it from price
    history each time.

    But it's the *post-activation* peak (§3.5 / ZMONEY-CONTEXT.md) — a
    position with no peak yet only gets one once its unrealized gain from
    avg_cost clears its conviction-scaled activation_threshold_pct. Until
    then this returns None, so trailing_stop_breached has nothing to
    breach. Once activated, the running max persists forward even if price
    later pulls back under that threshold — activation is a one-way gate,
    not a re-checked condition.
    """
    if current_peak is not None:
        return max(current_peak, current_price)
    if not avg_cost or conviction_score is None:
        return None
    gain_pct = (current_price - avg_cost) / avg_cost * 100.0
    threshold = lerp_by_conviction(
        conviction_score, scaling.activation_threshold_pct.at_0, scaling.activation_threshold_pct.at_100
    )
    if gain_pct < threshold:
        return None
    return current_price


# --------------------------------------------------------------- kill switches

@dataclass
class KillSwitchStatus:
    triggered: bool
    reasons: list[str] = field(default_factory=list)


def check_kill_switches(daily_loss_pct: float, drawdown_pct: float, config: RiskConfig) -> KillSwitchStatus:
    """`daily_loss_pct` and `drawdown_pct` are loss magnitudes (e.g. 4.0 means
    down 4%), not signed returns. Triggering either halts all new proposals
    for the run — held-position exit logic (trailing stop etc.) is untouched;
    a kill switch stops you from digging deeper, not from getting out."""
    reasons = []
    if daily_loss_pct >= config.max_daily_loss_pct:
        reasons.append(f"daily loss {daily_loss_pct:.1f}% >= cap {config.max_daily_loss_pct:.1f}%")
    if drawdown_pct >= config.max_drawdown_pct:
        reasons.append(f"drawdown {drawdown_pct:.1f}% >= cap {config.max_drawdown_pct:.1f}%")
    return KillSwitchStatus(triggered=bool(reasons), reasons=reasons)


# ------------------------------------------------------------------- sizing

@dataclass
class SizingResult:
    approved: bool
    position_pct: float
    position_usd: float
    reasons: list[str] = field(default_factory=list)
    conviction_target_pct: float = 0.0
    volatility_multiplier: float = 1.0


def volatility_size_multiplier(atr_pct_of_price: float | None, config: RiskConfig) -> float:
    if atr_pct_of_price is None or atr_pct_of_price <= 0:
        return 1.0
    if atr_pct_of_price <= config.reference_atr_pct_of_price:
        return 1.0
    raw = config.reference_atr_pct_of_price / atr_pct_of_price
    return max(config.min_volatility_size_multiplier, min(1.0, raw))


def size_new_position(
    conviction_score: float,
    atr_pct_of_price: float | None,
    nav_usd: float,
    sector: str | None,
    cluster: str | None,
    current_sector_pct: dict[str, float],
    current_cluster_pct: dict[str, float],
    cash_available_usd: float,
    scaling: ConvictionScalingConfig,
    config: RiskConfig,
) -> SizingResult:
    """Applies §5.3's ordered caps for a single candidate: conviction+
    volatility target -> max_position_pct -> sector room -> cluster room ->
    cash available -> min_order_value_usd floor. Each cap can only shrink the
    size further; nothing after the first step can increase it."""
    reasons: list[str] = []

    conviction_target = lerp_by_conviction(
        conviction_score, scaling.activation_threshold_pct.at_0, scaling.activation_threshold_pct.at_100
    )
    vol_multiplier = volatility_size_multiplier(atr_pct_of_price, config)
    pct = conviction_target * vol_multiplier

    if pct > config.max_position_pct:
        reasons.append(f"capped at max_position_pct {config.max_position_pct:.1f}%")
        pct = config.max_position_pct

    if sector is not None:
        sector_room = max(0.0, config.max_sector_pct - current_sector_pct.get(sector, 0.0))
        if pct > sector_room:
            reasons.append(f"capped by sector room {sector_room:.1f}% (sector {sector})")
            pct = sector_room

    if cluster is not None:
        cluster_room = max(0.0, config.max_correlated_cluster_pct - current_cluster_pct.get(cluster, 0.0))
        if pct > cluster_room:
            reasons.append(f"capped by correlated-cluster room {cluster_room:.1f}% (cluster {cluster})")
            pct = cluster_room

    position_usd = nav_usd * (pct / 100.0)
    if position_usd > cash_available_usd:
        reasons.append(f"capped by cash available ${cash_available_usd:,.0f}")
        position_usd = cash_available_usd
        pct = (position_usd / nav_usd * 100.0) if nav_usd > 0 else 0.0

    if position_usd < config.min_order_value_usd:
        reasons.append(f"below min_order_value_usd ${config.min_order_value_usd:,.0f}")
        return SizingResult(
            approved=False,
            position_pct=0.0,
            position_usd=0.0,
            reasons=reasons,
            conviction_target_pct=conviction_target,
            volatility_multiplier=vol_multiplier,
        )

    return SizingResult(
        approved=True,
        position_pct=pct,
        position_usd=position_usd,
        reasons=reasons,
        conviction_target_pct=conviction_target,
        volatility_multiplier=vol_multiplier,
    )


@dataclass
class ScoredProposal:
    ticker: str
    conviction: float


def enforce_daily_proposal_cap(proposals: list[ScoredProposal], config: RiskConfig) -> list[ScoredProposal]:
    """Trims to `max_daily_proposals`, keeping the highest-conviction names.
    Applied to new-BUY proposals only — held-position exits aren't capped,
    since suppressing a stop-loss to make room quota would defeat the point
    of having one."""
    ranked = sorted(proposals, key=lambda p: p.conviction, reverse=True)
    return ranked[: config.max_daily_proposals]


# ---------------------------------------------------------- held-position exits

ExitTriggerType = Literal["TRAILING_STOP", "PROFIT_BAND", "THESIS_DECAY", "HARD_STOP"]


@dataclass
class ExitTrigger:
    type: ExitTriggerType
    detail: dict


@dataclass
class HeldPositionEvaluation:
    ticker: str
    triggers: list[ExitTrigger] = field(default_factory=list)

    @property
    def has_exit_signal(self) -> bool:
        return bool(self.triggers)

    @property
    def primary_trigger(self) -> ExitTrigger | None:
        """§5.3 lists them in priority order: trailing stop breach · profit
        band crossed · thesis decay. First triggered in that order wins when
        a single label is needed (e.g. proposals.trigger_type).
        CONVICTION_FLOOR (not in §5.3, user-requested) is checked last —
        it's the catch-all for a position none of the other three caught,
        so it never outranks a real price- or decay-based signal."""
        return self.triggers[0] if self.triggers else None


def trailing_stop_breached(
    current_price: float,
    peak_price: float | None,
    atr_14: float | None,
    conviction_score: float,
    scaling: ConvictionScalingConfig,
) -> tuple[bool, dict]:
    multiple = lerp_by_conviction(
        conviction_score, scaling.trailing_stop_atr_multiple.at_0, scaling.trailing_stop_atr_multiple.at_100
    )
    if peak_price is None or atr_14 is None or atr_14 <= 0:
        return False, {"atr_multiple": multiple, "reason": "insufficient data"}
    stop_price = peak_price - multiple * atr_14
    breached = current_price <= stop_price
    return breached, {
        "atr_multiple": multiple,
        "peak_price": peak_price,
        "stop_price": stop_price,
        "current_price": current_price,
    }


def profit_band_crossed(
    current_price: float, avg_cost: float, conviction_score: float, scaling: ConvictionScalingConfig
) -> tuple[bool, dict]:
    threshold = lerp_by_conviction(
        conviction_score, scaling.profit_taking_start_pct.at_0, scaling.profit_taking_start_pct.at_100
    )
    if not avg_cost:
        return False, {"threshold_pct": threshold, "reason": "no cost basis"}
    gain_pct = (current_price - avg_cost) / avg_cost * 100.0
    return gain_pct >= threshold, {"threshold_pct": threshold, "gain_pct": gain_pct}


def hard_stop_breached(current_price: float, avg_cost: float, hard_stop_pct: float) -> tuple[bool, dict]:
    """SPECULATIVE's only exit besides the 15%-NAV reclass (Part 4): an
    absolute floor at hard_stop_pct from avg_cost (e.g. -60), unlike
    TRAILING_STOP/PROFIT_BAND/THESIS_DECAY/CONVICTION_FLOOR, none of which
    apply to this sleeve."""
    if not avg_cost:
        return False, {"reason": "no cost basis"}
    gain_pct = (current_price - avg_cost) / avg_cost * 100.0
    return gain_pct <= hard_stop_pct, {"gain_pct": gain_pct, "hard_stop_pct": hard_stop_pct}


def thesis_decay_triggered(
    conviction_now: float, conviction_at_entry: float | None, config: RiskConfig
) -> tuple[bool, dict]:
    if conviction_at_entry is None:
        return False, {"reason": "no conviction_at_entry recorded"}
    drop = conviction_at_entry - conviction_now
    return drop >= config.thesis_decay_trigger_pts, {
        "conviction_at_entry": conviction_at_entry,
        "conviction_now": conviction_now,
        "drop_pts": drop,
        "threshold_pts": config.thesis_decay_trigger_pts,
    }


def conviction_floor_triggered(conviction_now: float, config: RiskConfig) -> tuple[bool, dict]:
    """User-requested absolute floor: unlike trailing-stop/profit-band
    (need favorable price action) and thesis-decay (needs a recorded entry
    baseline), this fires on conviction_now alone — the trigger of last
    resort for a position that's just bad, never having gone up and never
    having had a baseline to decay from. See RiskConfig.min_hold_conviction."""
    return conviction_now < config.min_hold_conviction, {
        "conviction_now": conviction_now,
        "min_hold_conviction": config.min_hold_conviction,
    }


def evaluate_held_position(
    ticker: str,
    current_price: float,
    avg_cost: float,
    peak_price: float | None,
    atr_14: float | None,
    conviction_now: float,
    conviction_at_entry: float | None,
    scaling: ConvictionScalingConfig,
    config: RiskConfig,
    conviction_is_fresh: bool = True,
    sleeve: str = "SWING",
    hard_stop_pct: float | None = None,
) -> HeldPositionEvaluation:
    """`conviction_is_fresh=False` means `conviction_now` is a fallback, not
    a real score computed this run (see core/orchestrator.py) — thesis-decay
    is already guarded by `conviction_at_entry` being passed as None in that
    case, but the conviction floor has no such guard of its own, since it
    only looks at conviction_now. Suppressing it here keeps both triggers
    off a fabricated number, not just the one whose guard happened to cover it.

    `sleeve` gates which exit machinery applies at all (user-requested
    sleeve architecture): CORE and HEDGE_CASH get no signal-based exits
    whatsoever — they only ever exit via the concentration-based runner-rule
    trim, which lives outside this function. SPECULATIVE swaps all four
    triggers for a single hard_stop_pct floor. Only SWING runs the original
    four, in their original priority order."""
    if sleeve in ("CORE", "HEDGE_CASH"):
        return HeldPositionEvaluation(ticker=ticker, triggers=[])

    if sleeve == "SPECULATIVE":
        triggers: list[ExitTrigger] = []
        if hard_stop_pct is not None:
            stop_hit, stop_detail = hard_stop_breached(current_price, avg_cost, hard_stop_pct)
            if stop_hit:
                triggers.append(ExitTrigger(type="HARD_STOP", detail=stop_detail))
        return HeldPositionEvaluation(ticker=ticker, triggers=triggers)

    triggers = []

    stop_hit, stop_detail = trailing_stop_breached(current_price, peak_price, atr_14, conviction_now, scaling)
    if stop_hit:
        triggers.append(ExitTrigger(type="TRAILING_STOP", detail=stop_detail))

    profit_hit, profit_detail = profit_band_crossed(current_price, avg_cost, conviction_now, scaling)
    if profit_hit:
        triggers.append(ExitTrigger(type="PROFIT_BAND", detail=profit_detail))

    decay_hit, decay_detail = thesis_decay_triggered(conviction_now, conviction_at_entry, config)
    if decay_hit:
        triggers.append(ExitTrigger(type="THESIS_DECAY", detail=decay_detail))

    if conviction_is_fresh:
        floor_hit, floor_detail = conviction_floor_triggered(conviction_now, config)
        if floor_hit:
            triggers.append(ExitTrigger(type="CONVICTION_FLOOR", detail=floor_detail))

    return HeldPositionEvaluation(ticker=ticker, triggers=triggers)
