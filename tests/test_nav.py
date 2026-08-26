import datetime as dt

import pytest

from core.models import Run
from core.money import CurrencyMismatch, Money, usd
from core.nav import compute_nav, record_nav


def dt_(days_ago: float, base: dt.datetime | None = None) -> dt.datetime:
    base = base or dt.datetime(2026, 8, 25, 12, 0, 0)
    return base - dt.timedelta(days=days_ago)


def make_run(session, as_of):
    run = Run(started_at=as_of, finished_at=None, status="running", config_snapshot_json="{}")
    session.add(run)
    session.flush()
    return run


class TestComputeNav:
    def test_sums_position_values_and_cash(self):
        assert compute_nav([usd(1000.0), usd(2500.0)], cash=usd(500.0)) == usd(4000.0)

    def test_empty_positions_is_just_cash(self):
        assert compute_nav([], cash=usd(1000.0)) == usd(1000.0)

    def test_mismatched_currency_raises(self):
        with pytest.raises(CurrencyMismatch):
            compute_nav([Money(1000.0, "SGD")], cash=usd(500.0))


class TestRecordNav:
    def test_first_run_starts_drawdown_and_daily_loss_at_zero(self, session):
        run = make_run(session, dt_(0))
        status = record_nav(session, run.id, nav=usd(100_000), as_of=dt_(0))
        assert status.nav == usd(100_000)
        assert status.peak_nav == usd(100_000)
        assert status.drawdown_pct == 0.0
        assert status.daily_loss_pct == 0.0

    def test_nav_increase_raises_peak_no_drawdown(self, session):
        run1 = make_run(session, dt_(1))
        record_nav(session, run1.id, nav=usd(100_000), as_of=dt_(1))
        run2 = make_run(session, dt_(0))
        status = record_nav(session, run2.id, nav=usd(110_000), as_of=dt_(0))
        assert status.peak_nav == usd(110_000)
        assert status.drawdown_pct == 0.0
        assert status.daily_loss_pct == 0.0

    def test_nav_decrease_produces_drawdown_and_daily_loss(self, session):
        run1 = make_run(session, dt_(1))
        record_nav(session, run1.id, nav=usd(100_000), as_of=dt_(1))
        run2 = make_run(session, dt_(0))
        status = record_nav(session, run2.id, nav=usd(90_000), as_of=dt_(0))
        assert status.peak_nav == usd(100_000)  # peak preserved from before
        assert status.drawdown_pct == pytest.approx(10.0)
        assert status.daily_loss_pct == pytest.approx(10.0)

    def test_drawdown_persists_after_partial_recovery(self, session):
        r1 = make_run(session, dt_(2))
        record_nav(session, r1.id, nav=usd(100_000), as_of=dt_(2))
        r2 = make_run(session, dt_(1))
        record_nav(session, r2.id, nav=usd(80_000), as_of=dt_(1))  # -20% drawdown
        r3 = make_run(session, dt_(0))
        status = record_nav(session, r3.id, nav=usd(90_000), as_of=dt_(0))  # partial recovery
        assert status.peak_nav == usd(100_000)  # still the old peak
        assert status.drawdown_pct == pytest.approx(10.0)  # 10% below peak, not 0
        assert status.daily_loss_pct == 0.0  # up from yesterday's 80k, no daily loss

    def test_only_compares_against_the_single_most_recent_snapshot(self, session):
        r1 = make_run(session, dt_(3))
        record_nav(session, r1.id, nav=usd(100_000), as_of=dt_(3))
        r2 = make_run(session, dt_(2))
        record_nav(session, r2.id, nav=usd(95_000), as_of=dt_(2))
        r3 = make_run(session, dt_(1))
        status = record_nav(session, r3.id, nav=usd(96_000), as_of=dt_(1))
        # daily_loss compares to the immediately prior run (95k), not the oldest (100k)
        assert status.daily_loss_pct == 0.0  # 96k > 95k, no loss vs yesterday
