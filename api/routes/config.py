"""Settings screen backend — GET /api/config (current values, full raw
text for "View current"), POST /api/config/update (validated write),
POST /api/config/reset (editable fields back to Pydantic defaults). See
core/config_writer.py's docstring for what "editable" means here and why
writes go through ruamel instead of core/config.py's PyYAML loader.

Validation is two-layered: the request body model below enforces sane
ranges (percentages in [0, 100], positive dollar amounts, a parseable cron
string, cheap-PE < expensive-PE) independent of core/config.py's shared
domain models — a bad Settings submission can't affect what the orchestrator
imports. After that passes, the merged whole-file result is re-validated
through the real `Config` model before anything touches disk, as a final
consistency check.

`config_path` is threaded through from `app.state` (set by
`api.server.create_app`), the same pattern as the briefing routes' session
factory — tests point it at a temp file, never the real config.yaml.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Config
from core.config_writer import apply_updates, default_values, dump_to_string, editable_snapshot, read_raw, write_raw
from core.models import ConfigVersion
from core.schedule import InvalidCronExpression, next_run_after

router = APIRouter()


def get_session(request: Request) -> Session:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_config_path(request: Request) -> Path:
    return request.app.state.config_path


class PortfolioUpdate(BaseModel):
    allow_fractional: bool


class RiskUpdate(BaseModel):
    max_position_pct: float = Field(gt=0, le=100)
    max_sector_pct: float = Field(gt=0, le=100)
    max_correlated_cluster_pct: float = Field(gt=0, le=100)
    max_daily_proposals: int = Field(ge=0, le=50)
    max_daily_loss_pct: float = Field(gt=0, le=100)
    max_drawdown_pct: float = Field(gt=0, le=100)
    min_order_value_usd: float = Field(ge=0)
    min_hold_conviction: float = Field(ge=0, le=100)
    max_unpriced_held_positions: int = Field(ge=0)


class Stage1Update(BaseModel):
    min_avg_daily_volume_usd: float = Field(ge=0)
    min_market_cap_usd: float = Field(ge=0)
    max_survivors: int = Field(ge=1, le=500)
    min_revenue_growth_pct: float
    valuation_pe_cheap_max: float = Field(gt=0)
    valuation_pe_expensive_min: float = Field(gt=0)
    earnings_proximity_days: int = Field(ge=0, le=90)

    @model_validator(mode="after")
    def cheap_below_expensive(self) -> "Stage1Update":
        if self.valuation_pe_cheap_max >= self.valuation_pe_expensive_min:
            raise ValueError(
                f"valuation_pe_cheap_max ({self.valuation_pe_cheap_max}) must be less than "
                f"valuation_pe_expensive_min ({self.valuation_pe_expensive_min})"
            )
        return self


class ScreenerUpdate(BaseModel):
    stage1: Stage1Update


class BudgetUpdate(BaseModel):
    monthly_api_cap_usd: float = Field(gt=0)


class ScheduleUpdate(BaseModel):
    nightly_run: str

    @model_validator(mode="after")
    def valid_cron(self) -> "ScheduleUpdate":
        try:
            next_run_after(self.nightly_run, dt.datetime(2026, 1, 1))
        except InvalidCronExpression as exc:
            raise ValueError(str(exc)) from exc
        return self


class ConfigUpdateRequest(BaseModel):
    portfolio: PortfolioUpdate
    risk: RiskUpdate
    screener: ScreenerUpdate
    budget: BudgetUpdate
    schedule: ScheduleUpdate


def _snapshot(session: Session, raw) -> None:
    last = session.execute(select(ConfigVersion).order_by(ConfigVersion.version.desc()).limit(1)).scalar_one_or_none()
    next_version = (last.version + 1) if last is not None else 1
    session.add(ConfigVersion(version=next_version, yaml_text=dump_to_string(raw), created_at=dt.datetime.utcnow()))


def _write_and_validate(session: Session, config_path: Path, raw) -> Config:
    """Re-validates the merged file through the real Config model before
    anything touches disk. Snapshots the pre-write state to config_versions
    so a bad edit (that still passed per-field validation, e.g. a
    cross-section inconsistency) is recoverable."""
    try:
        validated = Config.model_validate(dict(raw))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc

    _snapshot(session, read_raw(config_path))
    write_raw(config_path, raw)
    session.commit()
    return validated


def _current(config_path: Path) -> dict:
    raw = read_raw(config_path)
    return {
        "editable": editable_snapshot(raw),
        "defaults": default_values(),
        "yaml_text": dump_to_string(raw),
    }


@router.get("/config")
def get_config(config_path: Path = Depends(get_config_path)) -> dict:
    return _current(config_path)


@router.post("/config/update")
def update_config(
    body: ConfigUpdateRequest,
    session: Session = Depends(get_session),
    config_path: Path = Depends(get_config_path),
) -> dict:
    raw = read_raw(config_path)
    apply_updates(raw, body.model_dump())
    _write_and_validate(session, config_path, raw)
    return _current(config_path)


@router.post("/config/reset")
def reset_config(
    session: Session = Depends(get_session),
    config_path: Path = Depends(get_config_path),
) -> dict:
    raw = read_raw(config_path)
    apply_updates(raw, default_values())
    _write_and_validate(session, config_path, raw)
    return _current(config_path)
