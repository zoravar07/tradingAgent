"""Briefing assembler — §10 step 8, §4's core/briefing.py, §3's five
sections (Actions today, Watching, Overnight changes, Your book, Portfolio
health).

This module does no fetching and no deciding — everything it receives is
already computed by screener/research/scoring/risk_rules/order_builder/
portfolio. Its job is assembly: bundle those pieces into one `Briefing`
object and apply the two ordering rules §3 implies but doesn't spell out as
algorithms:

* Actions today: highest conviction first (§3's mockup shows the new BUY
  before the trim — ANET at conviction 74 before NBIS at 61).
* Your book: "Sorted by whatever needs attention most" (§3, verbatim, no
  definition given). Read here as: positions with an active exit trigger
  first, then by how far conviction has decayed since entry, then by
  portfolio weight — a documented judgment call, same pattern as the
  screener ranking calls in steps 4/6.

The drift warning (§2) is surfaced on the briefing only when it's actually
stale — a fresh import produces `drift_warning=None`, not a status object
the UI has to remember to check `.stale` on.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from agents.order_builder import OrderProposal
from core.risk_rules import KillSwitchStatus
from core.portfolio import DriftStatus


@dataclass
class ActionItem:
    order: OrderProposal
    headline: str  # e.g. "New position", "Trailing stop triggered", "Trim 50%"
    thesis_summary: str | None = None
    bear_case: str | None = None


@dataclass
class WatchlistItem:
    ticker: str
    reason: str
    distance_to_trigger_pct: float | None = None


@dataclass
class OvernightChange:
    ticker: str
    summary: str


@dataclass
class BookEntry:
    ticker: str
    qty: float
    value_usd: float
    weight_pct: float
    unrealized_pnl_pct: float
    conviction_now: float | None = None
    conviction_at_entry: float | None = None
    distance_to_trailing_stop_pct: float | None = None  # <= 0 means the stop is currently breached
    next_profit_band_pct: float | None = None
    has_exit_trigger: bool = False
    # Not in §3 — added per the user's explicit request. A held position
    # with no conviction score has no thesis-decay trigger and no
    # conviction-scaled stop/profit thresholds this run: it is effectively
    # unmonitored. "conviction n/a" in a table read too easily as routine
    # missing data rather than a real coverage gap — this flag exists so
    # the table itself says so, on top of the top-of-briefing banner
    # (see UnresearchedHolding / Briefing.unresearched_holdings below).
    no_research_coverage: bool = False


@dataclass
class UnresearchedHolding:
    ticker: str
    reason: str


@dataclass
class PortfolioHealth:
    sleeve_weights_pct: dict[str, float] = field(default_factory=dict)
    sleeve_targets_pct: dict[str, float] = field(default_factory=dict)
    correlated_cluster_pct: dict[str, float] = field(default_factory=dict)
    cash_pct: float = 0.0
    drawdown_from_peak_pct: float = 0.0
    kill_switch: KillSwitchStatus | None = None


@dataclass
class UnpricedPosition:
    ticker: str
    error: str


@dataclass
class BlockedStatus:
    """Not in §3 — added per the user's explicit request: if too many held
    positions can't be priced, NAV/weights/risk checks are meaningless, so
    the run halts with zero proposals rather than publish a confident-
    looking briefing built on a broken NAV. See core/orchestrator.py's
    pricing gate, run *before* Stage 1 so a run that's going to be blocked
    never spends on screening/research it can't use."""

    reason: str
    unpriced_positions: list[UnpricedPosition]


@dataclass
class Briefing:
    generated_at: dt.datetime
    actions_today: list[ActionItem]
    watching: list[WatchlistItem]
    overnight_changes: list[OvernightChange]
    book: list[BookEntry]
    portfolio_health: PortfolioHealth
    drift_warning: DriftStatus | None = None
    blocked: BlockedStatus | None = None
    unresearched_holdings: list[UnresearchedHolding] = field(default_factory=list)


def sort_actions_by_conviction(items: list[ActionItem]) -> list[ActionItem]:
    return sorted(items, key=lambda i: i.order.conviction, reverse=True)


def sort_book_by_attention(entries: list[BookEntry]) -> list[BookEntry]:
    def decay_pts(e: BookEntry) -> float:
        if e.conviction_now is None or e.conviction_at_entry is None:
            return 0.0
        return e.conviction_at_entry - e.conviction_now

    return sorted(
        entries,
        key=lambda e: (not e.has_exit_trigger, -decay_pts(e), -e.weight_pct),
    )


def assemble_briefing(
    *,
    generated_at: dt.datetime,
    actions_today: list[ActionItem],
    watching: list[WatchlistItem],
    overnight_changes: list[OvernightChange],
    book: list[BookEntry],
    portfolio_health: PortfolioHealth,
    drift: DriftStatus | None,
    unresearched_holdings: list[UnresearchedHolding] | None = None,
) -> Briefing:
    return Briefing(
        generated_at=generated_at,
        actions_today=sort_actions_by_conviction(actions_today),
        watching=watching,
        overnight_changes=overnight_changes,
        book=sort_book_by_attention(book),
        portfolio_health=portfolio_health,
        unresearched_holdings=sorted(unresearched_holdings or [], key=lambda u: u.ticker),
        drift_warning=drift if (drift is not None and drift.stale) else None,
    )


def assemble_blocked_briefing(
    generated_at: dt.datetime, unpriced: list[UnpricedPosition], tolerance: int, total_held: int
) -> Briefing:
    """The pricing gate's output when it trips. Every other section is
    empty on purpose — NAV underlies weight/conviction/health, and NAV is
    unknown here, so nothing else is trustworthy enough to show."""
    reason = (
        f"{len(unpriced)}/{total_held} held position(s) could not be priced this run "
        f"(tolerance: {tolerance}). NAV, weights, and risk checks would be built on an "
        f"incomplete book, so no proposals were generated."
    )
    return Briefing(
        generated_at=generated_at,
        actions_today=[],
        watching=[],
        overnight_changes=[],
        book=[],
        portfolio_health=PortfolioHealth(),
        drift_warning=None,
        blocked=BlockedStatus(reason=reason, unpriced_positions=unpriced),
    )


def render_briefing_text(briefing: Briefing) -> str:
    """Plain-text rendering of §3's five sections — a debug/CLI view for
    looking at pipeline output before there's a UI (step 10) to show it in.
    Not meant to be the UI itself."""
    lines: list[str] = []
    lines.append(f"=== Z MONEY BRIEFING — {briefing.generated_at:%Y-%m-%d %H:%M} ===")
    lines.append("")

    if briefing.blocked is not None:
        lines.append("🛑 RUN BLOCKED — no proposals generated")
        lines.append(briefing.blocked.reason)
        lines.append("")
        lines.append("Unpriced positions:")
        for u in briefing.blocked.unpriced_positions:
            lines.append(f"  {u.ticker}: {u.error}")
        return "\n".join(lines)

    if briefing.unresearched_holdings:
        n = len(briefing.unresearched_holdings)
        lines.append(f"🚨 NO RESEARCH COVERAGE — {n} held position(s) unmonitored this run:")
        for u in briefing.unresearched_holdings:
            lines.append(f"  {u.ticker}: {u.reason}")
        lines.append(
            "  These have no current conviction score: no thesis-decay trigger, no "
            "conviction-scaled stop/profit thresholds. Treat as un-reviewed, not held-and-safe."
        )
        lines.append("")

    if briefing.drift_warning is not None:
        d = briefing.drift_warning
        if d.last_import_at is None:
            lines.append("⚠ DRIFT WARNING: positions have never been imported from a broker CSV.")
        else:
            lines.append(
                f"⚠ DRIFT WARNING: last import was {d.days_since_import:.1f} days ago "
                f"(threshold {d.threshold_days} days). Positions may be stale."
            )
        lines.append("")

    lines.append("--- Actions today ---")
    if not briefing.actions_today:
        lines.append("(none)")
    for item in briefing.actions_today:
        o = item.order
        trim_note = " (trim)" if o.is_trim else ""
        lines.append(
            f"{o.action:<5} {o.ticker:<6} {o.quantity} shares   {o.order_type} ${o.limit_price:.2f}   "
            f"~${o.estimated_cost_usd:,.0f}   ({o.weight_pct:.1f}% of NAV){trim_note}"
        )
        lines.append(f"      Conviction {o.conviction:.0f} · {item.headline}")
        if item.thesis_summary:
            lines.append(f"      Why: {item.thesis_summary}")
        if item.bear_case:
            lines.append(f"      Bear case: {item.bear_case}")
        lines.append("")

    lines.append("--- Watching ---")
    if not briefing.watching:
        lines.append("(none)")
    for w in briefing.watching:
        dist = f"{w.distance_to_trigger_pct:.1f}" if w.distance_to_trigger_pct is not None else "?"
        lines.append(f"{w.ticker:<6} {w.reason} (distance {dist})")
    lines.append("")

    lines.append("--- Overnight changes ---")
    if not briefing.overnight_changes:
        lines.append("(none)")
    for c in briefing.overnight_changes:
        lines.append(f"{c.ticker:<6} {c.summary}")
    lines.append("")

    lines.append("--- Your book ---")
    if not briefing.book:
        lines.append("(no open positions)")
    for b in briefing.book:
        if b.conviction_now is not None and b.conviction_at_entry is not None:
            conv = f"conviction {b.conviction_now:.0f} (was {b.conviction_at_entry:.0f})"
        elif b.conviction_now is not None:
            # a real fresh score exists this run, just no recorded entry
            # baseline to compare it to (true for every manually-entered
            # position without a conviction_at_entry — showing "n/a" here
            # would hide a real number the run actually computed)
            conv = f"conviction {b.conviction_now:.0f} (no entry baseline)"
        elif b.no_research_coverage:
            conv = "⚠ NO RESEARCH COVERAGE"
        else:
            conv = "conviction n/a"
        flag = "  ⚠ EXIT TRIGGERED" if b.has_exit_trigger else ""
        lines.append(
            f"{b.ticker:<6} qty={b.qty:g}  value=${b.value_usd:,.0f}  weight={b.weight_pct:.1f}%  "
            f"pnl={b.unrealized_pnl_pct:+.1f}%  {conv}{flag}"
        )
    lines.append("")

    lines.append("--- Portfolio health ---")
    ph = briefing.portfolio_health
    lines.append(f"Cash: {ph.cash_pct:.1f}%   Drawdown from peak: {ph.drawdown_from_peak_pct:.1f}%")
    if ph.kill_switch is not None:
        status = "TRIGGERED — " + "; ".join(ph.kill_switch.reasons) if ph.kill_switch.triggered else "OK"
        lines.append(f"Kill switch: {status}")
    if ph.correlated_cluster_pct:
        clusters = ", ".join(f"{name} {pct:.1f}%" for name, pct in sorted(ph.correlated_cluster_pct.items()))
        lines.append(f"Correlated clusters: {clusters}")

    return "\n".join(lines)
