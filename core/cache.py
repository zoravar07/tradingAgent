"""Aggressive on-disk cache for external API calls — §10 step 3: "cache hard;
free tier is 250 calls/day". Keyed by an explicit string key the caller builds
(endpoint + params), so callers control cache granularity and can reason about
what a given key covers. Deliberately simple: one JSON file per key, no
eviction policy, no external dependency — this is a single-laptop app hitting
a low-volume API, not a distributed cache.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class CacheEntry:
    key: str
    stored_at: float
    ttl_seconds: float
    value: Any

    def is_fresh(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.stored_at) < self.ttl_seconds


class FileCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str, now: float | None = None) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        entry = CacheEntry(**raw)
        if not entry.is_fresh(now):
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        payload = CacheEntry(key=key, stored_at=time.time(), ttl_seconds=ttl_seconds, value=value)
        self._path(key).write_text(json.dumps(payload.__dict__))

    def get_or_fetch(
        self, key: str, ttl_seconds: float, fetch_fn: Callable[[], Any]
    ) -> tuple[Any, bool]:
        """Returns (value, was_cache_hit)."""
        cached = self.get(key)
        if cached is not None:
            return cached, True
        value = fetch_fn()
        self.set(key, value, ttl_seconds)
        return value, False


class BudgetExceeded(RuntimeError):
    pass


class DailyCallBudget:
    """Guards against blowing through FMP's 250-calls/day free tier. Only
    counts actual network calls — the caller increments this on a cache miss,
    never on a hit. Persisted to a small JSON file so the count survives
    across separate process runs within the same UTC day."""

    def __init__(self, path: str | Path, daily_limit: int, today_fn: Callable[[], str] | None = None):
        self.path = Path(path)
        self.daily_limit = daily_limit
        self._today_fn = today_fn or (lambda: time.strftime("%Y-%m-%d", time.gmtime()))

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))

    def used_today(self) -> int:
        return self._read().get(self._today_fn(), 0)

    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.used_today())

    def check_and_increment(self, n: int = 1) -> None:
        today = self._today_fn()
        data = self._read()
        used = data.get(today, 0)
        if used + n > self.daily_limit:
            raise BudgetExceeded(
                f"FMP daily call budget exceeded: {used}/{self.daily_limit} used, "
                f"{n} more requested"
            )
        data[today] = used + n
        # Keep the file from growing forever — one day of history is enough context.
        self._write({today: data[today]})
