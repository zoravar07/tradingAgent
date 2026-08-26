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


@dataclass
class PortfolioHealth:
    sleeve_weights_pct: dict[str, float] = field(default_factory=dict)
    sleeve_targets_pct: dict[str, float] = field(default_factory=dict)
    correlated_cluster_pct: dict[str, float] = field(default_factory=dict)
    cash_pct: float = 0.0
    drawdown_from_peak_pct: float = 0.0
    kill_switch: KillSwitchStatus | None = None


@dataclass
class Briefing:
    generated_at: dt.datetime
    actions_today: list[ActionItem]
    watching: list[WatchlistItem]
    overnight_changes: list[OvernightChange]
    book: list[BookEntry]
    portfolio_health: PortfolioHealth
    drift_warning: DriftStatus | None = None


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
) -> Briefing:
    return Briefing(
        generated_at=generated_at,
        actions_today=sort_actions_by_conviction(actions_today),
        watching=watching,
        overnight_changes=overnight_changes,
        book=sort_book_by_attention(book),
        portfolio_health=portfolio_health,
        drift_warning=drift if (drift is not None and drift.stale) else None,
    )
