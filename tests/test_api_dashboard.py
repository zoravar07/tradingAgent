"""Dashboard + prices routes — temp DB, temp data dir, no network."""

import datetime as dt
import json

from fastapi.testclient import TestClient

from agents.order_builder import OrderProposal
from api.server import create_app
from core.briefing import ActionItem, BookEntry, PortfolioHealth, assemble_briefing
from core.briefing_persistence import serialize_briefing
from core.cache import FileCache
from core.models import Candidate, Conviction, NavSnapshot, Position, Proposal, ResearchOutput, Run

NOW = dt.datetime(2026, 9, 9, 12, 0, 0)


def make_client(tmp_path):
    (tmp_path / "data").mkdir()
    app = create_app(db_path=tmp_path / "data" / "t.db", config_path="config.yaml", data_dir=tmp_path / "data")
    return TestClient(app), app.state.session_factory, tmp_path / "data"


def bars(n=260, start=100.0):
    out = []
    day = dt.date(2025, 9, 1)
    for i in range(n):
        day += dt.timedelta(days=1)
        px = start + i * 0.5
        out.append({"date": day.isoformat(), "open": px, "high": px + 2, "low": px - 2, "close": px, "volume": 1e6})
    return out


def seed(session_factory, data_dir, runs=2):
    session = session_factory()
    session.add(Position(ticker="AMD", qty=3.5, avg_cost=200.0, opened_at=NOW, source="manual", peak_price_since_activation=240.0))
    for i in range(runs):
        at = NOW - dt.timedelta(days=runs - 1 - i)
        run = Run(started_at=at, finished_at=at, status="succeeded", config_snapshot_json="{}")
        session.add(run)
        session.flush()
        for t, passed in (("AMD", True), ("DELL", True), ("BADCO", False)):
            session.add(Candidate(run_id=run.id, ticker=t, stage1_json=json.dumps({"gates": {"valuation_band": "fair"}, "rank_score": 4.2}), stage1_passed=True, stage2_passed=passed, stage2_material=passed))
        session.add(Proposal(run_id=run.id, ticker="AMD", action="SELL", quantity=1, order_type="LIMIT", limit_price=230.0, est_cost=230.0, conviction=58.0, rationale="r", risk_checks_json="[]", trigger_type="PROFIT_BAND", status="proposed", created_at=at))
        for t, score in (("AMD", 58.0), ("DELL", 64.8)):
            session.add(Conviction(run_id=run.id, ticker=t, score=score, weights_snapshot_json="{}", derivation_json="{}"))
            session.add(ResearchOutput(run_id=run.id, ticker=t, subscores_json="{}", reasoning_json=json.dumps({"unavailable_factors": [], "news_digest": "Here are the developments:\n2026-09-08: raised guidance.", "news_sources": ["https://x/1"]}), consensus_view="c", variant_view="v", bear_case_json=json.dumps({"thesis": "Margins compress.", "estimated_downside_pct": 30}), catalysts_json="[]", risks_json="[]", thesis_summary=f"{t} thesis.", model="m"))
        order = OrderProposal(ticker="AMD", action="SELL", quantity=1, order_type="LIMIT", limit_price=230.0, estimated_cost_usd=230.0, weight_pct=14.0, conviction=58.0, trigger_type="PROFIT_BAND", is_trim=True)
        briefing = assemble_briefing(
            generated_at=at, actions_today=[ActionItem(order=order, headline="Trim 50%")], watching=[], overnight_changes=[],
            book=[BookEntry(ticker="AMD", qty=3.5, value_usd=800.0, weight_pct=14.0, unrealized_pnl_pct=15.0, conviction_now=58.0, has_exit_trigger=True)],
            portfolio_health=PortfolioHealth(cash_pct=0.3, correlated_cluster_pct={"ai_semis": 55.0}),
        )
        from core.models import BriefingRecord
        session.add(BriefingRecord(run_id=run.id, briefing_json=serialize_briefing(briefing), created_at=at))
    # NAV history: 40 days ago 10,000; 8 days ago 11,000; 2 days ago 11,800; now 12,000
    for days_ago, nav in ((40, 10_000.0), (8, 11_000.0), (2, 11_800.0), (0, 12_000.0)):
        session.add(NavSnapshot(run_id=run.id, recorded_at=NOW - dt.timedelta(days=days_ago), nav_usd=nav, peak_nav_usd=nav, drawdown_pct=0.0, daily_loss_pct=0.0))
    session.commit()
    session.close()
    FileCache(data_dir / "yf_cache").set("yf:hist:AMD:2y", bars(), 1)  # TTL 1s: display must ignore freshness
    FileCache(data_dir / "cache").set('fmp:profile:{"symbol": "AMD"}', [{"symbol": "AMD", "companyName": "Advanced Micro Devices, Inc."}], 1)
    (data_dir / "llm_spend.json").write_text(json.dumps({dt.datetime.utcnow().strftime("%Y-%m"): 8.7552}))
    (data_dir / "fmp_call_budget.json").write_text(json.dumps({dt.datetime.utcnow().strftime("%Y-%m-%d"): 145}))


class TestDashboard:
    def test_no_runs(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        assert client.get("/api/dashboard").json() == {"status": "no_runs_yet"}

    def test_tiles_are_real_counts_with_series(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        body = client.get("/api/dashboard").json()
        tiles = {t["key"]: t for t in body["tiles"]}
        assert tiles["names_scanned"]["value"] == 3 and len(tiles["names_scanned"]["series"]) == 2
        assert tiles["candidates_found"]["value"] == 1  # DELL passed triage and isn't in the book
        assert tiles["positions_held"]["value"] == 1
        assert tiles["actions_today"]["value"] == 1
        assert tiles["ai_semis_pct"]["value"] == 55.0
        assert tiles["api_spend_mtd"]["value"] == 8.76 and tiles["api_spend_mtd"]["cap"] == 80.0
        assert tiles["api_spend_mtd"]["fmp_calls_today"] == 145
        assert not any(k in tiles for k in ("win_rate", "total_trades", "avg_return"))

    def test_setups_actions_first_then_candidates_with_cached_price(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        setups = client.get("/api/dashboard").json()["setups"]
        assert [s["ticker"] for s in setups] == ["AMD", "DELL"]
        assert setups[0]["action"] == "TRIM" and setups[0]["is_held"] is True
        assert setups[0]["price"] == 229.5 and round(setups[0]["change_pct"], 3) == round(0.5 / 229.0 * 100, 3)
        assert setups[1]["action"] == "CANDIDATE" and setups[1]["price"] is None  # no cached bars, no invented price

    def test_plan_uses_pipeline_trigger_math(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        plan = client.get("/api/dashboard").json()["plans"]["AMD"]
        assert plan["entry_price"] == 230.0 and plan["entry_basis"] == "limit order"
        # profit band: lerp(58, 15, 60) = 41.1% above the $200 cost basis
        assert round(plan["target_pct"], 1) == 41.1 and round(plan["target_price"], 2) == 282.2
        # trailing stop: peak 240 - lerp(58, 1.5, 4.5) * ATR14 (ATR of the synthetic bars = 4.0)
        assert plan["stop_price"] is not None and 220 < plan["stop_price"] < 240
        assert plan["quantity"] == 1 and plan["conviction"] == 58.0
        assert plan["note"] is None

    def test_candidate_plan_carries_the_sizing_rejection(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        session = sf()
        from core.models import RiskEvent, Run
        from sqlalchemy import select
        latest = session.execute(select(Run).order_by(Run.started_at.desc())).scalars().first()
        session.add(RiskEvent(run_id=latest.id, type="SIZING_REJECTED", detail_json=json.dumps({"ticker": "DELL", "reasons": ["capped by sector room 0.0% (sector Technology)", "below min_order_value_usd $150"]})))
        session.commit(); session.close()
        plan = client.get("/api/dashboard").json()["plans"]["DELL"]
        assert plan["entry_price"] is None
        assert plan["note"] == "No order sized: capped by sector room 0.0% (sector Technology); below min_order_value_usd $150."

    def test_insights_are_one_liners_from_persisted_data(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        ins = client.get("/api/dashboard").json()["insights"]["AMD"]
        assert ins["technical"] == "Over the last three months the shares have done 4 percentage points better than the S&P 500. The share price is about in line with the company's profits. One of your sell rules has been triggered."
        assert ins["fundamental"] == "AMD thesis."
        assert ins["news"].startswith("2026-09-08: raised guidance.") and "(1 source)" in ins["news"]
        assert "\n" not in ins["fundamental"]
        assert ins["risk"] == "Margins compress. If that happens, the estimate is a fall of about 30%."


class TestPrices:
    def test_ranges_window_the_cached_bars(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        week = client.get("/api/prices/amd?range=1W").json()
        year = client.get("/api/prices/AMD?range=1Y").json()
        assert week["ticker"] == "AMD" and 5 <= len(week["bars"]) <= 8
        assert len(year["bars"]) == 260 and week["available_ranges"] == ["1W", "1M", "3M", "1Y"]
        assert week["as_of"] is not None

    def test_unknown_ticker_404_and_bad_range_422(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        assert client.get("/api/prices/ZZZZ?range=1M").status_code == 404
        assert client.get("/api/prices/AMD?range=1D").status_code == 422


class TestPnlAndHoldings:
    def test_pnl_windows_use_the_latest_reading_old_enough(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        pnl = client.get("/api/dashboard").json()["pnl"]
        assert pnl["current_nav_usd"] == 12_000.0
        assert round(pnl["daily"]["usd"], 2) == 200.0  # vs 2 days ago (the nearest reading >= 1 day old)
        assert round(pnl["weekly"]["usd"], 2) == 1_000.0  # vs 8 days ago
        assert round(pnl["monthly"]["usd"], 2) == 2_000.0 and round(pnl["monthly"]["pct"], 1) == 20.0
        assert len(pnl["series"]) == 4

    def test_pnl_window_is_null_when_history_is_too_short(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        session = sf()
        for s_ in session.execute(select_all_snapshots()).scalars():
            if (NOW - s_.recorded_at).days >= 8:
                session.delete(s_)
        session.commit(); session.close()
        pnl = client.get("/api/dashboard").json()["pnl"]
        assert pnl["daily"] is not None and pnl["weekly"] is None and pnl["monthly"] is None

    def test_holdings_carry_action_name_and_plan(self, tmp_path):
        client, sf, data_dir = make_client(tmp_path)
        seed(sf, data_dir)
        body = client.get("/api/dashboard").json()
        (amd,) = body["holdings"]
        assert amd["name"] == "Advanced Micro Devices, Inc." and amd["action"] == "TRIM" and amd["qty"] == 3.5
        assert body["setups"][0]["name"] == "Advanced Micro Devices, Inc."
        assert body["setups"][1]["name"] is None  # DELL has no cached profile: no name, not a guess
        assert "AMD" in body["plans"] and "AMD" in body["insights"]


def select_all_snapshots():
    from sqlalchemy import select
    return select(NavSnapshot)
