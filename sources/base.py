"""FactorSource plugin interface — §8.2.

    class FactorSource(ABC):
        name: str
        @abstractmethod
        def fetch(self, ticker: str, ctx: RunContext) -> FactorData: ...

Adding a source is one new file implementing this ABC plus one config line
(§8.2) — no changes to research, scoring, or risk. `FactorData.fields` is
deliberately an untyped dict rather than a per-source schema: scoring (§8.3)
iterates whatever weights are configured and never hardcodes factor names, so
a source's payload shape is a contract between that source and whichever
config-declared weight consumes it, not something the plugin layer enforces.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunContext:
    """Shared context passed to every source's fetch() for one pipeline run."""

    run_id: int
    as_of: dt.datetime
    config: dict = field(default_factory=dict)


@dataclass
class FactorData:
    """One source's contribution for one ticker.

    `error` is set instead of raising so one misbehaving source (an API
    outage, a bad ticker, a rate limit) can't take down a whole run — the
    screener/scoring layer decides how to treat a partial or errored fetch,
    not the source itself.
    """

    source: str
    ticker: str
    fetched_at: dt.datetime
    fields: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class FactorSource(ABC):
    name: str

    @abstractmethod
    def fetch(self, ticker: str, ctx: RunContext) -> FactorData: ...
