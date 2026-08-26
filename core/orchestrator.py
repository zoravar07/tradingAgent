"""Orchestrator — §10 step 9: "wire, schedule, log everything." Runs §5's
full pipeline once, persists every stage to the §6 tables so a run is fully
replayable afterward, and returns the assembled §3 briefing.

**Open question this module does NOT resolve**: §5 sets Universe = S&P500 +
watchlist + all current holdings, and per-ticker data gathering (Stage 1's
quant fields, Research's context text) costs several FMP calls each — S&P500
alone is ~500 names against the 250-calls/day free-tier budget that
sources/fmp.py's docstring already flagged as unsolved. This module takes a
resolved `universe_tickers` list and a `MarketDataGateway` as inputs rather
than deciding how to economically fetch 500 names' worth of data — that's a
real decision (a paid FMP tier? a cheaper bulk/screener endpoint? a smaller
day-to-day universe?) worth making deliberately. Flagged here, not guessed
at, same as step 3.

Also not built here: computing `daily_loss_pct`/`drawdown_pct` from NAV
history (needs a NAV time series this codebase doesn't track yet), and
sector/correlated-cluster classification per ticker (needs a ticker-to-
sector/cluster mapping the spec never defines a source for). Both are
accepted as inputs to `run_nightly` rather than invented here.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.order_builder import build_buy_order, build_exit_order
from agents.research import ResearchContext, run_research_batch
from agents.screener import (
    ScreenerInput,
    run_stage1,
    run_stage2_batch,
    select_stage2_survivors,
    select_survivors,
)
from core.briefing import (
    ActionItem,
    BookEntry,
    Briefing,
    OvernightChange,
    PortfolioHealth,
    WatchlistItem as BriefingWatchlistItem,
    assemble_briefing,
)
from core.config import Config
from core.llm import LLMClient
from core.models import Candidate, Conviction as ConvictionRow, Proposal, ResearchOutput, RiskEvent, Run
from core.models import WatchlistItem as WatchlistItemRow
from core.portfolio import PortfolioService
from core.risk_rules import (
    ScoredProposal,
    check_kill_switches,
    enforce_daily_proposal_cap,
    evaluate_held_position,
    size_new_position,
    update_peak_price,
)
from core.scoring import compute_conviction

logger = logging.getLogger("zopro.orchestrator")


class MarketDataGateway(Protocol):
    def get_screener_input(self, ticker: str, is_held: bool) -> ScreenerInput: ...
    def get_research_context(self, ticker: str) -> str: ...
    def get_current_price(self, ticker: str) -> float: ...
    def get_sector(self, ticker: str) -> str | None: ...
    def get_cluster(self, ticker: str) -> str | None: ...


def build_universe(sp500_tickers: list[str], watchlist: list[str], held_tickers: list[str]) -> list[str]:
    """§5: "Universe = S&P500 + watchlist + ALL current holdings." Held
    positions are listed first so a caller iterating the universe in order
    hits them before any API budget runs out — losing a held-position
    evaluation is worse than losing a new-candidate screen."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for group in (held_tickers, watchlist, sp500_tickers):
        for raw in group:
            ticker = raw.upper()
            if ticker not in seen_set:
                seen.append(ticker)
                seen_set.add(ticker)
    return seen


@dataclass
class NightlyRunInputs:
    as_of: dt.datetime
    universe_tickers: list[str]
    held_tickers: list[str]
    nav_usd: float
    cash_available_usd: float
    daily_loss_pct: float = 0.0
    drawdown_pct: float = 0.0
    current_sector_pct: dict[str, float] = field(default_factory=dict)
    current_cluster_pct: dict[str, float] = field(default_factory=dict)


def _stage1_gate_summary(result) -> dict:
    return {
        "passed": result.passed,
        "held_override": result.held_override,
        "reasons": result.reasons,
        "gates": {
            "liquidity_pass": result.gates.liquidity_pass,
            "fundamental_floor_pass": result.gates.fundamental_floor_pass,
            "valuation_band": result.gates.valuation_band,
            "earnings_soon": result.gates.earnings_soon,
        },
        "rank_score": result.rank_score,
    }


def run_nightly(
    *,
    session: Session,
    config: Config,
    gateway: MarketDataGateway,
    llm: LLMClient,
    portfolio: PortfolioService,
    inputs: NightlyRunInputs,
) -> Briefing:
    logger.info("run start as_of=%s universe_size=%d", inputs.as_of, len(inputs.universe_tickers))
    run_row = Run(
        started_at=inputs.as_of,
        finished_at=None,
        status="running",
        config_snapshot_json=config.model_dump_json(),
        error=None,
    )
    session.add(run_row)
    session.flush()

    try:
        briefing = _run_pipeline(session, config, gateway, llm, portfolio, inputs, run_row)
        run_row.status = "succeeded"
        run_row.finished_at = _utcnow()
        session.flush()
        logger.info("run succeeded run_id=%s", run_row.id)
        return briefing
    except Exception as exc:
        run_row.status = "failed"
        run_row.finished_at = _utcnow()
        run_row.error = str(exc)
        session.flush()
        logger.exception("run failed run_id=%s", run_row.id)
        raise


def _run_pipeline(session, config, gateway, llm, portfolio, inputs, run_row) -> Briefing:
    held_set = {t.upper() for t in inputs.held_tickers}

    # ---------------------------------------------------------------- Stage 1
    screener_inputs: dict[str, ScreenerInput] = {}
    for ticker in inputs.universe_tickers:
        try:
            screener_inputs[ticker] = gateway.get_screener_input(ticker, ticker in held_set)
        except Exception as exc:  # noqa: BLE001 — one bad data fetch must not kill the run
            session.add(RiskEvent(run_id=run_row.id, type="DATA_FETCH_FAILED", detail_json=json.dumps({"ticker": ticker, "stage": "stage1_input", "error": str(exc)})))
            logger.warning("stage1 input fetch failed ticker=%s error=%s", ticker, exc)

    stage1_results = run_stage1(list(screener_inputs.values()), config.screener.stage1)
    stage1_by_ticker = {r.ticker: r for r in stage1_results}
    for r in stage1_results:
        session.add(
            Candidate(
                run_id=run_row.id,
                ticker=r.ticker,
                stage1_json=json.dumps(_stage1_gate_summary(r)),
                stage1_passed=r.passed,
            )
        )
    session.flush()
    stage1_survivors = select_survivors(stage1_results, config.screener.stage1)
    logger.info("stage1 survivors=%d/%d", len(stage1_survivors), len(stage1_results))

    # ---------------------------------------------------------------- Stage 2
    stage2_results = run_stage2_batch(llm, stage1_survivors, config.screener.stage2)
    candidate_rows = {
        row.ticker: row
        for row in session.execute(select(Candidate).where(Candidate.run_id == run_row.id)).scalars()
    }
    for r2 in stage2_results:
        row = candidate_rows.get(r2.ticker)
        if row is not None:
            row.stage2_verdict = r2.verdict
            row.stage2_material = r2.material
            row.stage2_passed = r2.passed
    session.flush()
    stage2_survivors = select_stage2_survivors(stage2_results, stage1_by_ticker, config.screener.stage2)
    logger.info("stage2 survivors=%d/%d", len(stage2_survivors), len(stage2_results))

    # --------------------------------------------------------------- Research
    research_contexts = [
        ResearchContext(ticker=r.ticker, context_text=gateway.get_research_context(r.ticker)) for r in stage2_survivors
    ]
    research_results = run_research_batch(llm, research_contexts, config.research)

    conviction_by_ticker: dict[str, float] = {}
    memo_by_ticker: dict[str, object] = {}
    for rr in research_results:
        if not rr.ok:
            session.add(RiskEvent(run_id=run_row.id, type="RESEARCH_FAILED", detail_json=json.dumps({"ticker": rr.ticker, "error": rr.error})))
            logger.warning("research failed ticker=%s error=%s", rr.ticker, rr.error)
            continue

        memo = rr.memo
        memo_by_ticker[rr.ticker] = memo
        session.add(
            ResearchOutput(
                run_id=run_row.id,
                ticker=rr.ticker,
                subscores_json=json.dumps(memo.subscores()),
                reasoning_json=json.dumps({}),
                consensus_view=memo.consensus_view,
                variant_view=memo.variant_view,
                bear_case_json=json.dumps(memo.bear_case.model_dump()),
                catalysts_json=json.dumps([c.model_dump() for c in memo.catalysts]),
                risks_json=json.dumps(memo.key_risks),
                thesis_summary=memo.thesis_summary,
                model=config.research.model,
                input_tokens=rr.usage.input_tokens if rr.usage else None,
                output_tokens=rr.usage.output_tokens if rr.usage else None,
            )
        )

        conviction_result = compute_conviction(memo.subscores(), config.conviction_weights)
        conviction_by_ticker[rr.ticker] = conviction_result.score
        session.add(
            ConvictionRow(
                run_id=run_row.id,
                ticker=rr.ticker,
                score=conviction_result.score,
                weights_snapshot_json=json.dumps(conviction_result.normalized_weights),
                derivation_json=json.dumps(conviction_result.derivation()),
            )
        )
    session.flush()

    # -------------------------------------------------------- Risk: run-level
    kill_status = check_kill_switches(inputs.daily_loss_pct, inputs.drawdown_pct, config.risk)
    if kill_status.triggered:
        session.add(RiskEvent(run_id=run_row.id, type="KILL_SWITCH", detail_json=json.dumps({"reasons": kill_status.reasons})))
        logger.warning("kill switch triggered reasons=%s", kill_status.reasons)

    # ---------------------------------------------------- Held positions: exits
    action_items: list[ActionItem] = []
    book_entries: list[BookEntry] = []
    for pos in portfolio.list_positions():
        try:
            current_price = gateway.get_current_price(pos.ticker)
        except Exception as exc:  # noqa: BLE001
            session.add(RiskEvent(run_id=run_row.id, type="DATA_FETCH_FAILED", detail_json=json.dumps({"ticker": pos.ticker, "stage": "current_price", "error": str(exc)})))
            logger.warning("price fetch failed for held position ticker=%s error=%s", pos.ticker, exc)
            continue

        pos.peak_price_since_activation = update_peak_price(pos.peak_price_since_activation, current_price)

        screener_input = screener_inputs.get(pos.ticker)
        atr_14 = screener_input.technical.atr_14 if screener_input else None
        conviction_now = conviction_by_ticker.get(pos.ticker, pos.conviction_at_entry or 50.0)

        evaluation = evaluate_held_position(
            ticker=pos.ticker,
            current_price=current_price,
            avg_cost=pos.avg_cost,
            peak_price=pos.peak_price_since_activation,
            atr_14=atr_14,
            conviction_now=conviction_now,
            conviction_at_entry=pos.conviction_at_entry,
            scaling=config.conviction_scaling,
            config=config.risk,
        )

        value_usd = pos.qty * current_price
        weight_pct = (value_usd / inputs.nav_usd * 100) if inputs.nav_usd else 0.0
        unrealized_pnl_pct = ((current_price - pos.avg_cost) / pos.avg_cost * 100) if pos.avg_cost else 0.0

        if evaluation.has_exit_signal:
            order = build_exit_order(
                pos.ticker, pos.qty, current_price, weight_pct, conviction_now, evaluation, config.order_builder
            )
            if order is not None:
                headline = {
                    "TRAILING_STOP": "Trailing stop triggered",
                    "PROFIT_BAND": f"Trim {int(config.order_builder.profit_trim_fraction * 100)}%",
                    "THESIS_DECAY": "Thesis decay",
                }.get(evaluation.primary_trigger.type, "Exit triggered")
                memo = memo_by_ticker.get(pos.ticker)
                action_items.append(
                    ActionItem(
                        order=order,
                        headline=headline,
                        thesis_summary=getattr(memo, "thesis_summary", None),
                        bear_case=getattr(getattr(memo, "bear_case", None), "thesis", None),
                    )
                )
                session.add(
                    Proposal(
                        run_id=run_row.id, ticker=order.ticker, action=order.action, quantity=order.quantity,
                        order_type=order.order_type, limit_price=order.limit_price, est_cost=order.estimated_cost_usd,
                        conviction=order.conviction, rationale=headline,
                        risk_checks_json=json.dumps([t.type for t in evaluation.triggers]),
                        trigger_type=order.trigger_type, status="proposed", created_at=inputs.as_of,
                    )
                )

        book_entries.append(
            BookEntry(
                ticker=pos.ticker, qty=pos.qty, value_usd=value_usd, weight_pct=weight_pct,
                unrealized_pnl_pct=unrealized_pnl_pct, conviction_now=conviction_by_ticker.get(pos.ticker),
                conviction_at_entry=pos.conviction_at_entry,
                distance_to_trailing_stop_pct=_distance_to_stop_pct(evaluation, current_price),
                has_exit_trigger=evaluation.has_exit_signal,
            )
        )
    session.flush()

    # ---------------------------------------------------- New candidates: BUYs
    new_proposals: list[ScoredProposal] = []
    if not kill_status.triggered:
        for ticker, conviction in conviction_by_ticker.items():
            if ticker in held_set:
                continue
            new_proposals.append(ScoredProposal(ticker=ticker, conviction=conviction))
    capped = enforce_daily_proposal_cap(new_proposals, config.risk)

    for scored in capped:
        screener_input = screener_inputs.get(scored.ticker)
        if screener_input is None:
            continue
        try:
            current_price = gateway.get_current_price(scored.ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("price fetch failed for candidate ticker=%s error=%s", scored.ticker, exc)
            continue

        sizing = size_new_position(
            conviction_score=scored.conviction,
            atr_pct_of_price=screener_input.technical.atr_pct_of_price,
            nav_usd=inputs.nav_usd,
            sector=gateway.get_sector(scored.ticker),
            cluster=gateway.get_cluster(scored.ticker),
            current_sector_pct=inputs.current_sector_pct,
            current_cluster_pct=inputs.current_cluster_pct,
            cash_available_usd=inputs.cash_available_usd,
            scaling=config.conviction_scaling,
            config=config.risk,
        )
        if not sizing.approved:
            session.add(RiskEvent(run_id=run_row.id, type="SIZING_REJECTED", detail_json=json.dumps({"ticker": scored.ticker, "reasons": sizing.reasons})))
            continue

        order = build_buy_order(scored.ticker, scored.conviction, sizing, current_price, config.order_builder)
        if order is None:
            continue
        memo = memo_by_ticker.get(scored.ticker)
        action_items.append(
            ActionItem(
                order=order, headline="New position",
                thesis_summary=getattr(memo, "thesis_summary", None),
                bear_case=getattr(getattr(memo, "bear_case", None), "thesis", None),
            )
        )
        session.add(
            Proposal(
                run_id=run_row.id, ticker=order.ticker, action=order.action, quantity=order.quantity,
                order_type=order.order_type, limit_price=order.limit_price, est_cost=order.estimated_cost_usd,
                conviction=order.conviction, rationale=getattr(memo, "thesis_summary", "") or "",
                risk_checks_json=json.dumps(sizing.reasons), trigger_type=None, status="proposed",
                created_at=inputs.as_of,
            )
        )
    session.flush()

    # -------------------------------------------------------------- Watching
    watching = _build_watchlist(stage1_by_ticker, screener_inputs, held_set, config, run_row, session)

    briefing = assemble_briefing(
        generated_at=inputs.as_of,
        actions_today=action_items,
        watching=watching,
        overnight_changes=_overnight_changes(stage2_results, held_set),
        book=book_entries,
        portfolio_health=PortfolioHealth(
            correlated_cluster_pct=inputs.current_cluster_pct,
            cash_pct=(inputs.cash_available_usd / inputs.nav_usd * 100) if inputs.nav_usd else 0.0,
            kill_switch=kill_status,
        ),
        drift=portfolio.check_drift(as_of=inputs.as_of),
    )
    return briefing


def _distance_to_stop_pct(evaluation, current_price: float) -> float | None:
    for trigger in evaluation.triggers:
        if trigger.type == "TRAILING_STOP":
            stop_price = trigger.detail.get("stop_price")
            if stop_price is not None and current_price:
                return (current_price - stop_price) / current_price * 100
    return None


def _overnight_changes(stage2_results, held_set: set[str]) -> list[OvernightChange]:
    return [
        OvernightChange(ticker=r.ticker, summary=r.verdict)
        for r in stage2_results
        if r.ticker in held_set and r.material and r.verdict
    ]


def _build_watchlist(stage1_by_ticker, screener_inputs, held_set, config, run_row, session) -> list[BriefingWatchlistItem]:
    """§3.2: "Names approaching a trigger but not there yet." Read as: Stage 1
    survivors that didn't make the Stage 2 cut but are close on relative
    strength, or held positions with decaying-but-not-yet-triggered
    conviction. This module doesn't have Stage 2 results in scope at the
    point it's called from `_run_pipeline`'s watchlist step in the current
    wiring — kept intentionally simple (Stage 1 near-misses only) rather
    than guessing at a richer "approaching a trigger" definition the spec
    doesn't specify."""
    items: list[BriefingWatchlistItem] = []
    for ticker, result in stage1_by_ticker.items():
        if ticker in held_set or result.passed:
            continue
        if result.rank_score is not None and result.rank_score > 0:
            item = BriefingWatchlistItem(ticker=ticker, reason="near Stage 1 cutoff", distance_to_trigger_pct=result.rank_score)
            items.append(item)
            session.add(WatchlistItemRow(run_id=run_row.id, ticker=ticker, reason=item.reason, distance_to_trigger=result.rank_score))
    session.flush()
    return items


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
