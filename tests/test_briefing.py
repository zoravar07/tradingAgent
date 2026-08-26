import datetime as dt

import pytest

from agents.order_builder import OrderProposal
from core.briefing import (
    ActionItem,
    BookEntry,
    OvernightChange,
    PortfolioHealth,
    UnpricedPosition,
    UnresearchedHolding,
    WatchlistItem,
    assemble_blocked_briefing,
    assemble_briefing,
    render_briefing_text,
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


def book_entry(ticker="AMD", weight_pct=5.0, conviction_now=None, conviction_at_entry=None, has_exit_trigger=False, no_research_coverage=False):
    return BookEntry(
        ticker=ticker,
        qty=10,
        value_usd=1000,
        weight_pct=weight_pct,
        unrealized_pnl_pct=0.0,
        conviction_now=conviction_now,
        conviction_at_entry=conviction_at_entry,
        has_exit_trigger=has_exit_trigger,
        no_research_coverage=no_research_coverage,
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


class TestRenderBriefingText:
    def test_renders_all_sections(self):
        from core.risk_rules import KillSwitchStatus

        briefing = assemble_briefing(
            generated_at=NOW,
            actions_today=[ActionItem(order=order("ANET", 74), headline="New position", thesis_summary="strong margins")],
            watching=[WatchlistItem(ticker="CRDO", reason="near stop", distance_to_trigger_pct=3.1)],
            overnight_changes=[OvernightChange(ticker="AMD", summary="guidance raised")],
            book=[book_entry("NBIS", weight_pct=1.8, has_exit_trigger=True)],
            portfolio_health=PortfolioHealth(cash_pct=98.2, drawdown_from_peak_pct=0.0, kill_switch=KillSwitchStatus(triggered=False)),
            drift=None,
        )
        text = render_briefing_text(briefing)
        assert "ANET" in text
        assert "strong margins" in text
        assert "CRDO" in text
        assert "AMD" in text
        assert "guidance raised" in text
        assert "NBIS" in text
        assert "EXIT TRIGGERED" in text
        assert "Kill switch: OK" in text
        assert "Cash: 98.2%" in text

    def test_empty_sections_render_placeholder(self):
        briefing = assemble_briefing(
            generated_at=NOW, actions_today=[], watching=[], overnight_changes=[], book=[],
            portfolio_health=PortfolioHealth(), drift=None,
        )
        text = render_briefing_text(briefing)
        assert "(none)" in text
        assert "(no open positions)" in text

    def test_drift_warning_rendered_when_present(self):
        stale = DriftStatus(stale=True, last_import_at=None, days_since_import=None, threshold_days=7)
        briefing = assemble_briefing(
            generated_at=NOW, actions_today=[], watching=[], overnight_changes=[], book=[],
            portfolio_health=PortfolioHealth(), drift=stale,
        )
        text = render_briefing_text(briefing)
        assert "DRIFT WARNING" in text


class TestAssembleBlockedBriefing:
    def test_reason_names_the_counts(self):
        unpriced = [UnpricedPosition(ticker="CEG", error="402 restricted")]
        briefing = assemble_blocked_briefing(NOW, unpriced, tolerance=0, total_held=16)
        assert briefing.blocked is not None
        assert "1/16" in briefing.blocked.reason
        assert "tolerance: 0" in briefing.blocked.reason

    def test_every_other_section_is_empty(self):
        unpriced = [UnpricedPosition(ticker="CEG", error="402")]
        briefing = assemble_blocked_briefing(NOW, unpriced, tolerance=0, total_held=16)
        assert briefing.actions_today == []
        assert briefing.watching == []
        assert briefing.overnight_changes == []
        assert briefing.book == []
        assert briefing.drift_warning is None

    def test_carries_the_unpriced_list(self):
        unpriced = [UnpricedPosition(ticker="CEG", error="402"), UnpricedPosition(ticker="CLS", error="402")]
        briefing = assemble_blocked_briefing(NOW, unpriced, tolerance=0, total_held=16)
        assert briefing.blocked.unpriced_positions == unpriced


class TestRenderBlockedBriefing:
    def test_shows_blocked_banner_and_failures_not_normal_sections(self):
        unpriced = [UnpricedPosition(ticker="CEG", error="402 Restricted Endpoint")]
        briefing = assemble_blocked_briefing(NOW, unpriced, tolerance=0, total_held=16)
        text = render_briefing_text(briefing)
        assert "RUN BLOCKED" in text
        assert "CEG" in text
        assert "402 Restricted Endpoint" in text
        assert "Actions today" not in text  # normal sections are skipped entirely
        assert "Your book" not in text


class TestUnresearchedHoldings:
    def base_kwargs(self, **overrides):
        kwargs = dict(
            generated_at=NOW, actions_today=[], watching=[], overnight_changes=[],
            book=[], portfolio_health=PortfolioHealth(), drift=None,
        )
        kwargs.update(overrides)
        return kwargs

    def test_sorted_alphabetically_regardless_of_input_order(self):
        holdings = [UnresearchedHolding(ticker="MP", reason="x"), UnresearchedHolding(ticker="CEG", reason="y")]
        briefing = assemble_briefing(**self.base_kwargs(unresearched_holdings=holdings))
        assert [u.ticker for u in briefing.unresearched_holdings] == ["CEG", "MP"]

    def test_defaults_to_empty(self):
        briefing = assemble_briefing(**self.base_kwargs())
        assert briefing.unresearched_holdings == []

    def test_banner_appears_at_top_before_actions_and_book(self):
        holdings = [UnresearchedHolding(ticker="CEG", reason="Stage 1 data fetch failed: 402")]
        book = [book_entry("CEG", no_research_coverage=True)]
        briefing = assemble_briefing(**self.base_kwargs(unresearched_holdings=holdings, book=book))
        text = render_briefing_text(briefing)
        assert "NO RESEARCH COVERAGE" in text
        assert "CEG: Stage 1 data fetch failed: 402" in text
        # the banner appears before the normal section headers
        assert text.index("NO RESEARCH COVERAGE") < text.index("--- Actions today ---")
        assert text.index("NO RESEARCH COVERAGE") < text.index("--- Your book ---")

    def test_no_banner_when_no_unresearched_holdings(self):
        briefing = assemble_briefing(**self.base_kwargs())
        text = render_briefing_text(briefing)
        assert "NO RESEARCH COVERAGE" not in text

    def test_book_row_shows_flag_instead_of_generic_na(self):
        book = [book_entry("CEG", no_research_coverage=True)]
        briefing = assemble_briefing(**self.base_kwargs(book=book))
        text = render_briefing_text(briefing)
        assert "⚠ NO RESEARCH COVERAGE" in text
        assert "conviction n/a" not in text

    def test_ordinary_missing_conviction_without_flag_still_shows_na(self):
        # distinguishes "genuinely not researched this run" from any other
        # reason a position might lack a score, without over-claiming
        book = [book_entry("CEG", no_research_coverage=False)]
        briefing = assemble_briefing(**self.base_kwargs(book=book))
        text = render_briefing_text(briefing)
        assert "conviction n/a" in text
