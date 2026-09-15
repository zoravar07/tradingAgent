import datetime as dt

from sqlalchemy import select

from core.db import init_db, make_engine, make_session_factory
from core.models import CostEvent, Position, Proposal, Run, SleeveBreachState


def test_position_has_sleeve_column():
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    position = Position(
        ticker="NVDA", qty=1, avg_cost=100.0, opened_at=dt.datetime(2026, 1, 1),
        source="manual", sleeve="SWING",
    )
    session.add(position)
    session.flush()
    assert session.get(Position, position.id).sleeve == "SWING"


def test_sleeve_breach_state_round_trips():
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    session.add(Run(id=1, started_at=dt.datetime(2026, 1, 1), status="succeeded", config_snapshot_json="{}"))
    session.flush()
    state = SleeveBreachState(sleeve="SWING", direction="OVER", streak_days=3, last_run_id=1)
    session.add(state)
    session.flush()
    fetched = session.get(SleeveBreachState, "SWING")
    assert (fetched.direction, fetched.streak_days, fetched.last_run_id) == ("OVER", 3, 1)


def test_proposal_speculative_warning_json_defaults_to_none():
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    session.add(Run(id=1, started_at=dt.datetime(2026, 1, 1), status="succeeded", config_snapshot_json="{}"))
    session.flush()
    proposal = Proposal(
        run_id=1, ticker="NVDA", action="BUY", quantity=1, order_type="LIMIT", limit_price=100.0,
        est_cost=100.0, conviction=60.0, rationale="", risk_checks_json="[]", status="proposed",
        created_at=dt.datetime(2026, 1, 1),
    )
    session.add(proposal)
    session.flush()
    assert session.get(Proposal, proposal.id).speculative_warning_json is None


def test_cost_event_round_trips_and_sums_per_run_per_stage():
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    session.add(Run(id=1, started_at=dt.datetime(2026, 1, 1), status="succeeded", config_snapshot_json="{}"))
    session.flush()
    session.add_all([
        CostEvent(
            run_id=1, stage="research_memo", ticker="AMD", model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=500, cost_usd=0.0105, created_at=dt.datetime(2026, 1, 1),
        ),
        CostEvent(
            run_id=1, stage="news_digest", ticker="AMD", model="claude-haiku-4-5",
            input_tokens=200, output_tokens=100, web_search_requests=1, cost_usd=0.011, created_at=dt.datetime(2026, 1, 1),
        ),
        CostEvent(
            run_id=1, stage="stage2_triage", ticker=None, model="claude-haiku-4-5",
            input_tokens=3000, output_tokens=800, cost_usd=0.007, created_at=dt.datetime(2026, 1, 1),
        ),
    ])
    session.flush()

    total = session.execute(select(CostEvent.cost_usd).where(CostEvent.run_id == 1)).scalars().all()
    assert sum(total) == 0.0105 + 0.011 + 0.007

    memo_only = session.execute(
        select(CostEvent.cost_usd).where(CostEvent.run_id == 1, CostEvent.stage == "research_memo")
    ).scalars().all()
    assert memo_only == [0.0105]
