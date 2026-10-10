"""Dashboard data behind the Briefing screen's multi-panel layout, and the
cached price bars behind its chart.

Everything here is read from what the pipeline already persisted (runs,
candidates, proposals, briefings, research outputs, the spend counters, the
yfinance history cache). Nothing is fetched live and nothing is estimated:
a tile the data can't support is omitted, not filled with a placeholder.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.cache import FileCache
from core.config import load_config
from core.models import BriefingRecord, Candidate, NavSnapshot, Position, Proposal, ResearchOutput, RiskEvent, Run
from api.routes.screens import nav_series
from core.risk_rules import lerp_by_conviction
from sources.prices import Bar, compute_technical_snapshot

router = APIRouter()

RANGES: dict[str, int] = {"1W": 7, "1M": 31, "3M": 93, "1Y": 366}  # calendar days of daily bars
SPARKLINE_RUNS = 12
MAX_SETUPS = 12


def get_session(request: Request) -> Session:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_data_dir(request: Request) -> Path:
    return request.app.state.data_dir


def get_config_path(request: Request) -> Path:
    return request.app.state.config_path


# ------------------------------------------------------------ helpers


def _cached_bars(data_dir: Path, ticker: str) -> tuple[list[Bar], str | None]:
    """The 2y daily bars the last run priced this name against, TTL ignored
    (this is display, not a refetch decision). Empty if never fetched."""
    cache = FileCache(data_dir / "yf_cache")
    hit = cache.peek(f"yf:hist:{ticker.upper()}:2y")
    if hit is None:
        return [], None
    rows, stored_at = hit
    bars = sorted((Bar(**r) for r in rows), key=lambda b: b.date)
    return bars, dt.datetime.utcfromtimestamp(stored_at).isoformat()


def _last_close_and_change(bars: list[Bar]) -> tuple[float | None, float | None]:
    if not bars:
        return None, None
    last = bars[-1].close
    if len(bars) < 2 or not bars[-2].close:
        return last, None
    return last, (last - bars[-2].close) / bars[-2].close * 100


ONE_LINE = 220

VALUATION_WORDS = {
    "cheap": "The share price is low compared with the company's profits.",
    "fair": "The share price is about in line with the company's profits.",
    "expensive": "The share price is high compared with the company's profits.",
}


def _technical_sentence(rank: float | None, valuation_band: str | None, exit_trigger: bool) -> str | None:
    """The Stage 1 numbers as a beginner would hear them: how the shares have
    done against the market recently, what the price says relative to
    profits, and whether a sell rule has fired."""
    parts: list[str] = []
    if rank is not None:
        if abs(rank) < 1:
            parts.append("Over the last three months the shares have moved about in line with the S&P 500.")
        elif rank > 0:
            parts.append(f"Over the last three months the shares have done {rank:.0f} percentage points better than the S&P 500.")
        else:
            parts.append(f"Over the last three months the shares have done {abs(rank):.0f} percentage points worse than the S&P 500.")
    if valuation_band in VALUATION_WORDS:
        parts.append(VALUATION_WORDS[valuation_band])
    if exit_trigger:
        parts.append("One of your sell rules has been triggered.")
    return " ".join(parts) or None


def _one_line(text: str | None, limit: int = ONE_LINE) -> str | None:
    """Collapse to a single line and trim — the panel shows one line per
    insight; the full memo is on the Insights screen."""
    if not text:
        return None
    flat = " ".join(text.replace("**", "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _first_news_line(digest: str) -> str:
    """The first substantive line of a digest: skips the model's preamble
    ("Here are..."), markdown rules and bare numbering."""
    lines = [raw.strip().strip("*-# ").strip() for raw in digest.splitlines()]
    lines = [l for l in lines if l and not all(ch in "-—_=*#" for ch in l)]
    # Prefer the first dated item; the model sometimes narrates its search first.
    for line in lines:
        if re.match(r"^\d{4}-\d{2}-\d{2}", line):
            return line
    narration = ("here are", "i'll ", "i will", "let me", "based on", "i have", "i found")
    for line in lines:
        if not line.lower().startswith(narration):
            return line
    return lines[0] if lines else digest.strip()


def _company_name(data_dir: Path, ticker: str) -> str | None:
    """The full company name from the cached FMP profile the pipeline
    already fetched — never a guess. None when no profile is cached."""
    hit = FileCache(data_dir / "cache").peek(f'fmp:profile:{{"symbol": "{ticker.upper()}"}}')
    if hit is None:
        return None
    value = hit[0]
    row = value[0] if isinstance(value, list) and value else (value if isinstance(value, dict) else None)
    name = (row or {}).get("companyName")
    return str(name).strip() or None if name else None


def _pnl(points: list[dict], source: str) -> dict:
    """Change in portfolio value against the latest reading at least 1, 7
    and 30 days older than the newest one. Each window is null until the
    history is long enough — never a number stretched over a shorter span.
    `points` are nav_series() rows (broker daily values when synced, else
    per-run estimates)."""
    parsed = [(dt.datetime.fromisoformat(p["recorded_at"]), p["nav_usd"]) for p in points]
    series = [{"at": at.isoformat(), "nav_usd": nav} for at, nav in parsed]
    if not parsed:
        return {"series": series, "source": source, "current_nav_usd": None, "daily": None, "weekly": None, "monthly": None}
    latest_at, latest_nav = parsed[-1]

    def window(days: int) -> dict | None:
        cutoff = latest_at - dt.timedelta(days=days)
        older = [(at, nav) for at, nav in parsed if at <= cutoff]
        if not older or not older[-1][1]:
            return None
        base_at, base_nav = older[-1]
        return {"usd": latest_nav - base_nav, "pct": (latest_nav - base_nav) / base_nav * 100, "since": base_at.isoformat()}

    return {"series": series, "source": source, "current_nav_usd": latest_nav, "daily": window(1), "weekly": window(7), "monthly": window(30)}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


def _briefing_for(session: Session, run_id: int) -> dict[str, Any] | None:
    rec = session.execute(select(BriefingRecord).where(BriefingRecord.run_id == run_id)).scalar_one_or_none()
    return json.loads(rec.briefing_json) if rec else None


# ------------------------------------------------------------ dashboard


@router.get("/dashboard")
def get_dashboard(
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    config_path: Path = Depends(get_config_path),
) -> dict:
    runs = session.execute(select(Run).order_by(Run.started_at.desc()).limit(SPARKLINE_RUNS)).scalars().all()
    if not runs:
        return {"status": "no_runs_yet"}
    latest = runs[0]
    runs_asc = list(reversed(runs))
    run_ids = [r.id for r in runs_asc]

    candidates = session.execute(select(Candidate).where(Candidate.run_id.in_(run_ids))).scalars().all()
    proposals = session.execute(select(Proposal).where(Proposal.run_id.in_(run_ids))).scalars().all()
    briefings = {rid: _briefing_for(session, rid) for rid in run_ids}
    positions = {p.ticker.upper(): p for p in session.execute(select(Position)).scalars()}

    def series(fn) -> list[dict]:
        out = []
        for r in runs_asc:
            value = fn(r)
            if value is not None:
                out.append({"run_id": r.id, "at": r.started_at.isoformat(), "value": value})
        return out

    scanned_by_run: dict[int, int] = {}
    found_by_run: dict[int, int] = {}
    for c in candidates:
        scanned_by_run[c.run_id] = scanned_by_run.get(c.run_id, 0) + 1
    for rid in run_ids:
        book = {b["ticker"] for b in (briefings.get(rid) or {}).get("book", [])}
        found_by_run[rid] = sum(1 for c in candidates if c.run_id == rid and c.stage2_passed and c.ticker not in book)
    actions_by_run: dict[int, int] = {}
    for p in proposals:
        actions_by_run[p.run_id] = actions_by_run.get(p.run_id, 0) + 1

    latest_briefing = briefings.get(latest.id) or {}
    health = latest_briefing.get("portfolio_health") or {}
    clusters = health.get("correlated_cluster_pct") or {}

    tiles: list[dict] = [
        {
            "key": "names_scanned", "label": "Names scanned", "value": scanned_by_run.get(latest.id, 0),
            "hint": "in the last run", "series": series(lambda r: scanned_by_run.get(r.id, 0)),
        },
        {
            "key": "candidates_found", "label": "Candidates found", "value": found_by_run.get(latest.id, 0),
            "hint": "new names past triage", "series": series(lambda r: found_by_run.get(r.id, 0)),
        },
        {
            "key": "positions_held", "label": "Positions held", "value": len(positions),
            "hint": "in your book", "series": series(lambda r: len((briefings.get(r.id) or {}).get("book", [])) or None),
        },
        {
            "key": "actions_today", "label": "Actions today", "value": actions_by_run.get(latest.id, 0),
            "hint": "proposed this run", "series": series(lambda r: actions_by_run.get(r.id, 0)),
        },
    ]
    if "ai_semis" in clusters:
        tiles.append(
            {
                "key": "ai_semis_pct", "label": "AI-semis cluster", "value": clusters["ai_semis"], "unit": "%",
                "hint": "of the book, correlated",
                "series": series(lambda r: ((briefings.get(r.id) or {}).get("portfolio_health") or {}).get("correlated_cluster_pct", {}).get("ai_semis")),
            }
        )

    spend = _read_json(data_dir / "llm_spend.json")
    month = time.strftime("%Y-%m", time.gmtime())
    fmp = _read_json(data_dir / "fmp_call_budget.json")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        cap = load_config(config_path).budget.monthly_api_cap_usd
    except Exception:  # noqa: BLE001 — a missing/invalid config must not take the dashboard down
        cap = None
    if month in spend:
        tiles.append(
            {
                "key": "api_spend_mtd", "label": "API spend", "value": round(spend[month], 2), "unit": "$",
                "hint": f"of ${cap:.0f} monthly cap" if cap else "month to date", "cap": cap,
                "fmp_calls_today": fmp.get(today, 0), "series": [],
            }
        )

    # ---- setups: today's actions first, then researched new names by conviction
    latest_proposals = [p for p in proposals if p.run_id == latest.id]
    # Latest memo per ticker across runs — a holding on the weekly refresh
    # cadence keeps last week's memo until its turn comes round.
    research_by_ticker: dict[str, ResearchOutput] = {}
    for r in session.execute(select(ResearchOutput).order_by(ResearchOutput.run_id.desc(), ResearchOutput.id.desc())).scalars():
        research_by_ticker.setdefault(r.ticker.upper(), r)
    conviction_by_ticker: dict[str, float] = {}
    from core.models import Conviction

    for c in session.execute(select(Conviction).where(Conviction.run_id == latest.id)).scalars():
        conviction_by_ticker[c.ticker.upper()] = c.score
    book_by_ticker = {b["ticker"].upper(): b for b in latest_briefing.get("book", [])}
    actions_by_ticker = {a["order"]["ticker"].upper(): a for a in latest_briefing.get("actions_today", [])}

    setups: list[dict] = []
    seen: set[str] = set()

    def add(ticker: str, action: str, conviction: float | None, order: dict | None, reason: str | None) -> None:
        if ticker in seen:
            return
        seen.add(ticker)
        bars, _ = _cached_bars(data_dir, ticker)
        price, change = _last_close_and_change(bars)
        book = book_by_ticker.get(ticker)
        setups.append(
            {
                "ticker": ticker, "name": _company_name(data_dir, ticker), "action": action, "conviction": conviction,
                "price": price, "change_pct": change, "is_held": ticker in positions,
                "weight_pct": book["weight_pct"] if book else (order or {}).get("weight_pct"),
                "order": order, "reason": reason,
            }
        )

    for p in sorted(latest_proposals, key=lambda p: -p.conviction):
        item = actions_by_ticker.get(p.ticker.upper())
        order = item["order"] if item else None
        action = "TRIM" if (order and order.get("is_trim")) else p.action
        add(p.ticker.upper(), action, p.conviction, order, item["headline"] if item else None)
    for ticker, score in sorted(conviction_by_ticker.items(), key=lambda kv: -kv[1]):
        if ticker in positions:
            continue
        add(ticker, "CANDIDATE", score, None, "researched, no order sized")
    setups = setups[:MAX_SETUPS]

    # ---- holdings: every held name with today's action (or HOLD), for the
    # briefing's selector and the Positions screen
    action_for = {s["ticker"]: s["action"] for s in setups if s["action"] != "CANDIDATE"}
    holdings: list[dict] = []
    for ticker, pos in sorted(positions.items(), key=lambda kv: -(book_by_ticker.get(kv[0], {}).get("weight_pct") or 0)):
        bars, _ = _cached_bars(data_dir, ticker)
        price, change = _last_close_and_change(bars)
        book = book_by_ticker.get(ticker, {})
        holdings.append(
            {
                "ticker": ticker, "name": _company_name(data_dir, ticker), "action": action_for.get(ticker, "HOLD"),
                "conviction": book.get("conviction_now"), "price": price, "change_pct": change,
                "weight_pct": book.get("weight_pct"), "qty": pos.qty, "avg_cost": pos.avg_cost,
                "unrealized_pnl_pct": book.get("unrealized_pnl_pct"), "has_exit_trigger": bool(book.get("has_exit_trigger")),
            }
        )
    plan_targets = {s["ticker"]: s for s in setups}
    for h in holdings:
        plan_targets.setdefault(h["ticker"], {"ticker": h["ticker"], "conviction": h["conviction"], "order": None, "weight_pct": h["weight_pct"]})

    # ---- trade plans, from the pipeline's own trigger math
    try:
        scaling = load_config(config_path).conviction_scaling
    except Exception:  # noqa: BLE001
        scaling = None
    sizing_notes: dict[str, str] = {}
    for ev in session.execute(
        select(RiskEvent).where(RiskEvent.run_id == latest.id, RiskEvent.type == "SIZING_REJECTED")
    ).scalars():
        detail = json.loads(ev.detail_json or "{}")
        if detail.get("ticker"):
            sizing_notes[detail["ticker"].upper()] = "; ".join(detail.get("reasons", [])) or "sizing rejected"

    plans: dict[str, dict] = {}
    for s in plan_targets.values():
        ticker = s["ticker"]
        conviction = s["conviction"]
        pos = positions.get(ticker)
        order = s["order"]
        bars, _ = _cached_bars(data_dir, ticker)
        tech = compute_technical_snapshot(bars) if bars else None
        stop = target = target_pct = None
        if pos is not None and conviction is not None and scaling is not None:
            multiple = lerp_by_conviction(
                conviction, scaling.trailing_stop_atr_multiple.at_0, scaling.trailing_stop_atr_multiple.at_100
            )
            if pos.peak_price_since_activation and tech and tech.atr_14:
                stop = pos.peak_price_since_activation - multiple * tech.atr_14
            target_pct = lerp_by_conviction(
                conviction, scaling.profit_taking_start_pct.at_0, scaling.profit_taking_start_pct.at_100
            )
            target = pos.avg_cost * (1 + target_pct / 100) if pos.avg_cost else None
        plans[ticker] = {
            "entry_price": order["limit_price"] if order else (pos.avg_cost if pos else None),
            "entry_basis": "limit order" if order else ("average cost" if pos else None),
            "stop_price": stop,
            "target_price": target,
            "target_pct": target_pct,
            "quantity": order["quantity"] if order else (pos.qty if pos else None),
            "est_cost_usd": order["estimated_cost_usd"] if order else None,
            "weight_pct": s["weight_pct"],
            "conviction": conviction,
            "atr_14": tech.atr_14 if tech else None,
            "note": (
                f"No order sized: {sizing_notes[ticker]}." if ticker in sizing_notes
                else ("Researched this run; no order was proposed." if order is None and pos is None else None)
            ),
        }

    # ---- one-line insights per setup, from the latest memo and stage 1 gates
    insights: dict[str, dict] = {}
    cand_by_ticker = {c.ticker.upper(): c for c in candidates if c.run_id == latest.id}
    for s in plan_targets.values():
        ticker = s["ticker"]
        memo = research_by_ticker.get(ticker)
        cand = cand_by_ticker.get(ticker)
        gates = json.loads(cand.stage1_json).get("gates", {}) if cand else {}
        rank = json.loads(cand.stage1_json).get("rank_score") if cand else None
        book = book_by_ticker.get(ticker)
        technical = _technical_sentence(rank, gates.get("valuation_band"), bool(book and book.get("has_exit_trigger")))
        fundamental = memo.thesis_summary if memo else None
        news = None
        risk = None
        if memo:
            reasoning = json.loads(memo.reasoning_json or "{}")
            digest = (reasoning.get("news_digest") or "").strip()
            sources = reasoning.get("news_sources") or []
            if digest and sources and "NO_MATERIAL_NEWS" not in digest:
                news = f"{_one_line(_first_news_line(digest), 150)} ({len(sources)} source{'s' if len(sources) != 1 else ''})"
            else:
                news = "No sourced news found in the lookback window."
            bear = json.loads(memo.bear_case_json or "{}")
            if bear.get("thesis"):
                dd = bear.get("estimated_downside_pct")
                risk = f"{_one_line(bear['thesis'], 150)}" + (f" If that happens, the estimate is a fall of about {dd:.0f}%." if dd is not None else "")
        insights[ticker] = {
            "technical": _one_line(technical), "fundamental": _one_line(fundamental), "news": news, "risk": risk,
        }

    points, nav_source = nav_series(session)
    return {
        "status": "ok",
        "run": {"run_id": latest.id, "status": latest.status, "started_at": latest.started_at.isoformat(),
                "finished_at": latest.finished_at.isoformat() if latest.finished_at else None},
        "tiles": tiles,
        "pnl": _pnl(points, nav_source),
        "setups": setups,
        "holdings": holdings,
        "plans": plans,
        "insights": insights,
    }


# ------------------------------------------------------------ prices


@router.get("/prices/{ticker}")
def get_prices(ticker: str, range: str = "1M", data_dir: Path = Depends(get_data_dir)) -> dict:
    """Daily bars from the yfinance cache — what the last run priced against.
    Intraday (1D) is not stored, so it is not offered."""
    if range not in RANGES:
        raise HTTPException(status_code=422, detail=f"range must be one of {', '.join(RANGES)}")
    bars, as_of = _cached_bars(data_dir, ticker)
    if not bars:
        raise HTTPException(status_code=404, detail=f"No cached price history for {ticker.upper()}.")
    cutoff = (dt.date.fromisoformat(bars[-1].date) - dt.timedelta(days=RANGES[range])).isoformat()
    window = [b for b in bars if b.date >= cutoff]
    return {
        "ticker": ticker.upper(), "range": range, "as_of": as_of, "available_ranges": list(RANGES),
        "bars": [b.__dict__ for b in window],
    }
