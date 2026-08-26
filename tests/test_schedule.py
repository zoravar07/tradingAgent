import datetime as dt

import pytest

from core.schedule import InvalidCronExpression, is_due, next_run_after

# §9's actual config.yaml value: after US close, weeknights
NIGHTLY_CRON = "0 22 * * 0-4"


class TestNextRunAfter:
    def test_next_fire_same_day_before_scheduled_hour(self):
        after = dt.datetime(2026, 8, 25, 10, 0, 0)  # Tuesday 10am
        result = next_run_after(NIGHTLY_CRON, after)
        assert result == dt.datetime(2026, 8, 25, 22, 0, 0)

    def test_next_fire_rolls_to_next_weekday_after_scheduled_hour(self):
        after = dt.datetime(2026, 8, 25, 23, 0, 0)  # Tuesday 11pm, already past today's run
        result = next_run_after(NIGHTLY_CRON, after)
        assert result == dt.datetime(2026, 8, 26, 22, 0, 0)  # Wednesday

    def test_skips_weekend(self):
        # Friday 23:00 -> next run is Sunday 22:00 (cron days 0-4 = Sun-Thu nights,
        # i.e. the night before each weekday market open — Fri/Sat nights excluded)
        after = dt.datetime(2026, 8, 28, 23, 0, 0)  # Friday
        result = next_run_after(NIGHTLY_CRON, after)
        assert result == dt.datetime(2026, 8, 30, 22, 0, 0)
        assert result.weekday() == 6  # Sunday

    def test_invalid_cron_raises(self):
        with pytest.raises(InvalidCronExpression):
            next_run_after("not a cron expression", dt.datetime(2026, 8, 25))

    def test_simple_every_minute(self):
        after = dt.datetime(2026, 8, 25, 10, 0, 30)
        result = next_run_after("* * * * *", after)
        assert result == dt.datetime(2026, 8, 25, 10, 1, 0)


class TestIsDue:
    def test_never_run_is_always_due(self):
        assert is_due(NIGHTLY_CRON, last_run_at=None, now=dt.datetime(2026, 8, 25, 6, 0)) is True

    def test_not_due_before_next_scheduled_fire(self):
        last_run = dt.datetime(2026, 8, 25, 22, 0, 0)
        now = dt.datetime(2026, 8, 26, 6, 0, 0)  # next morning, before tonight's run
        assert is_due(NIGHTLY_CRON, last_run_at=last_run, now=now) is False

    def test_due_after_next_scheduled_fire(self):
        last_run = dt.datetime(2026, 8, 25, 22, 0, 0)
        now = dt.datetime(2026, 8, 26, 23, 0, 0)  # past the next night's 22:00 run
        assert is_due(NIGHTLY_CRON, last_run_at=last_run, now=now) is True
