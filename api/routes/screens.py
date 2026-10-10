"""Read-only routes behind Watchlist, Positions, Orders, Insights and
Performance. Until this module existed those four screens rendered
`ui/src/lib/previewData.ts` — invented tickers with invented prices — while
only Briefing and Settings touched the database. Everything below reads the
real tables.

Two joins do the actual work, and both exist for the same reason: the raw
tables store what was *decided*, not what things were *worth* at the time.

- **Positions** carries qty / avg_cost / opened_at, but no price. The live
  price used on a given night is only ever recorded inside that night's
  serialized briefing (see core/models.py's BriefingRecord docstring — this
  is exactly the gap it was added to close). So a Position row is joined to
  its BookEntry from the latest briefing to get value, weight, P&L and
  current conviction. A holding with no matching BookEntry is returned with
  those fields null rather than dropped or back-filled with a guess.

- **Insights** joins ResearchOutput to Conviction on (run_id, ticker),
  because the write-up and the score it produced are separate rows from the
  same pipeline stage. Grouping by ticker across runs is what turns a pile of
  memos into a trend — the arc a thesis traces run over run is the whole
  point of the screen.

Nothing here computes a number the pipeline didn't already compute. Where a
figure genuinely isn't in the database (a position with no coverage, a
portfolio with one NAV point), the response says so and the UI says so too.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import (
    AccountValue,
    Conviction,
    NavSnapshot,
    Position,
    Proposal,
    ResearchOutput,
    RiskEvent,
    Run,
    WatchlistItem,
)
from core.models import BriefingRecord

router = APIRouter()


def get_session(request: Request) -> Session:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def _latest_briefing(session: Session) -> dict[str, Any] | None:
    stmt = select(BriefingRecord).order_by(BriefingRecord.created_at.desc()).limit(1)
    record = session.execute(stmt).scalar_one_or_none()
    if record is None:
        return None
    return json.loads(record.briefing_json)


def _book_by_ticker(session: Session) -> dict[str, dict[str, Any]]:
    """The latest briefing's BookEntry rows, keyed by ticker. Empty when no
    run has produced a briefing yet — callers must treat every field it
    would have supplied as unknown, not as zero."""
    briefing = _latest_briefing(session)
    if briefing is None:
        return {}
    return {entry["ticker"]: entry for entry in briefing.get("book", [])}


# --------------------------------------------------------------------------
# Positions
# --------------------------------------------------------------------------


@router.get("/positions")
def get_positions(session: Session = Depends(get_session)) -> dict:
    book = _book_by_ticker(session)
    rows = session.execute(select(Position).order_by(Position.ticker)).scalars().all()

    positions = []
    for p in rows:
        entry = book.get(p.ticker)
        # value_usd / qty is the price the briefing actually priced this
        # holding at. Deriving it back out beats storing a second copy that
        # could drift from the one the briefing reported.
        last_price = (entry["value_usd"] / p.qty) if entry and p.qty else None
        positions.append(
            {
                "ticker": p.ticker,
                "qty": p.qty,
                "avg_cost": p.avg_cost,
                "opened_at": p.opened_at.isoformat(),
                "source": p.source,
                "last_verified_at": p.last_verified_at.isoformat() if p.last_verified_at else None,
                "conviction_at_entry": p.conviction_at_entry,
                "peak_price_since_activation": p.peak_price_since_activation,
                # From the latest briefing — null when this holding wasn't in it.
                "value_usd": entry["value_usd"] if entry else None,
                "weight_pct": entry["weight_pct"] if entry else None,
                "unrealized_pnl_pct": entry["unrealized_pnl_pct"] if entry else None,
                "conviction_now": entry["conviction_now"] if entry else None,
                "last_price": last_price,
                "distance_to_trailing_stop_pct": (
                    entry["distance_to_trailing_stop_pct"] if entry else None
                ),
                "next_profit_band_pct": entry["next_profit_band_pct"] if entry else None,
                "has_exit_trigger": entry["has_exit_trigger"] if entry else False,
                "no_research_coverage": entry["no_research_coverage"] if entry else True,
            }
        )

    briefing = _latest_briefing(session)
    return {
        "positions": positions,
        "cash_pct": (briefing or {}).get("portfolio_health", {}).get("cash_pct"),
        "priced_at": (briefing or {}).get("generated_at"),
    }


# --------------------------------------------------------------------------
# Watchlist
# --------------------------------------------------------------------------


@router.get("/watchlist")
def get_watchlist(session: Session = Depends(get_session)) -> dict:
    """Names near a trigger but not yet actionable. The persisted
    WatchlistItem rows are the record; the latest briefing's `watching` list
    is the same data as of the last run. Rows are preferred when present so
    the screen still works for runs whose briefing predates the table."""
    latest_run = session.execute(select(Run).order_by(Run.started_at.desc()).limit(1)).scalar_one_or_none()

    items: list[dict[str, Any]] = []
    if latest_run is not None:
        rows = (
            session.execute(select(WatchlistItem).where(WatchlistItem.run_id == latest_run.id))
            .scalars()
            .all()
        )
        items = [
            {
                "ticker": w.ticker,
                "reason": w.reason,
                "distance_to_trigger_pct": w.distance_to_trigger,
            }
            for w in rows
        ]

    briefing = _latest_briefing(session)
    if not items and briefing is not None:
        items = list(briefing.get("watching", []))

    # Conviction gives each watched name a magnitude to sort and read by; it
    # comes from the same run, so it is the score that put the name on watch.
    if latest_run is not None and items:
        scores = {
            c.ticker: c.score
            for c in session.execute(
                select(Conviction).where(Conviction.run_id == latest_run.id)
            ).scalars()
        }
        for item in items:
            item["conviction"] = scores.get(item["ticker"])

    return {
        "items": items,
        "run_id": latest_run.id if latest_run else None,
        "generated_at": (briefing or {}).get("generated_at"),
    }


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------


@router.get("/orders")
def get_orders(session: Session = Depends(get_session)) -> dict:
    """Every proposal ever made, newest first, plus a per-run note of what
    else happened that night — a run that proposed nothing, or one that
    logged risk events, is part of the record too, and a timeline that only
    showed fills would quietly hide it."""
    runs = {r.id: r for r in session.execute(select(Run)).scalars()}

    proposals = (
        session.execute(select(Proposal).order_by(Proposal.created_at.desc(), Proposal.id.desc()))
        .scalars()
        .all()
    )

    orders = [
        {
            "id": p.id,
            "run_id": p.run_id,
            "ticker": p.ticker,
            "action": p.action,
            "quantity": p.quantity,
            "order_type": p.order_type,
            "limit_price": p.limit_price,
            "est_cost": p.est_cost,
            "conviction": p.conviction,
            "rationale": p.rationale,
            "trigger_type": p.trigger_type,
            "status": p.status,
            "created_at": p.created_at.isoformat(),
            "filled_at": p.filled_at.isoformat() if p.filled_at else None,
            "fill_price": p.fill_price,
        }
        for p in proposals
    ]

    # Risk events are collapsed to one line per (run, type). Run 1 alone
    # logged 22 DATA_FETCH_FAILED rows; listing them individually would bury
    # the proposals they sit beside without telling you anything the count
    # doesn't.
    event_counts: dict[tuple[int, str], int] = defaultdict(int)
    for e in session.execute(select(RiskEvent)).scalars():
        event_counts[(e.run_id, e.type)] += 1

    proposals_per_run: dict[int, int] = defaultdict(int)
    for p in proposals:
        proposals_per_run[p.run_id] += 1

    run_events = []
    for run in sorted(runs.values(), key=lambda r: r.started_at, reverse=True):
        events = [
            {"type": etype, "count": count}
            for (rid, etype), count in event_counts.items()
            if rid == run.id
        ]
        run_events.append(
            {
                "run_id": run.id,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "error": run.error,
                "proposal_count": proposals_per_run.get(run.id, 0),
                "risk_events": sorted(events, key=lambda e: -e["count"]),
            }
        )

    return {"orders": orders, "runs": run_events}


# --------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------


def _trend(scores: list[float]) -> str:
    """scores are newest-first. Two runs is enough to call a direction; one
    isn't, and saying "steady" off a single data point would be a claim the
    data doesn't support."""
    if len(scores) < 2:
        return "new"
    delta = scores[0] - scores[1]
    if delta > 2:
        return "strengthening"
    if delta < -2:
        return "decaying"
    return "steady"


@router.get("/insights")
def get_insights(session: Session = Depends(get_session)) -> dict:
    runs = {r.id: r for r in session.execute(select(Run)).scalars()}
    conviction_by_key = {
        (c.run_id, c.ticker): c
        for c in session.execute(select(Conviction)).scalars()
    }

    memos_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in session.execute(select(ResearchOutput).order_by(ResearchOutput.id.desc())).scalars():
        run = runs.get(r.run_id)
        conviction = conviction_by_key.get((r.run_id, r.ticker))
        bear = json.loads(r.bear_case_json)
        memos_by_ticker[r.ticker].append(
            {
                "run_id": r.run_id,
                "dated_at": (run.started_at.isoformat() if run else None),
                "conviction": conviction.score if conviction else None,
                "subscores": json.loads(r.subscores_json),
                "derivation": json.loads(conviction.derivation_json) if conviction else None,
                "consensus_view": r.consensus_view,
                "variant_view": r.variant_view,
                "thesis_summary": r.thesis_summary,
                "bear_case": bear.get("thesis"),
                "estimated_downside_pct": bear.get("estimated_downside_pct"),
                "catalysts": json.loads(r.catalysts_json),
                "risks": json.loads(r.risks_json),
                "unavailable_factors": json.loads(r.reasoning_json).get("unavailable_factors", []),
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
            }
        )

    tickers = []
    for ticker, memos in memos_by_ticker.items():
        # Newest run first. ResearchOutput ids are monotonic per run, so the
        # id-desc ordering above already gives this, but sorting on run_id
        # makes the intent explicit rather than incidental.
        memos.sort(key=lambda m: m["run_id"], reverse=True)
        scores = [m["conviction"] for m in memos if m["conviction"] is not None]
        tickers.append(
            {
                "ticker": ticker,
                "trend": _trend(scores),
                "conviction_now": scores[0] if scores else None,
                "conviction_delta": (scores[0] - scores[1]) if len(scores) > 1 else None,
                "memos": memos,
            }
        )

    tickers.sort(key=lambda t: (t["conviction_now"] is None, -(t["conviction_now"] or 0)))
    return {"tickers": tickers}


# --------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------


def nav_series(session: Session) -> tuple[list[dict], str]:
    """The portfolio-value series and where it comes from: the broker's own
    daily account value when the Flex NAV section has been synced (source
    "ibkr"), else the pipeline's per-run estimate (source "runs")."""
    values = session.execute(select(AccountValue).order_by(AccountValue.report_date)).scalars().all()
    if values:
        series = [
            {
                "run_id": None, "recorded_at": f"{v.report_date}T00:00:00", "nav_usd": v.nav_usd,
                "nav_base": v.nav_base, "base_currency": v.base_currency, "peak_nav_usd": None, "drawdown_pct": None, "daily_loss_pct": None,
            }
            for v in values
        ]
        peak = 0.0
        for point in series:
            peak = max(peak, point["nav_usd"])
            point["peak_nav_usd"] = peak
            point["drawdown_pct"] = (peak - point["nav_usd"]) / peak * 100 if peak else 0.0
        return series, "ibkr"
    snapshots = session.execute(select(NavSnapshot).order_by(NavSnapshot.recorded_at)).scalars().all()
    return [
        {
            "run_id": s.run_id, "recorded_at": s.recorded_at.isoformat(), "nav_usd": s.nav_usd, "nav_base": None, "base_currency": None,
            "peak_nav_usd": s.peak_nav_usd, "drawdown_pct": s.drawdown_pct, "daily_loss_pct": s.daily_loss_pct,
        }
        for s in snapshots
    ], "runs"


@router.get("/performance")
def get_performance(session: Session = Depends(get_session)) -> dict:
    """Portfolio value over time. From the broker's daily Net Asset Value
    once the Flex sync carries it (one reading per calendar day, the
    account's real value), otherwise from nav_snapshots (one per run, the
    pipeline's own estimate). `source` says which, so the UI can say so."""
    series, source = nav_series(session)

    first = series[0] if series else None
    last = series[-1] if series else None
    change_pct = (
        ((last["nav_usd"] - first["nav_usd"]) / first["nav_usd"] * 100)
        if first and last and first["nav_usd"]
        else None
    )

    return {
        "series": series,
        "source": source,
        "point_count": len(series),
        "has_history": len(series) >= 2,
        "current_nav_usd": last["nav_usd"] if last else None,
        "peak_nav_usd": last["peak_nav_usd"] if last else None,
        "drawdown_pct": last["drawdown_pct"] if last else None,
        "change_since_first_pct": change_pct,
    }
