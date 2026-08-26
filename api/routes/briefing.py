"""GET /api/briefing/latest — the only route this pass needs (§10 step 10:
Briefing screen first, per the other chat's advice already in the project's
history). Reads the most recent BriefingRecord
(core/briefing_persistence.py) and returns it essentially as-is; no
transformation — the persisted JSON already matches what the frontend
renders, by design (see that module's docstring).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.briefing_persistence import deserialize_briefing
from core.models import BriefingRecord, Run

router = APIRouter()


def get_session(request: Request) -> Session:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@router.get("/briefing/latest")
def get_latest_briefing(session: Session = Depends(get_session)) -> dict:
    stmt = select(BriefingRecord).order_by(BriefingRecord.created_at.desc()).limit(1)
    record = session.execute(stmt).scalar_one_or_none()
    if record is None:
        return {"status": "no_runs_yet"}

    run = session.get(Run, record.run_id)
    return {
        "status": "ok",
        "run_id": record.run_id,
        "run_status": run.status if run is not None else None,
        "generated_at": run.finished_at.isoformat() if run and run.finished_at else None,
        "briefing": deserialize_briefing(record.briefing_json),
    }
