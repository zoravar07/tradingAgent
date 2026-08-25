import time

import pytest

from core.cache import BudgetExceeded, DailyCallBudget, FileCache


class TestFileCache:
    def test_miss_then_hit(self, tmp_path):
        cache = FileCache(tmp_path)
        calls = []

        def fetch():
            calls.append(1)
            return {"x": 1}

        value1, hit1 = cache.get_or_fetch("k", ttl_seconds=100, fetch_fn=fetch)
        value2, hit2 = cache.get_or_fetch("k", ttl_seconds=100, fetch_fn=fetch)

        assert value1 == value2 == {"x": 1}
        assert hit1 is False
        assert hit2 is True
        assert len(calls) == 1  # fetch_fn only ran once

    def test_expired_entry_refetches(self, tmp_path):
        cache = FileCache(tmp_path)
        cache.set("k", "old", ttl_seconds=1)
        time.sleep(1.05)
        assert cache.get("k") is None

    def test_different_keys_dont_collide(self, tmp_path):
        cache = FileCache(tmp_path)
        cache.set("a", 1, ttl_seconds=100)
        cache.set("b", 2, ttl_seconds=100)
        assert cache.get("a") == 1
        assert cache.get("b") == 2


class TestDailyCallBudget:
    def test_increments_and_tracks_usage(self, tmp_path):
        budget = DailyCallBudget(tmp_path / "budget.json", daily_limit=3, today_fn=lambda: "2026-08-25")
        budget.check_and_increment()
        budget.check_and_increment()
        assert budget.used_today() == 2
        assert budget.remaining_today() == 1

    def test_raises_when_exceeded(self, tmp_path):
        budget = DailyCallBudget(tmp_path / "budget.json", daily_limit=2, today_fn=lambda: "2026-08-25")
        budget.check_and_increment()
        budget.check_and_increment()
        with pytest.raises(BudgetExceeded):
            budget.check_and_increment()

    def test_resets_on_new_day(self, tmp_path):
        day = {"value": "2026-08-25"}
        budget = DailyCallBudget(tmp_path / "budget.json", daily_limit=1, today_fn=lambda: day["value"])
        budget.check_and_increment()
        with pytest.raises(BudgetExceeded):
            budget.check_and_increment()
        day["value"] = "2026-08-26"
        budget.check_and_increment()  # doesn't raise — new day, fresh quota
        assert budget.used_today() == 1

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "budget.json"
        DailyCallBudget(path, daily_limit=5, today_fn=lambda: "2026-08-25").check_and_increment()
        second = DailyCallBudget(path, daily_limit=5, today_fn=lambda: "2026-08-25")
        assert second.used_today() == 1
