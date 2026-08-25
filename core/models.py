"""SQLAlchemy models. Only the `positions` and `position_imports` tables from
the §6 schema are defined here (what the portfolio module owns). The rest of
§6 (runs, candidates, research_outputs, conviction, proposals, watchlist_items,
risk_events, config_versions) gets added as their owning modules are built —
add them to this file rather than starting a second models module.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
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
