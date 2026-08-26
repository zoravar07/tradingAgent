import datetime as dt

import pytest

from agents.order_builder import OrderProposal
from core.briefing import (
    ActionItem,
    BookEntry,
    OvernightChange,
    PortfolioHealth,
    WatchlistItem,
    assemble_briefing,
    sort_actions_by_conviction,
    sort_book_by_attention,
)
from core.portfolio import DriftStatus

NOW = dt.datetime(2026, 8, 25, 6, 0, 0)


def order(ticker="AMD", conviction=50, action="BUY"):
    return OrderProposal(
        ticker=ticker,
        action=action,
        quantity=1,
        order_type="LIMIT",
        limit_price=100.0,
        estimated_cost_usd=100.0,
        weight_pct=1.0,
        conviction=conviction,
        trigger_type=None,
        is_trim=False,
    )


def book_entry(ticker="AMD", weight_pct=5.0, conviction_now=None, conviction_at_entry=None, has_exit_trigger=False):
    return BookEntry(
        ticker=ticker,
        qty=10,
        value_usd=1000,
        weight_pct=weight_pct,
        unrealized_pnl_pct=0.0,
        conviction_now=conviction_now,
        conviction_at_entry=conviction_at_entry,
        has_exit_trigger=has_exit_trigger,
    )


class TestSortActionsByConviction:
    def test_highest_conviction_first(self):
        items = [ActionItem(order=order("A", 40), headline="x"), ActionItem(order=order("B", 90), headline="y")]
        sorted_items = sort_actions_by_conviction(items)
        assert [i.order.ticker for i in sorted_items] == ["B", "A"]


class TestSortBookByAttention:
    def test_exit_trigger_positions_come_first(self):
        entries = [
            book_entry("CALM", weight_pct=10, has_exit_trigger=False),
            book_entry("URGENT", weight_pct=1, has_exit_trigger=True),
        ]
        sorted_entries = sort_book_by_attention(entries)
        assert sorted_entries[0].ticker == "URGENT"

    def test_larger_decay_ranks_above_smaller_decay(self):
        entries = [
            book_entry("SMALL_DECAY", conviction_now=65, conviction_at_entry=70),  # -5
            book_entry("BIG_DECAY", conviction_now=40, conviction_at_entry=68),  # -28, NBIS-ish
        ]
        sorted_entries = sort_book_by_attention(entries)
        assert sorted_entries[0].ticker == "BIG_DECAY"

    def test_falls_back_to_weight_when_no_trigger_or_decay(self):
        entries = [book_entry("SMALL", weight_pct=1), book_entry("BIG", weight_pct=10)]
        sorted_entries = sort_book_by_attention(entries)
        assert sorted_entries[0].ticker == "BIG"

    def test_exit_trigger_beats_decay_and_weight(self):
        entries = [
            book_entry("HUGE_DECAY_NO_TRIGGER", weight_pct=20, conviction_now=10, conviction_at_entry=90),
            book_entry("SMALL_WITH_TRIGGER", weight_pct=1, has_exit_trigger=True),
        ]
        sorted_entries = sort_book_by_attention(entries)
        assert sorted_entries[0].ticker == "SMALL_WITH_TRIGGER"


class TestAssembleBriefing:
    def base_kwargs(self, **overrides):
        kwargs = dict(
            generated_at=NOW,
            actions_today=[ActionItem(order=order("A", 40), headline="x"), ActionItem(order=order("B", 90), headline="y")],
            watching=[WatchlistItem(ticker="CRDO", reason="near trailing stop")],
            overnight_changes=[OvernightChange(ticker="AMD", summary="guidance raised")],
            book=[book_entry("A", weight_pct=1), book_entry("B", weight_pct=10)],
            portfolio_health=PortfolioHealth(cash_pct=5.0),
            drift=None,
        )
        kwargs.update(overrides)
        return kwargs

    def test_assembles_all_sections(self):
        briefing = assemble_briefing(**self.base_kwargs())
        assert briefing.generated_at == NOW
        assert len(briefing.actions_today) == 2
        assert len(briefing.watching) == 1
        assert len(briefing.overnight_changes) == 1
        assert len(briefing.book) == 2

    def test_actions_sorted_within_assembly(self):
        briefing = assemble_briefing(**self.base_kwargs())
        assert [i.order.ticker for i in briefing.actions_today] == ["B", "A"]

    def test_book_sorted_within_assembly(self):
        briefing = assemble_briefing(**self.base_kwargs())
        assert [e.ticker for e in briefing.book] == ["B", "A"]

    def test_fresh_drift_suppressed(self):
        fresh = DriftStatus(stale=False, last_import_at=NOW, days_since_import=1.0, threshold_days=7)
        briefing = assemble_briefing(**self.base_kwargs(drift=fresh))
        assert briefing.drift_warning is None

    def test_stale_drift_surfaced(self):
        stale = DriftStatus(stale=True, last_import_at=None, days_since_import=None, threshold_days=7)
        briefing = assemble_briefing(**self.base_kwargs(drift=stale))
        assert briefing.drift_warning is stale

    def test_no_import_ever_drift_surfaced(self):
        briefing = assemble_briefing(**self.base_kwargs(drift=None))
        assert briefing.drift_warning is None
