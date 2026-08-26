import datetime as dt

import pytest

from core.models import PositionImport
from core.money import usd
from core.portfolio import (
    ImportedPosition,
    PortfolioError,
    ReconciliationError,
    parse_flex_cash_balance,
    parse_flex_csv,
)
from tests.conftest import FIXTURES


def dt_(days_ago: float, base: dt.datetime | None = None) -> dt.datetime:
    base = base or dt.datetime(2026, 8, 25, 12, 0, 0)
    return base - dt.timedelta(days=days_ago)


# --------------------------------------------------------------- CSV parsing

class TestParseFlexCsv:
    def test_parses_equities_and_skips_cash_row(self):
        rows = parse_flex_csv((FIXTURES / "flex_open_positions.csv").read_text())
        tickers = {r.ticker for r in rows}
        assert tickers == {"AMD", "NBIS", "VTI"}

    def test_reads_qty_and_avg_cost(self):
        rows = {r.ticker: r for r in parse_flex_csv((FIXTURES / "flex_open_positions.csv").read_text())}
        assert rows["AMD"].qty == 10
        assert rows["AMD"].avg_cost == 142.30

    def test_derives_avg_cost_from_cost_basis_money_when_price_column_absent(self):
        csv_text = (
            "Symbol,Position,CostBasisMoney\n"
            "MSFT,4,1600.00\n"
        )
        rows = parse_flex_csv(csv_text)
        assert rows == [ImportedPosition(ticker="MSFT", qty=4, avg_cost=400.0)]

    def test_zero_quantity_rows_skipped(self):
        csv_text = "Symbol,Position,CostBasisPrice\nAMD,0,142.30\nNBIS,5,218.00\n"
        rows = parse_flex_csv(csv_text)
        assert [r.ticker for r in rows] == ["NBIS"]

    def test_missing_required_columns_raises(self):
        with pytest.raises(ReconciliationError):
            parse_flex_csv("Foo,Bar\n1,2\n")

    def test_missing_cost_column_raises(self):
        with pytest.raises(ReconciliationError):
            parse_flex_csv("Symbol,Position\nAMD,10\n")

    def test_empty_csv_raises(self):
        with pytest.raises(ReconciliationError):
            parse_flex_csv("")


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

    def test_mark_filled_updates_last_verified_at_but_not_drift(self, portfolio):
        pos = portfolio.mark_filled("AMD", "BUY", qty=10, fill_price=140.00, filled_at=dt_(0))
        assert pos.last_verified_at == dt_(0)
        # no import has ever happened — drift is still stale despite the fresh fill
        status = portfolio.check_drift(as_of=dt_(0))
        assert status.stale is True
        assert status.last_import_at is None


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

class TestImportFlexCsv:
    def test_import_creates_position_import_record(self, portfolio):
        csv_text = (FIXTURES / "flex_open_positions.csv").read_text()
        result = portfolio.import_flex_csv(csv_text, filename="flex_open_positions.csv")
        assert result.rows == 3
        last = portfolio.last_import()
        assert last.filename == "flex_open_positions.csv"
        assert last.rows == 3
        assert '"action": "added"' in last.reconciliation_json

    def test_import_populates_book(self, portfolio):
        csv_text = (FIXTURES / "flex_open_positions.csv").read_text()
        portfolio.import_flex_csv(csv_text, filename="flex_open_positions.csv")
        assert {p.ticker for p in portfolio.list_positions()} == {"AMD", "NBIS", "VTI"}

    def test_second_import_reconciles_against_first(self, portfolio):
        csv_text = (FIXTURES / "flex_open_positions.csv").read_text()
        portfolio.import_flex_csv(csv_text, filename="day1.csv")

        # AMD position grew, NBIS unchanged, VTI sold entirely, new SOFI position
        csv_day2 = (
            "AssetClass,Symbol,Position,CostBasisPrice\n"
            "STK,AMD,15,142.30\n"
            "STK,NBIS,8,218.00\n"
            "STK,SOFI,20,18.50\n"
        )
        result = portfolio.import_flex_csv(csv_day2, filename="day2.csv")
        assert result.summary() == {"updated": 1, "matched": 1, "removed": 1, "added": 1}
        assert portfolio.get_position("AMD").qty == 15
        assert portfolio.get_position("VTI") is None
        assert portfolio.get_position("SOFI") is not None


# ---------------------------------------------------------------------- drift

class TestDrift:
    def test_no_positions_no_imports_not_stale(self, portfolio):
        status = portfolio.check_drift()
        assert status.stale is False
        assert status.last_import_at is None

    def test_positions_but_never_imported_is_stale(self, portfolio):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        status = portfolio.check_drift()
        assert status.stale is True
        assert status.last_import_at is None
        assert status.days_since_import is None

    def test_recent_import_not_stale(self, portfolio, session):
        portfolio.reconcile([ImportedPosition("AMD", 10, 142.30)], imported_at=dt_(2))
        session.add(PositionImport(imported_at=dt_(2), filename="x.csv", rows=1, reconciliation_json="[]"))
        session.flush()
        status = portfolio.check_drift(as_of=dt_(0))
        assert status.stale is False
        assert status.days_since_import == pytest.approx(2.0)

    def test_old_import_is_stale(self, portfolio, session):
        portfolio.add_manual_position("AMD", qty=10, avg_cost=142.30)
        session.add(PositionImport(imported_at=dt_(10), filename="x.csv", rows=1, reconciliation_json="[]"))
        session.flush()
        status = portfolio.check_drift(as_of=dt_(0))
        assert status.stale is True
        assert status.days_since_import == pytest.approx(10.0)

    def test_import_via_import_flex_csv_clears_drift(self, portfolio):
        csv_text = (FIXTURES / "flex_open_positions.csv").read_text()
        portfolio.import_flex_csv(csv_text, filename="flex_open_positions.csv")
        status = portfolio.check_drift()
        assert status.stale is False
        assert status.threshold_days == 7

    def test_custom_threshold_respected(self, session):
        from core.config import PortfolioConfig
        from core.portfolio import PortfolioService

        svc = PortfolioService(session, config=PortfolioConfig(import_reminder_days=1))
        svc.add_manual_position("AMD", qty=10, avg_cost=142.30)
        session.add(PositionImport(imported_at=dt_(2), filename="x.csv", rows=1, reconciliation_json="[]"))
        session.flush()
        status = svc.check_drift(as_of=dt_(0))
        assert status.stale is True
        assert status.threshold_days == 1


# ------------------------------------------------------------- cash balance

class TestParseFlexCashBalance:
    def test_reads_cash_row_from_fixture(self):
        csv_text = (FIXTURES / "flex_open_positions.csv").read_text()
        assert parse_flex_cash_balance(csv_text) == usd(15320.44)

    def test_result_is_tagged_usd(self):
        csv_text = (FIXTURES / "flex_open_positions.csv").read_text()
        assert parse_flex_cash_balance(csv_text).currency == "USD"

    def test_none_when_no_cash_rows(self):
        csv_text = "AssetClass,Symbol,Position,CostBasisPrice\nSTK,AMD,10,142.30\n"
        assert parse_flex_cash_balance(csv_text) is None

    def test_none_when_no_asset_class_column(self):
        csv_text = "Symbol,Position,CostBasisPrice\nAMD,10,142.30\n"
        assert parse_flex_cash_balance(csv_text) is None

    def test_sums_multiple_cash_rows(self):
        csv_text = (
            "AssetClass,CurrencyPrimary,Symbol,Position\n"
            "CASH,USD,USD,1000.00\n"
            "CASH,USD,USD,50.25\n"
            "STK,USD,AMD,10\n"
        )
        assert parse_flex_cash_balance(csv_text) == usd(1050.25)

    def test_filters_out_non_usd_currency(self):
        csv_text = (
            "AssetClass,CurrencyPrimary,Symbol,Position\n"
            "CASH,USD,USD,1000.00\n"
            "CASH,EUR,EUR,500.00\n"
        )
        assert parse_flex_cash_balance(csv_text) == usd(1000.00)


class TestLatestCashBalance:
    def test_none_before_any_import(self, portfolio):
        assert portfolio.latest_cash_balance() is None

    def test_returns_most_recent_imports_cash(self, portfolio):
        csv_text = (FIXTURES / "flex_open_positions.csv").read_text()
        portfolio.import_flex_csv(csv_text, filename="flex_open_positions.csv")
        assert portfolio.latest_cash_balance() == usd(15320.44)

    def test_updates_on_second_import(self, portfolio):
        csv1 = "AssetClass,CurrencyPrimary,Symbol,Position,CostBasisPrice\nCASH,USD,USD,1000.00,\n"
        csv2 = "AssetClass,CurrencyPrimary,Symbol,Position,CostBasisPrice\nCASH,USD,USD,2500.00,\n"
        portfolio.import_flex_csv(csv1, filename="day1.csv")
        portfolio.import_flex_csv(csv2, filename="day2.csv")
        assert portfolio.latest_cash_balance() == usd(2500.00)
