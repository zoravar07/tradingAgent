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
    """One open position. Z Money's own book — the source of truth, reconciled
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
    # Assigned once at position-open time (core/portfolio.py's three
    # Position(...) construction sites) via core.sleeves.resolve_sleeve.
    # Never drifts afterward except through PortfolioService.reclassify_sleeve
    # (Part 4's SPECULATIVE-crosses-15%-NAV rule) — editing config.yaml's
    # ticker lists after the fact does NOT retroactively move a stored
    # position; core.sleeves.find_sleeve_drift is the startup check that
    # surfaces (never auto-fixes) that mismatch.
    sleeve: Mapped[str] = mapped_column(String, nullable=False, default="SWING")


class PositionImport(Base):
    """One Flex Query CSV import event, with a record of what reconciliation did."""

    __tablename__ = "position_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Added alongside core/nav.py: the account's cash balance as of this
    # import, read from the Flex Query CSV's CASH rows. Nullable because
    # older imports (before this column existed) and manual-only books
    # won't have one. Always USD — parse_flex_cash_balance filters to
    # CurrencyPrimary=="USD" before summing (see core/portfolio.py's
    # "base-currency trap" note and core/money.py), so no separate currency
    # column is needed here; the app-level type is core.money.Money, this
    # column is its .amount.
    cash_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


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
    # Informational only (core.sleeves.speculative_look_reasons) — set when
    # a new BUY defaulted to SWING but has characteristics (small market
    # cap, negative FCF, no earnings) that look SPECULATIVE. Never blocks
    # the BUY. NULL for every proposal type except a fresh SWING new-BUY,
    # and for every proposal recorded before this column existed.
    speculative_warning_json: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class SleeveBreachState(Base):
    """One row per sleeve, updated once per run — core.sleeves.update_breach_streak's
    persisted state. `direction`/`streak_days` mirror SleeveBreachStatus;
    `last_run_id` is audit trail, not used by the streak logic itself."""

    __tablename__ = "sleeve_breach_state"

    sleeve: Mapped[str] = mapped_column(String, primary_key=True)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)  # 'OVER' | 'UNDER' | NULL
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)


class ConfigVersion(Base):
    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class NavSnapshot(Base):
    """Not in §6's original schema — added for the drawdown/daily-loss
    tracking the user asked for on top of the spec: "drawdown history builds
    up from run to run — start it at zero on first run." One row per run;
    `peak_nav_usd` and `drawdown_pct` are derived by comparing against the
    single prior row, same never-recompute-from-scratch pattern as
    positions.peak_price_since_activation (§6).

    NAV/cash figures are USD by construction (core/nav.py's compute_nav only
    accepts core.money.Money — see that module's docstring for the real bug
    this guards against: a broker dashboard showing figures in the account's
    base currency, not the trading currency). These *_usd columns are each
    Money's .amount; the app-level values are always tagged Money, this is
    just their storage representation."""

    __tablename__ = "nav_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    nav_usd: Mapped[float] = mapped_column(Float, nullable=False)
    peak_nav_usd: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    daily_loss_pct: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)


class BriefingRecord(Base):
    """Not in §6's original schema — a gap step 9 left for step 10 (§10 UI
    design, 2026-08-26): `run_nightly` builds a `Briefing` object in memory
    and returns it, but nothing persisted the *assembled* result — only the
    underlying facts (Proposal/Candidate/Conviction/NavSnapshot rows).
    Reconstructing an accurate BookEntry (weight %, P&L) from those alone
    isn't reliable — the live price used that night isn't stored anywhere
    else. One row per run, storing core.briefing.Briefing serialized as JSON
    (core/briefing_persistence.py) — the exact record of what the briefing
    said, not a re-derivation of it later."""

    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, unique=True)
    briefing_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)


class JournalEntry(Base):
    """Freeform notes tied to a date and, optionally, a ticker (§10 UI,
    Journal screen). Deliberately the simplest table in the schema: the
    point is a place to write down why you did something, in your own
    words, next to the run that prompted it — not another structured
    record the pipeline has to keep in sync.

    `date` is the day the note is *about* (which is usually, but not
    always, the day it was written), so a note can be filed against the
    run it belongs to. `linked_ticker` is nullable because plenty of
    notes are about the book as a whole, not one name.
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    linked_ticker: Mapped[str | None] = mapped_column(String, index=True, nullable=True)


class AccountValue(Base):
    """One broker-reported portfolio value per calendar day, from the Flex
    Web Service's Net Asset Value / Equity Summary section, written by the
    position sync (sources/ibkr_flex.py). `nav_base` is in the account's
    base currency (SGD here); `nav_usd` is that figure divided by the
    USD->base fx rate the same report carries. This is the account's actual
    value, as opposed to nav_snapshots, which is the pipeline's own
    positions-times-price estimate at run time."""

    __tablename__ = "account_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # YYYY-MM-DD
    nav_base: Mapped[float] = mapped_column(Float, nullable=False)
    base_currency: Mapped[str] = mapped_column(String, nullable=False)
    fx_rate_to_base: Mapped[float] = mapped_column(Float, nullable=False)  # base units per 1 USD
    nav_usd: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
