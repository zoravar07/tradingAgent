"""SQLAlchemy models for the full §6 schema. `Position`/`PositionImport` are
the portfolio module's (step 2); everything below them is the orchestrator's
(step 9) — one row per pipeline stage per run, so a run is fully replayable
from the database afterward.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Position(Base):
    """One open position. Zopro's own book — the source of truth, reconciled
    against Flex Query imports but not blindly replaced by them (§2)."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, index=True, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'import' | 'manual' | 'fill'
    last_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    conviction_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_price_since_activation: Mapped[float | None] = mapped_column(Float, nullable=True)


class PositionImport(Base):
    """One Flex Query CSV import event, with a record of what reconciliation did."""

    __tablename__ = "position_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_json: Mapped[str] = mapped_column(Text, nullable=False)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # 'running' | 'succeeded' | 'failed'
    config_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String, index=True, nullable=False)
    stage1_json: Mapped[str] = mapped_column(Text, nullable=False)
    stage1_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stage2_verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage2_material: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stage2_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ResearchOutput(Base):
    __tablename__ = "research_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String, index=True, nullable=False)
    subscores_json: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning_json: Mapped[str] = mapped_column(Text, nullable=False)
    consensus_view: Mapped[str] = mapped_column(Text, nullable=False)
    variant_view: Mapped[str] = mapped_column(Text, nullable=False)
    bear_case_json: Mapped[str] = mapped_column(Text, nullable=False)
    catalysts_json: Mapped[str] = mapped_column(Text, nullable=False)
    risks_json: Mapped[str] = mapped_column(Text, nullable=False)
    thesis_summary: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Conviction(Base):
    __tablename__ = "conviction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String, index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    weights_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    derivation_json: Mapped[str] = mapped_column(Text, nullable=False)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # 'BUY' | 'SELL'
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String, nullable=False)
    limit_price: Mapped[float] = mapped_column(Float, nullable=False)
    est_cost: Mapped[float] = mapped_column(Float, nullable=False)
    conviction: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    risk_checks_json: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")  # 'proposed'|'filled'|'dismissed'
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    filled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String, index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    distance_to_trigger: Mapped[float | None] = mapped_column(Float, nullable=True)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False)


class ConfigVersion(Base):
    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
