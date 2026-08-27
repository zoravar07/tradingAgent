"""API tests — FastAPI's TestClient against an isolated temp-file DB per
test (create_app(db_path=...)), never the real data/z_money.db. No network."""

import datetime as dt

from fastapi.testclient import TestClient

from api.server import create_app
from core.briefing import ActionItem, BookEntry, PortfolioHealth, assemble_briefing
from core.briefing_persistence import serialize_briefing
from core.db import init_db, make_engine, make_session_factory
from core.models import BriefingRecord, Run
from agents.order_builder import OrderProposal

NOW = dt.datetime(2026, 8, 25, 22, 0, 0)


def make_client(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app(db_path=db_path)
    return TestClient(app), app.state.session_factory


def order():
    return OrderProposal(
        ticker="AMD", action="SELL", quantity=1, order_type="LIMIT", limit_price=476.78,
        estimated_cost_usd=476.78, weight_pct=13.7, conviction=54.0, trigger_type="PROFIT_BAND", is_trim=True,
    )


def seed_run_with_briefing(session_factory, status="succeeded", created_at=NOW):
    session = session_factory()
    run = Run(started_at=created_at, finished_at=created_at, status=status, config_snapshot_json="{}")
    session.add(run)
    session.flush()

    briefing = assemble_briefing(
        generated_at=created_at,
        actions_today=[ActionItem(order=order(), headline="Trim 50%", thesis_summary="thesis")],
        watching=[], overnight_changes=[],
        book=[BookEntry(ticker="AMD", qty=3.5, value_usd=1681.0, weight_pct=13.7, unrealized_pnl_pct=132.5)],
        portfolio_health=PortfolioHealth(cash_pct=0.3),
        drift=None,
    )
    session.add(BriefingRecord(run_id=run.id, briefing_json=serialize_briefing(briefing), created_at=created_at))
    session.commit()
    session.close()
    return run.id


class TestHealth:
    def test_health_ok(self, tmp_path):
        client, _ = make_client(tmp_path)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestGetLatestBriefing:
    def test_no_runs_yet(self, tmp_path):
        client, _ = make_client(tmp_path)
        resp = client.get("/api/briefing/latest")
        assert resp.status_code == 200
        assert resp.json() == {"status": "no_runs_yet"}

    def test_returns_the_persisted_briefing(self, tmp_path):
        client, session_factory = make_client(tmp_path)
        run_id = seed_run_with_briefing(session_factory)

        resp = client.get("/api/briefing/latest")
        body = resp.json()

        assert resp.status_code == 200
        assert body["status"] == "ok"
        assert body["run_id"] == run_id
        assert body["run_status"] == "succeeded"
        assert body["briefing"]["book"][0]["ticker"] == "AMD"
        assert body["briefing"]["actions_today"][0]["headline"] == "Trim 50%"

    def test_returns_the_most_recent_of_several_runs(self, tmp_path):
        client, session_factory = make_client(tmp_path)
        seed_run_with_briefing(session_factory, created_at=NOW - dt.timedelta(days=1))
        second_run_id = seed_run_with_briefing(session_factory, created_at=NOW)

        resp = client.get("/api/briefing/latest")
        assert resp.json()["run_id"] == second_run_id

    def test_blocked_run_status_surfaced(self, tmp_path):
        client, session_factory = make_client(tmp_path)
        seed_run_with_briefing(session_factory, status="blocked")

        resp = client.get("/api/briefing/latest")
        assert resp.json()["run_status"] == "blocked"


class TestCors:
    def test_vite_origin_allowed(self, tmp_path):
        client, _ = make_client(tmp_path)
        resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
