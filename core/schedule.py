"""Scheduling — the "schedule" part of §10 step 9's "wire, schedule, log
everything." §9's config.yaml: `schedule.nightly_run: "0 22 * * 0-4"`.

This module answers "when should the next run fire" from a cron string —
pure, testable logic. It deliberately does NOT run a daemon/event loop that
stays up and fires `orchestrator.run_nightly` on schedule — that's a
main.py concern (keep the process alive, handle signals, survive restarts),
and main.py isn't a numbered §10 step. Wire `next_run_after` into whatever
process-supervision approach main.py ends up using (APScheduler, a bare
while-loop with sleep-until, a system cron entry calling a CLI — any of
these can call this function to decide, or validate, the fire time).
"""

from __future__ import annotations

import datetime as dt

from croniter import CroniterError, croniter


class InvalidCronExpression(ValueError):
    pass


def next_run_after(cron_expression: str, after: dt.datetime) -> dt.datetime:
    try:
        it = croniter(cron_expression, after)
        return it.get_next(dt.datetime)
    except (CroniterError, ValueError) as exc:
        raise InvalidCronExpression(f"invalid cron expression {cron_expression!r}: {exc}") from exc


def is_due(cron_expression: str, last_run_at: dt.datetime | None, now: dt.datetime) -> bool:
    """True if a run scheduled for `cron_expression` should have fired by
    `now`, given the last run happened at `last_run_at` (None = never run)."""
    if last_run_at is None:
        return True
    return next_run_after(cron_expression, last_run_at) <= now
