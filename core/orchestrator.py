"""Orchestrator — §10 step 9: "wire, schedule, log everything." Runs §5's
full pipeline once, persists every stage to the §6 tables so a run is fully
replayable afterward, and returns the assembled §3 briefing.

**Universe and FMP budget.** §5's "Universe = S&P500 + watchlist + all
current holdings" doesn't fit the 250-calls/day free tier at ~500 names
(step 3 flagged this first). Per the user's decision: the day-to-day
universe is holdings + watchlist + a rotating slice of the S&P 500
(`config.universe.rotating_scan_size`, default 30 — see `resolve_universe`
and `rotating_slice`), so the full pool still gets covered over roughly
`len(pool) / rotating_scan_size` days. `config.universe.weekly_wide_scan`
can flip on a full-pool day for a paid FMP tier.

**NAV and drawdown** (not in §6's original schema — added per the user's
request): NAV = sum of held positions' market value + cash (cash sourced
from the most recent Flex import's cash row, see core/portfolio.py's
`latest_cash_balance`). Drawdown and daily-loss are derived run-over-run by
core/nav.py, starting at zero on the first recorded run.

**Sector/cluster**: sector comes from the gateway (FMP's profile "sector"
field, live gateway in sources/live_gateway.py); correlated-cluster
membership comes from `config.universe.cluster_overrides` — an explicit
map, not inferred, since the spec's own §9 note names the AI/semis cluster
by ticker rather than by any classification rule.
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
    UnpricedPosition,
    UnresearchedHolding,
    WatchlistItem as BriefingWatchlistItem,
    assemble_blocked_briefing,
    assemble_briefing,
)
from core.config import Config, UniverseConfig
from core.llm import LLMClient
from core.briefing_persistence import serialize_briefing
from core.models import BriefingRecord, Candidate, Conviction as ConvictionRow, Proposal, ResearchOutput, RiskEvent, Run
from core.models import WatchlistItem as WatchlistItemRow
from core.money import Money, usd
from core.nav import compute_nav, record_nav
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


def build_universe(held_tickers: list[str], watchlist: list[str], scan_tickers: list[str]) -> list[str]:
    """Merges the three universe components, de-duplicated, held positions
    first — so a partial run (budget exhausted partway through) never loses
    a held-position evaluation before a new-candidate screen."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for group in (held_tickers, watchlist, scan_tickers):
        for raw in group:
            ticker = raw.upper()
            if ticker not in seen_set:
                seen.append(ticker)
                seen_set.add(ticker)
    return seen


def rotating_slice(pool: list[str], batch_size: int, day_index: int) -> list[str]:
    """Deterministically picks up to `batch_size` tickers from `pool`,
    rotating which ones based on `day_index` (e.g. `date.toordinal()`) so
    consecutive days cover different names and the full pool gets scanned
    over `ceil(len(pool) / batch_size)` days."""
    if not pool or batch_size <= 0:
        return []
    n = len(pool)
    batch_size = min(batch_size, n)
    start = (day_index * batch_size) % n
    return [pool[(start + i) % n] for i in range(batch_size)]


def resolve_universe(
    *, held_tickers: list[str], pool: list[str], config: UniverseConfig, as_of: dt.datetime
) -> list[str]:
    """Ties `config.universe` together: a full-pool scan on the configured
    weekly-wide-scan day (if enabled), otherwise a rotating slice sized to
    `rotating_scan_size`, merged with holdings and the watchlist."""
    if config.weekly_wide_scan.enabled and as_of.weekday() == config.weekly_wide_scan.day_of_week:
        scan_tickers = pool
    else:
        scan_tickers = rotating_slice(pool, config.rotating_scan_size, as_of.toordinal())
    return build_universe(held_tickers, config.watchlist, scan_tickers)


@dataclass
class NightlyRunInputs:
    as_of: dt.datetime
    universe_tickers: list[str]
    held_tickers: list[str]
    # Money, not a bare float — see core/money.py's docstring for the real
    # bug (a broker dashboard shown in the account's base currency, not USD)
    # this is guarding against.
    cash: Money = field(default_factory=lambda: usd(0.0))


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
        run_row.status = "blocked" if briefing.blocked is not None else "succeeded"
        run_row.finished_at = _utcnow()
        # §10 step 10 gap: persist the assembled Briefing itself, not just
        # the rows it was built from — the UI reads this back exactly as
        # produced, rather than trying to reconstruct it (unreliably; the
        # live price used that night isn't stored anywhere else).
        session.add(
            BriefingRecord(run_id=run_row.id, briefing_json=serialize_briefing(briefing), created_at=_utcnow())
        )
        session.flush()
        logger.info("run %s run_id=%s", run_row.status, run_row.id)
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

    # ------------------------------------------------------- Pricing gate (§0)
    # Runs before anything else — including before Stage 1/2/Research, which
    # cost real LLM money — because a run that's going to be blocked should
    # never spend on screening/research it can't use. Zero tolerance by
    # default (config.risk.max_unpriced_held_positions): NAV is the sum of
    # every held position's market value, so even one missing price makes
    # NAV, weights, sector/cluster exposure, and every risk gate built on
    # them meaningless — a wrong-looking-confident briefing is worse than
    # none (user's framing, and correct: the first live run silently
    # understated NAV by more than half this way).
    held_positions = portfolio.list_positions()
    price_by_ticker: dict[str, float] = {}
    unpriced: list[UnpricedPosition] = []
    for pos in held_positions:
        try:
            price_by_ticker[pos.ticker] = gateway.get_current_price(pos.ticker)
        except Exception as exc:  # noqa: BLE001 — collected, not raised; the gate below decides what happens
            unpriced.append(UnpricedPosition(ticker=pos.ticker, error=str(exc)))

    if len(unpriced) > config.risk.max_unpriced_held_positions:
        for u in unpriced:
            session.add(
                RiskEvent(
                    run_id=run_row.id, type="PRICING_GATE_BLOCKED",
                    detail_json=json.dumps({"ticker": u.ticker, "error": u.error}),
                )
            )
        session.flush()
        logger.error(
            "pricing gate blocked run: %d/%d held positions unpriced (tolerance=%d): %s",
            len(unpriced), len(held_positions), config.risk.max_unpriced_held_positions,
            ", ".join(u.ticker for u in unpriced),
        )
        return assemble_blocked_briefing(
            inputs.as_of, unpriced, tolerance=config.risk.max_unpriced_held_positions, total_held=len(held_positions)
        )

    # research_gap_reason tracks, per ticker, why a HELD position ended up
    # with no conviction score this run — populated at each of the three
    # points research coverage can fall through (Stage 1 input fetch,
    # research context fetch, the research LLM call itself). Surfaced as a
    # top-of-briefing warning below, per the user's explicit request: a
    # held position with no conviction score is unmonitored, and that must
    # be impossible to miss, not just an "n/a" in a table.
    research_gap_reason: dict[str, str] = {}

    # ---------------------------------------------------------------- Stage 1
    screener_inputs: dict[str, ScreenerInput] = {}
    for ticker in inputs.universe_tickers:
        try:
            screener_inputs[ticker] = gateway.get_screener_input(ticker, ticker in held_set)
        except Exception as exc:  # noqa: BLE001 — one bad data fetch must not kill the run
            session.add(RiskEvent(run_id=run_row.id, type="DATA_FETCH_FAILED", detail_json=json.dumps({"ticker": ticker, "stage": "stage1_input", "error": str(exc)})))
            logger.warning("stage1 input fetch failed ticker=%s error=%s", ticker, exc)
            research_gap_reason[ticker] = f"Stage 1 data fetch failed: {exc}"

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
    research_contexts: list[ResearchContext] = []
    for r in stage2_survivors:
        try:
            context_text = gateway.get_research_context(r.ticker)
        except Exception as exc:  # noqa: BLE001 — one bad context fetch must not skip a Sonnet call for nothing, or kill the run
            session.add(RiskEvent(run_id=run_row.id, type="DATA_FETCH_FAILED", detail_json=json.dumps({"ticker": r.ticker, "stage": "research_context", "error": str(exc)})))
            logger.warning("research context fetch failed ticker=%s error=%s", r.ticker, exc)
            research_gap_reason[r.ticker] = f"Research context fetch failed: {exc}"
            continue
        research_contexts.append(ResearchContext(ticker=r.ticker, context_text=context_text))
    research_results = run_research_batch(llm, research_contexts, config.research)

    conviction_by_ticker: dict[str, float] = {}
    memo_by_ticker: dict[str, object] = {}
    for rr in research_results:
        if not rr.ok:
            session.add(RiskEvent(run_id=run_row.id, type="RESEARCH_FAILED", detail_json=json.dumps({"ticker": rr.ticker, "error": rr.error})))
            logger.warning("research failed ticker=%s error=%s", rr.ticker, rr.error)
            research_gap_reason[rr.ticker] = f"Research call failed: {rr.error}"
            continue

        memo = rr.memo
        memo_by_ticker[rr.ticker] = memo
        session.add(
            ResearchOutput(
                run_id=run_row.id,
                ticker=rr.ticker,
                subscores_json=json.dumps(memo.subscores()),
                reasoning_json=json.dumps({"unavailable_factors": memo.unavailable_factors()}),
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

    # ------------------------------------------------- NAV, sector, cluster pass
    # Prices were already fetched by the pricing gate above (and, in the
    # default zero-tolerance config, that gate guarantees every held
    # position is in price_by_ticker — this loop's `.get()` check only
    # matters if max_unpriced_held_positions was raised above zero, letting
    # some tolerated failures through). No re-fetching here.
    position_values: list[Money] = []  # FMP quotes are always USD by construction — plain floats before wrapping
    sector_value: dict[str, Money] = {}
    cluster_value: dict[str, Money] = {}
    for pos in held_positions:
        price = price_by_ticker.get(pos.ticker)
        if price is None:
            continue  # a tolerated failure (max_unpriced_held_positions > 0) — already recorded above
        value = usd(pos.qty * price)
        position_values.append(value)
        sector = gateway.get_sector(pos.ticker)
        cluster = gateway.get_cluster(pos.ticker)
        if sector:
            sector_value[sector] = sector_value.get(sector, usd(0.0)) + value
        if cluster:
            cluster_value[cluster] = cluster_value.get(cluster, usd(0.0)) + value

    nav = compute_nav(position_values, inputs.cash)
    sector_pct = {k: (v / nav) * 100 for k, v in sector_value.items()} if nav.amount else {}
    cluster_pct = {k: (v / nav) * 100 for k, v in cluster_value.items()} if nav.amount else {}
    nav_status = record_nav(session, run_row.id, nav, inputs.as_of)
    logger.info(
        "nav=%s peak=%s drawdown_pct=%.2f daily_loss_pct=%.2f",
        nav_status.nav, nav_status.peak_nav, nav_status.drawdown_pct, nav_status.daily_loss_pct,
    )

    # -------------------------------------------------------- Risk: run-level
    kill_status = check_kill_switches(nav_status.daily_loss_pct, nav_status.drawdown_pct, config.risk)
    if kill_status.triggered:
        session.add(RiskEvent(run_id=run_row.id, type="KILL_SWITCH", detail_json=json.dumps({"reasons": kill_status.reasons})))
        logger.warning("kill switch triggered reasons=%s", kill_status.reasons)

    # ---------------------------------------------------- Held positions: exits
    action_items: list[ActionItem] = []
    book_entries: list[BookEntry] = []
    for pos in held_positions:
        current_price = price_by_ticker.get(pos.ticker)
        if current_price is None:
            continue  # fetch already failed and was logged above

        pos.peak_price_since_activation = update_peak_price(pos.peak_price_since_activation, current_price)

        screener_input = screener_inputs.get(pos.ticker)
        atr_14 = screener_input.technical.atr_14 if screener_input else None
        has_fresh_conviction = pos.ticker in conviction_by_ticker
        conviction_now = conviction_by_ticker.get(pos.ticker, pos.conviction_at_entry or 50.0)
        if not has_fresh_conviction:
            research_gap_reason.setdefault(pos.ticker, "no research coverage this run")

        evaluation = evaluate_held_position(
            ticker=pos.ticker,
            current_price=current_price,
            avg_cost=pos.avg_cost,
            peak_price=pos.peak_price_since_activation,
            atr_14=atr_14,
            conviction_now=conviction_now,
            # Only pass a real conviction_at_entry when conviction_now is
            # also real this run. Without this, when unresearched,
            # conviction_now's fallback above (`pos.conviction_at_entry or
            # 50.0`) is self-referential when conviction_at_entry is set —
            # it already produces drop=0 (no false trigger) by coincidence,
            # not by a check that says so. Making it explicit here means
            # thesis-decay's "no signal without real research" guarantee
            # holds by construction, not by an accident of how the fallback
            # happens to be written — the fallback logic could change later
            # without anyone noticing it was quietly relied upon for this.
            # Trailing-stop/profit-band still use the fallback conviction_now
            # for scaling — those only need *some* reasonable basis, not a
            # fresh one, unlike thesis-decay's entry-vs-now comparison.
            conviction_at_entry=pos.conviction_at_entry if has_fresh_conviction else None,
            scaling=config.conviction_scaling,
            config=config.risk,
            # Same reasoning as the conviction_at_entry guard above: the
            # conviction floor (§ user-requested, core/risk_rules.py) looks
            # at conviction_now alone, so it needs its own explicit guard
            # against firing on a fabricated fallback rather than relying on
            # thesis-decay's guard to somehow cover it too.
            conviction_is_fresh=has_fresh_conviction,
        )

        value_usd = pos.qty * current_price  # plain float — FMP quote, unambiguously USD
        weight_pct = (value_usd / nav.amount * 100) if nav.amount else 0.0
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
                    "CONVICTION_FLOOR": f"Conviction below floor ({config.risk.min_hold_conviction:.0f})",
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
                no_research_coverage=not has_fresh_conviction,
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

    # Running totals so approving one BUY reduces room for the next, within
    # the same run — a static snapshot would let two proposals in the same
    # cluster each look individually fine while together blowing the cap.
    running_cash = inputs.cash
    running_sector_pct = dict(sector_pct)
    running_cluster_pct = dict(cluster_pct)

    for scored in capped:
        screener_input = screener_inputs.get(scored.ticker)
        if screener_input is None:
            continue
        try:
            current_price = gateway.get_current_price(scored.ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("price fetch failed for candidate ticker=%s error=%s", scored.ticker, exc)
            continue

        sector = gateway.get_sector(scored.ticker)
        cluster = gateway.get_cluster(scored.ticker)
        sizing = size_new_position(
            conviction_score=scored.conviction,
            atr_pct_of_price=screener_input.technical.atr_pct_of_price,
            nav_usd=nav.amount,  # risk_rules.py operates in plain USD floats — explicit unwrap, not implicit
            sector=sector,
            cluster=cluster,
            current_sector_pct=running_sector_pct,
            current_cluster_pct=running_cluster_pct,
            cash_available_usd=running_cash.amount,
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

        running_cash = running_cash - usd(order.estimated_cost_usd)
        if sector:
            running_sector_pct[sector] = running_sector_pct.get(sector, 0.0) + order.weight_pct
        if cluster:
            running_cluster_pct[cluster] = running_cluster_pct.get(cluster, 0.0) + order.weight_pct
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
            correlated_cluster_pct=cluster_pct,
            cash_pct=(inputs.cash / nav * 100) if nav.amount else 0.0,
            drawdown_from_peak_pct=nav_status.drawdown_pct,
            kill_switch=kill_status,
        ),
        drift=portfolio.check_drift(as_of=inputs.as_of),
        unresearched_holdings=[
            UnresearchedHolding(ticker=t, reason=r) for t, r in research_gap_reason.items() if t in held_set
        ],
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
