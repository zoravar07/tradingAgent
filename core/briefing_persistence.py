"""Serializes core.briefing.Briefing to/from JSON for storage in the
`briefings` table (core/models.py's BriefingRecord) — §10 step 9/10 gap: the
UI needs to read back the exact briefing a run produced, not re-derive an
approximation of it from scattered rows later.

`Briefing` and everything it contains (ActionItem, BookEntry,
PortfolioHealth, OrderProposal, KillSwitchStatus, DriftStatus,
BlockedStatus, ...) are all plain dataclasses, so `dataclasses.asdict`
handles the recursion — the only thing it doesn't know how to do is
datetime, handled by a custom JSON encoder. Deserializing does NOT
reconstruct the dataclass tree; the API layer returns the plain dict
straight to the frontend, which has its own TypeScript types matching this
shape. Reconstructing real dataclasses would need one factory function per
nested type for no benefit this module's one consumer (a JSON HTTP
response) actually needs.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from typing import Any


def _json_default(obj: Any) -> Any:
    if isinstance(obj, dt.datetime):
        return obj.isoformat()
    raise TypeError(f"cannot serialize {type(obj).__name__} in a Briefing")


def serialize_briefing(briefing) -> str:
    return json.dumps(dataclasses.asdict(briefing), default=_json_default)


def deserialize_briefing(raw_json: str) -> dict:
    """Returns a plain dict matching Briefing's shape — see module
    docstring for why this isn't reconstructed back into dataclasses."""
    return json.loads(raw_json)
