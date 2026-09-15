import datetime as dt

import pytest

from core.models import PositionImport
from core.money import usd
from core.portfolio import (
    ImportedPosition,
    PortfolioError,
    ReconciliationError,
)


def dt_(days_ago: float, base: dt.datetime | None = None) -> dt.datetime:
    base = base or dt.datetime(2026, 8, 25, 12, 0, 0)
    return base - dt.timedelta(days=days_ago)


class TestSleeveAssignment:
    def test_manual_position_gets_resolved_sleeve(self, session, portfolio):
        position = portfolio.add_manual_position("VTI", qty=1, avg_cost=300.0)
        assert position.sleeve == "CORE"

    def test_manual_position_defaults_to_swing(self, session, portfolio):
        position = portfolio.add_manual_position("NVDA", qty=1, avg_cost=100.0)
        assert position.sleeve == "SWING"

    def test_mark_filled_new_buy_gets_resolved_sleeve(self, session, portfolio):
        position = portfolio.mark_filled("RKLB", "BUY", qty=10, fill_price=20.0)
        assert position.sleeve == "SPECULATIVE"

    def test_reconcile_new_row_gets_resolved_sleeve(self, session, portfolio):
        result = portfolio.reconcile([ImportedPosition(ticker="IAU", qty=5, avg_cost=80.0)])
        position = portfolio.get_position("IAU")
        assert position.sleeve == "HEDGE_CASH"

    def test_sleeve_does_not_change_on_top_up(self, session, portfolio):
        position = portfolio.mark_filled("NVDA", "BUY", qty=5, fill_price=100.0)
        assert position.sleeve == "SWING"
        position = portfolio.mark_filled("NVDA", "BUY", qty=5, fill_price=110.0)
        assert position.sleeve == "SWING"

    def test_reclassify_sleeve_updates_stored_value(self, session, portfolio):
        position = portfolio.add_manual_position("RKLB", qty=1, avg_cost=20.0)
        assert position.sleeve == "SPECULATIVE"
        updated = portfolio.reclassify_sleeve(position.id, "SWING")
        assert updated.sleeve == "SWING"
        assert portfolio.get_position("RKLB").sleeve == "SWING"


# ----------------------------------------------------------------- manual entry

class TestManualEntry:
    def test_add_manual_position(self, portfolio):
        pos = portfolio.add_manual_position("amd", qty=10, avg_cost=142.30)
        assert pos.ticker == "AMD"
        assert pos.source == "manual"
        assert pos.last_verified_at is not None

    def test_add_duplicate_ticker_rejected(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        with pytest.raises(PortfolioError):
            portfolio.add_manual_position("AMD", qty=5, avg_cost=150.00)

    def test_add_rejects_fractional_when_disallowed(self, portfolio):
        with pytest.raises(PortfolioError):
            portfolio.add_manual_position("AMD", qty=10.5, avg_cost=142.30)

    def test_edit_manual_position(self, portfolio):
        pos = portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        edited = portfolio.edit_manual_position(pos.id, qty=12, avg_cost=140.00)
        assert edited.qty == 12
        assert edited.avg_cost == 140.00

    def test_edit_unknown_field_rejected(self, portfolio):
        pos = portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        with pytest.raises(PortfolioError):
            portfolio.edit_manual_position(pos.id, ticker="NVDA")

    def test_remove_position(self, portfolio):
        pos = portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        portfolio.remove_position(pos.id)
        assert portfolio.get_position("AMD") is None

    def test_remove_unknown_position_raises(self, portfolio):
        with pytest.raises(PortfolioError):
            portfolio.remove_position(999)


# ----------------------------------------------------------------- mark-filled

class TestMarkFilled:
    def test_buy_opens_new_position(self, portfolio):
        pos = portfolio.mark_filled("ANET", "BUY", qty=3, fill_price=142.50)
        assert pos.qty == 3
        assert pos.avg_cost == 142.50
        assert pos.source == "fill"

    def test_buy_averages_into_existing_position(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=140.00)
        pos = portfolio.mark_filled("AMD", "BUY", qty=10, fill_price=160.00)
        assert pos.qty == 20
        assert pos.avg_cost == pytest.approx(150.00)

    def test_sell_partial_reduces_qty_keeps_avg_cost(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=140.00)
        pos = portfolio.mark_filled("AMD", "SELL", qty=4, fill_price=170.00)
        assert pos.qty == 6
        assert pos.avg_cost == 140.00

    def test_sell_full_closes_position(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=140.00)
        result = portfolio.mark_filled("AMD", "SELL", qty=10, fill_price=170.00)
        assert result is None
        assert portfolio.get_position("AMD") is None

    def test_sell_more_than_held_raises(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=140.00)
        with pytest.raises(PortfolioError):
            portfolio.mark_filled("AMD", "SELL", qty=11, fill_price=170.00)

    def test_sell_with_no_position_raises(self, portfolio):
        with pytest.raises(PortfolioError):
            portfolio.mark_filled("AMD", "SELL", qty=1, fill_price=170.00)

    def test_fractional_fill_rejected_when_disallowed(self, portfolio):
        with pytest.raises(PortfolioError):
            portfolio.mark_filled("AMD", "BUY", qty=2.5, fill_price=140.00)

    def test_unknown_action_raises(self, portfolio):
        with pytest.raises(PortfolioError):
            portfolio.mark_filled("AMD", "HOLD", qty=1, fill_price=140.00)

# ------------------------------------------------------------------ reconcile

class TestReconcile:
    def test_all_new_positions_are_added(self, portfolio):
        imported = [ImportedPosition("AMD", 10, 142.30), ImportedPosition("NBIS", 8, 218.00)]
        result = portfolio.reconcile(imported)
        assert result.summary() == {"added": 2}
        assert {p.ticker for p in portfolio.list_positions()} == {"AMD", "NBIS"}
        assert portfolio.get_position("AMD").source == "import"

    def test_matching_position_is_left_alone_but_verified(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30, opened_at=dt_(30))
        result = portfolio.reconcile([ImportedPosition("AMD", 10, 142.30)], imported_at=dt_(0))
        assert result.summary() == {"matched": 1}
        assert portfolio.get_position("AMD").last_verified_at == dt_(0)

    def test_small_cost_rounding_counts_as_matched(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        result = portfolio.reconcile([ImportedPosition("AMD", 10, 142.305)])
        assert result.summary() == {"matched": 1}

    def test_qty_mismatch_updates_to_broker_value(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        result = portfolio.reconcile([ImportedPosition("AMD", 12, 142.30)])
        assert result.summary() == {"updated": 1}
        assert portfolio.get_position("AMD").qty == 12
        assert result.items[0].detail["qty"] == {"was": 10, "now": 12}

    def test_cost_mismatch_updates_to_broker_value(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        result = portfolio.reconcile([ImportedPosition("AMD", 10, 150.00)])
        assert result.summary() == {"updated": 1}
        assert portfolio.get_position("AMD").avg_cost == 150.00

    def test_position_missing_from_csv_is_removed(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        portfolio.add_manual_position("NBIS", qty=8, avg_cost=218.00)
        result = portfolio.reconcile([ImportedPosition("AMD", 10, 142.30)])
        assert result.summary() == {"matched": 1, "removed": 1}
        assert portfolio.get_position("NBIS") is None
        assert portfolio.get_position("AMD") is not None

    def test_mixed_reconciliation(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)   # will match
        portfolio.add_manual_position("NBIS", qty=8, avg_cost=218.00)   # will be updated
        portfolio.add_manual_position("MSFT", qty=4, avg_cost=400.00)   # will be removed
        imported = [
            ImportedPosition("AMD", 10, 142.30),
            ImportedPosition("NBIS", 9, 218.00),
            ImportedPosition("VTI", 25, 275.40),  # will be added
        ]
        result = portfolio.reconcile(imported)
        assert result.summary() == {"matched": 1, "updated": 1, "removed": 1, "added": 1}
        assert {p.ticker for p in portfolio.list_positions()} == {"AMD", "NBIS", "VTI"}


# -------------------------------------------------------------------- import

# ---------------------------------------------------------------------- drift

# ------------------------------------------------------------- cash balance

class TestLatestCashBalance:
    def test_none_before_any_import(self, portfolio):
        assert portfolio.latest_cash_balance() is None



# ------------------------------------------------------------ broker sync


class TestRecordBrokerSync:
    def test_reconciles_and_records_import_with_usd_cash(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        portfolio.add_manual_position("GONE", qty=1, avg_cost=5.0)
        rows = [ImportedPosition("AMD", 10, 142.30), ImportedPosition("NBIS", 8, 218.0)]
        result = portfolio.record_broker_sync(rows, cash_usd=usd(41.91), source="flex-web-service:U1:2026-09-10T01:00:00", imported_at=dt_(0))

        assert result.summary() == {"matched": 1, "added": 1, "removed": 1}
        assert {p.ticker for p in portfolio.list_positions()} == {"AMD", "NBIS"}
        last = portfolio.last_import()
        assert last.filename.startswith("flex-web-service:") and last.rows == 2 and last.cash_usd == 41.91
        assert portfolio.latest_cash_balance() == usd(41.91)

    def test_rejects_non_usd_cash_before_touching_the_book(self, portfolio):
        from core.money import Money

        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        with pytest.raises(ReconciliationError):
            portfolio.record_broker_sync([], cash_usd=Money(1319.77, "SGD"), source="x")
        assert [p.ticker for p in portfolio.list_positions()] == ["AMD"]
        assert portfolio.last_import() is None

    def test_latest_cash_follows_the_most_recent_sync(self, portfolio):
        portfolio.record_broker_sync([], cash_usd=usd(10.0), source="day1", imported_at=dt_(1))
        portfolio.record_broker_sync([], cash_usd=usd(20.0), source="day2", imported_at=dt_(0))
        assert portfolio.latest_cash_balance() == usd(20.0)
        assert portfolio.last_import().filename == "day2"
