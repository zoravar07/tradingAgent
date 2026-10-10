"""Journal — freeform notes tied to a date and, optionally, a ticker.

The one write surface in the app that isn't config. Deliberately thin: list,
create, delete. There is no edit endpoint because a trading journal you can
quietly rewrite after the fact is worth less than one you can't — if a note
turns out wrong, the useful record is the wrong note plus a later one saying
so, not a tidied version that hides what you actually thought at the time.

See core/models.py's JournalEntry for the table itself.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import JournalEntry

router = APIRouter()

MAX_CONTENT_CHARS = 10_000


def get_session(request: Request) -> Session:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


class JournalCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    # Defaults to today on the server so a note written with the date field
    # left alone is filed against the day it was actually written.
    date: dt.date | None = None
    linked_ticker: str | None = Field(default=None, max_length=12)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("A note needs some text.")
        return stripped

    @field_validator("linked_ticker")
    @classmethod
    def normalise_ticker(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip().upper()
        return cleaned or None


def _serialize(e: JournalEntry) -> dict:
    return {
        "id": e.id,
        "date": e.date.isoformat(),
        "content": e.content,
        "linked_ticker": e.linked_ticker,
    }


@router.get("/journal")
def list_entries(session: Session = Depends(get_session)) -> dict:
    stmt = select(JournalEntry).order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
    entries = session.execute(stmt).scalars().all()
    return {"entries": [_serialize(e) for e in entries]}


@router.post("/journal")
def create_entry(body: JournalCreate, session: Session = Depends(get_session)) -> dict:
    day = body.date or dt.date.today()
    entry = JournalEntry(
        # Stored as a datetime at midnight: the column is a DateTime (every
        # other timestamp in the schema is), and the note is about a day, not
        # a moment.
        date=dt.datetime.combine(day, dt.time.min),
        content=body.content,
        linked_ticker=body.linked_ticker,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return _serialize(entry)


@router.delete("/journal/{entry_id}")
def delete_entry(entry_id: int, session: Session = Depends(get_session)) -> dict:
    entry = session.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No journal entry with that id.")
    session.delete(entry)
    session.commit()
    return {"deleted": entry_id}
