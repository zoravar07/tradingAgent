"""Orchestrator integration test — one full nightly run through fakes for
the FMP gateway and the Anthropic client. No network, no real API spend.
Verifies wiring/sequencing/persistence, not the pure logic inside each stage
(that's covered by test_screener.py / test_scoring.py / test_risk_rules.py /
test_order_builder.py / test_briefing.py already).
"""

import datetime as dt
import json

import pytest
from sqlalchemy import select

from agents.research import BearCase, Catalyst, ResearchMemo, Subscore
from agents.screener import ScreenerInput, Stage2Verdict
from core.config import (
    Config,
    ConvictionScalingConfig,
    OrderBuilderConfig,
    RiskConfig,
    ScreenerConfig,
    Stage1Config,
    Stage2Config,
)
from core.llm import LLMClient, MonthlySpendTracker
from core.models import Candidate, Conviction, NavSnapshot, Proposal, ResearchOutput, Run
from core.money import usd
from core.config import UniverseConfig, WeeklyWideScanConfig
from core.orchestrator import NightlyRunInputs, build_universe, resolve_universe, rotating_slice, run_nightly
from sources.prices import TechnicalSnapshot
from tests.test_llm import FakeClient, FakeResponse

CONVICTION_WEIGHTS = {
    "business_quality": 0.15,
    "financial_health": 0.10,
    "whats_priced_in": 0.15,
    "variant_perception": 0.10,
    "earnings_quality": 0.10,
    "catalyst_path": 0.08,
    "downside_asymmetry": 0.10,
    "ownership_flow": 0.07,
    "analyst_signals": 0.05,
    "news_sentiment": 0.03,
    "technical_momentum": 0.07,
}


def technical(**overrides) -> TechnicalSnapshot:
    base = dict(
        last_price=100.0, sma_50=95.0, sma_200=90.0, price_vs_sma_50_pct=5.0, price_vs_sma_200_pct=10.0,
        atr_14=3.0, atr_pct_of_price=3.0, atr_percentile_252d=50.0,
        relative_strength_vs_spy_pct=0.0, relative_strength_vs_sector_pct=0.0,
    )
    base.update(overrides)
    return TechnicalSnapshot(**base)


def screener_input(ticker, is_held=False, market_cap_usd=5_000_000_000, adv=50_000_000, **overrides):
    tech = overrides.pop("technical", technical())
    return ScreenerInput(
        ticker=ticker, market_cap_usd=market_cap_usd, avg_daily_volume_usd=adv, technical=tech,
        trailing_pe=20.0, free_cash_flow=1.0, revenue_growth_pct=10.0, days_to_earnings=30, is_held=is_held,
        **overrides,
    )


def memo(**overrides) -> ResearchMemo:
    subscore = overrides.pop("subscore", 50.0)
    base = {name: Subscore(value=subscore, data_available=True) for name in CONVICTION_WEIGHTS}
    for name in CONVICTION_WEIGHTS:
        if name in overrides:
            value = overrides.pop(name)
            base[name] = Subscore(value=None, data_available=False) if value is None else Subscore(value=value, data_available=True)
    base.update(
        consensus_view="consensus", variant_view="variant",
        bear_case=BearCase(thesis="bear thesis", estimated_downside_pct=25),
        catalysts=[Catalyst(description="cat", expected_date=None)],
        key_risks=["risk"], thesis_summary="summary",
    )
    base.update(overrides)
    return ResearchMemo(**base)


class FakeGateway:
    def __init__(self, inputs: dict, prices: dict, sectors: dict = None, clusters: dict = None, contexts: dict = None, context_failures: set = None):
        self.inputs = inputs
        self.prices = prices
        self.sectors = sectors or {}
        self.clusters = clusters or {}
        self.contexts = contexts or {}
        self.context_failures = context_failures or set()

    def get_screener_input(self, ticker, is_held):
        return self.inputs[ticker]

    def get_research_context(self, ticker):
        if ticker in self.context_failures:
            raise RuntimeError(f"data fetch failed for {ticker}")
        return self.contexts.get(ticker, f"context for {ticker}")

    def get_current_price(self, ticker):
        return self.prices[ticker]

    def get_sector(self, ticker):
        return self.sectors.get(ticker)

    def get_cluster(self, ticker):
        return self.clusters.get(ticker)


def make_config() -> Config:
    return Config(
        conviction_weights=CONVICTION_WEIGHTS,
        screener=ScreenerConfig(stage1=Stage1Config(max_survivors=10), stage2=Stage2Config(max_survivors=10)),
        risk=RiskConfig(),
        conviction_scaling=ConvictionScalingConfig(),
        order_builder=OrderBuilderConfig(),
    )


def make_llm(tmp_path, script):
    return LLMClient(FakeClient(script), MonthlySpendTracker(tmp_path / "spend.json", 40.0, month_fn=lambda: "2026-08"))


class TestBuildUniverse:
    def test_merges_and_dedupes(self):
        result = build_universe(held_tickers=["nbis"], watchlist=["AMD", "NBIS"], scan_tickers=["MSFT", "AMD"])
        assert result == ["NBIS", "AMD", "MSFT"]

    def test_held_positions_come_first(self):
        result = build_universe(held_tickers=["X"], watchlist=["A"], scan_tickers=["B"])
        assert result[0] == "X"


class TestRotatingSlice:
    def test_basic_slice(self):
        pool = ["A", "B", "C", "D", "E"]
        assert rotating_slice(pool, batch_size=2, day_index=0) == ["A", "B"]

    def test_rotates_on_day_index(self):
        pool = ["A", "B", "C", "D", "E"]
        assert rotating_slice(pool, batch_size=2, day_index=1) == ["C", "D"]

    def test_wraps_around_pool(self):
        pool = ["A", "B", "C", "D", "E"]
        assert rotating_slice(pool, batch_size=2, day_index=2) == ["E", "A"]

    def test_batch_size_larger_than_pool_returns_whole_pool(self):
        pool = ["A", "B"]
        assert set(rotating_slice(pool, batch_size=10, day_index=0)) == {"A", "B"}

    def test_empty_pool_returns_empty(self):
        assert rotating_slice([], batch_size=30, day_index=5) == []

    def test_full_pool_gets_covered_over_enough_days(self):
        pool = [f"T{i}" for i in range(100)]
        covered: set[str] = set()
        for day in range(100 // 10):
            covered.update(rotating_slice(pool, batch_size=10, day_index=day))
        assert covered == set(pool)


class TestResolveUniverse:
    def test_normal_day_uses_rotating_slice(self):
        pool = [f"T{i}" for i in range(50)]
        config = UniverseConfig(watchlist=["WATCH1"], rotating_scan_size=10)
        result = resolve_universe(held_tickers=["HELD1"], pool=pool, config=config, as_of=dt.datetime(2026, 8, 25))
        assert "HELD1" in result
        assert "WATCH1" in result
        assert len(result) == 12  # held(1) + watchlist(1) + rotating slice(10), none overlapping

    def test_wide_scan_day_uses_full_pool(self):
        pool = [f"T{i}" for i in range(50)]
        config = UniverseConfig(
            watchlist=[], rotating_scan_size=10, weekly_wide_scan=WeeklyWideScanConfig(enabled=True, day_of_week=1)
        )
        as_of = dt.datetime(2026, 8, 25)  # a Tuesday -> weekday() == 1
        assert as_of.weekday() == 1
        result = resolve_universe(held_tickers=[], pool=pool, config=config, as_of=as_of)
        assert set(result) == set(pool)

    def test_wide_scan_disabled_still_uses_rotating_slice(self):
        pool = [f"T{i}" for i in range(50)]
        config = UniverseConfig(watchlist=[], rotating_scan_size=10, weekly_wide_scan=WeeklyWideScanConfig(enabled=False))
        result = resolve_universe(held_tickers=[], pool=pool, config=config, as_of=dt.datetime(2026, 8, 25))
        assert len(result) == 10


class TestFullNightlyRun:
    def test_end_to_end(self, session, portfolio, tmp_path):
        # --- held position, matching §3's NBIS example
        portfolio.add_manual_position(
            "NBIS", qty=8, avg_cost=218.0, opened_at=dt.datetime(2026, 7, 1), conviction_at_entry=68.0
        )

        inputs_by_ticker = {
            "NBIS": screener_input("NBIS", is_held=True, technical=technical(atr_14=3.0, relative_strength_vs_spy_pct=0)),
            "AMD": screener_input("AMD", technical=technical(relative_strength_vs_spy_pct=10)),
            "NVDA": screener_input("NVDA", technical=technical(relative_strength_vs_spy_pct=5)),
            "BADCO": screener_input("BADCO", market_cap_usd=1_000, technical=technical(relative_strength_vs_spy_pct=2)),
        }
        gateway = FakeGateway(
            inputs=inputs_by_ticker,
            prices={"NBIS": 222.0, "AMD": 150.0, "NVDA": 100.0},
            sectors={"AMD": "Technology"},
            clusters={"AMD": "ai_semis"},
        )

        # call order: stage2 triage for stage1 survivors [NBIS(held), AMD, NVDA] (BADCO fails stage1, no call)
        # then research for stage2 survivors [NBIS(held, always), AMD(material)]
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="Guidance raised for FY", material=True)),  # NBIS
            FakeResponse(parsed_output=Stage2Verdict(verdict="New contract win", material=True)),  # AMD
            FakeResponse(parsed_output=Stage2Verdict(verdict="Nothing material", material=False)),  # NVDA
            FakeResponse(parsed_output=memo(subscore=40.0, thesis_summary="NBIS thesis decaying")),  # NBIS research
            FakeResponse(parsed_output=memo(subscore=80.0, thesis_summary="AMD strong thesis")),  # AMD research
        ]
        llm = make_llm(tmp_path, script)

        config = make_config()
        # NBIS position value (8 * $222 = $1,776) + this cash figure = $100,000 NAV,
        # chosen to keep the sizing math identical to the previous fixed-NAV test.
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS"], watchlist=[], scan_tickers=["AMD", "NVDA", "BADCO"]),
            held_tickers=["NBIS"],
            cash=usd(98_224.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        # --- run persisted as succeeded
        run_row = session.execute(select(Run)).scalar_one()
        assert run_row.status == "succeeded"
        assert run_row.finished_at is not None

        # --- every universe ticker got a Candidate row, even ones excluded early
        candidates = {c.ticker: c for c in session.execute(select(Candidate)).scalars()}
        assert set(candidates) == {"NBIS", "AMD", "NVDA", "BADCO"}
        assert candidates["BADCO"].stage1_passed is False
        assert candidates["NVDA"].stage1_passed is True
        assert candidates["NVDA"].stage2_passed is False
        assert candidates["NVDA"].stage2_material is False

        # --- only material, non-dropped names got a research memo
        research_tickers = {r.ticker for r in session.execute(select(ResearchOutput)).scalars()}
        assert research_tickers == {"NBIS", "AMD"}

        # --- conviction computed from uniform subscores * weights summing to 1.0
        conviction = {c.ticker: c.score for c in session.execute(select(Conviction)).scalars()}
        assert conviction["NBIS"] == 40.0
        assert conviction["AMD"] == 80.0

        # --- proposals: NBIS exits on thesis decay (68 -> 40, a 28pt drop), AMD gets a BUY
        proposals = {p.ticker: p for p in session.execute(select(Proposal)).scalars()}
        assert set(proposals) == {"NBIS", "AMD"}
        assert proposals["NBIS"].action == "SELL"
        assert proposals["NBIS"].quantity == 8  # full exit, not a profit-band trim
        assert proposals["NBIS"].trigger_type == "THESIS_DECAY"
        assert proposals["AMD"].action == "BUY"
        assert proposals["AMD"].quantity > 0
        assert proposals["AMD"].trigger_type is None

        # --- briefing: actions sorted by conviction (AMD 80 before NBIS 40)
        assert [a.order.ticker for a in briefing.actions_today] == ["AMD", "NBIS"]

        # --- briefing: watching surfaces the stage1 near-miss, not the stage2 drop
        assert [w.ticker for w in briefing.watching] == ["BADCO"]

        # --- briefing: overnight changes only for held + material (NBIS, not AMD)
        assert [c.ticker for c in briefing.overnight_changes] == ["NBIS"]
        assert briefing.overnight_changes[0].summary == "Guidance raised for FY"

        # --- briefing: book has the one held position, flagged for attention
        assert [b.ticker for b in briefing.book] == ["NBIS"]
        assert briefing.book[0].has_exit_trigger is True

        # --- LLM spend was tracked
        assert llm.budget.spent_this_month() > 0

        # --- NAV computed from positions + cash, sector/cluster from held book
        nav_row = session.execute(select(NavSnapshot)).scalar_one()
        assert nav_row.nav_usd == pytest.approx(100_000.0)  # 8*222 (NBIS) + 98,224 cash
        assert nav_row.drawdown_pct == 0.0  # first-ever snapshot
        assert briefing.portfolio_health.cash_pct == pytest.approx(98.224, abs=0.01)

        # --- the assembled briefing itself was persisted (§10 step 10 gap)
        from core.briefing_persistence import deserialize_briefing
        from core.models import BriefingRecord

        run_row = session.execute(select(Run)).scalar_one()
        record = session.execute(select(BriefingRecord).where(BriefingRecord.run_id == run_row.id)).scalar_one()
        stored = deserialize_briefing(record.briefing_json)
        assert stored["book"][0]["ticker"] == "NBIS"
        assert stored["actions_today"][0]["order"]["ticker"] == "AMD"

    def test_kill_switch_blocks_new_buys_but_not_exits(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=8, avg_cost=218.0, opened_at=dt.datetime(2026, 7, 1), conviction_at_entry=68.0)

        # Seed a prior NAV snapshot so record_nav has something to compare
        # against — daily_loss_pct/drawdown_pct are now derived, not passed
        # in, so triggering the kill switch means simulating an actual NAV
        # decline across two runs rather than overriding a field directly.
        prev_run = Run(started_at=dt.datetime(2026, 8, 24, 22, 0, 0), finished_at=dt.datetime(2026, 8, 24, 22, 5, 0), status="succeeded", config_snapshot_json="{}")
        session.add(prev_run)
        session.flush()
        session.add(NavSnapshot(run_id=prev_run.id, nav_usd=100_000.0, peak_nav_usd=100_000.0, drawdown_pct=0.0, daily_loss_pct=0.0, recorded_at=dt.datetime(2026, 8, 24, 22, 0, 0)))
        session.flush()

        inputs_by_ticker = {
            "NBIS": screener_input("NBIS", is_held=True),
            "AMD": screener_input("AMD", technical=technical(relative_strength_vs_spy_pct=10)),
        }
        gateway = FakeGateway(inputs=inputs_by_ticker, prices={"NBIS": 222.0, "AMD": 150.0})
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="x", material=True)),  # NBIS
            FakeResponse(parsed_output=Stage2Verdict(verdict="y", material=True)),  # AMD
            FakeResponse(parsed_output=memo(subscore=40.0)),  # NBIS research
            FakeResponse(parsed_output=memo(subscore=80.0)),  # AMD research
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        # NBIS value (8*222=1,776) + a small cash figure -> NAV of ~$10,000,
        # a ~90% drop from yesterday's $100,000 snapshot -> kill switch trips.
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS"], watchlist=[], scan_tickers=["AMD"]),
            held_tickers=["NBIS"],
            cash=usd(8_224.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        proposals = {p.ticker: p for p in session.execute(select(Proposal)).scalars()}
        assert "AMD" not in proposals  # kill switch blocked the new BUY
        assert "NBIS" in proposals  # but the thesis-decay exit still went through
        assert briefing.portfolio_health.kill_switch.triggered is True

    def test_one_ticker_context_fetch_failure_does_not_kill_the_run(self, session, portfolio, tmp_path):
        # A live-data lesson learned the hard way: a single ticker's data
        # fetch can fail for reasons unrelated to every other ticker (a
        # paywalled endpoint, a transient error). The run must still produce
        # a briefing for everything that succeeded.
        inputs_by_ticker = {
            "AMD": screener_input("AMD", technical=technical(relative_strength_vs_spy_pct=10)),
            "NVDA": screener_input("NVDA", technical=technical(relative_strength_vs_spy_pct=5)),
        }
        gateway = FakeGateway(
            inputs=inputs_by_ticker, prices={"AMD": 150.0, "NVDA": 100.0}, context_failures={"AMD"}
        )
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="a", material=True)),  # AMD
            FakeResponse(parsed_output=Stage2Verdict(verdict="b", material=True)),  # NVDA
            FakeResponse(parsed_output=memo(subscore=80.0)),  # NVDA research (AMD's context fetch failed first)
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=[], watchlist=[], scan_tickers=["AMD", "NVDA"]),
            held_tickers=[],
            cash=usd(100_000.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        run_row = session.execute(select(Run)).scalar_one()
        assert run_row.status == "succeeded"

        research_tickers = {r.ticker for r in session.execute(select(ResearchOutput)).scalars()}
        assert research_tickers == {"NVDA"}  # AMD dropped, NVDA still got researched

        assert [a.order.ticker for a in briefing.actions_today] == ["NVDA"]


class TestPricingGate:
    def test_unpriced_held_position_blocks_the_run_with_zero_tolerance(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=8, avg_cost=218.0, conviction_at_entry=68.0)
        portfolio.add_manual_position("AMD", qty=3, avg_cost=150.0)

        # NBIS has no price at all -> pricing gate must trip before anything else runs
        gateway = FakeGateway(inputs={}, prices={"AMD": 150.0})
        llm = make_llm(tmp_path, [])  # no LLM call should happen — script would error if one was attempted
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS", "AMD"], watchlist=[], scan_tickers=[]),
            held_tickers=["NBIS", "AMD"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert briefing.blocked is not None
        assert briefing.blocked.unpriced_positions[0].ticker == "NBIS"
        assert briefing.actions_today == []
        assert briefing.book == []

        run_row = session.execute(select(Run)).scalar_one()
        assert run_row.status == "blocked"

        # nothing downstream ran: no candidates, no research, no proposals, no NAV snapshot
        assert session.execute(select(Candidate)).first() is None
        assert session.execute(select(ResearchOutput)).first() is None
        assert session.execute(select(Proposal)).first() is None
        assert session.execute(select(NavSnapshot)).first() is None

        # the blocked briefing is persisted too (§10 step 10 gap) — the UI
        # must be able to surface today's block, not silently keep showing
        # the last succeeded run as if nothing happened.
        from core.briefing_persistence import deserialize_briefing
        from core.models import BriefingRecord

        record = session.execute(select(BriefingRecord).where(BriefingRecord.run_id == run_row.id)).scalar_one()
        stored = deserialize_briefing(record.briefing_json)
        assert stored["blocked"]["unpriced_positions"][0]["ticker"] == "NBIS"
        assert stored["book"] == []

    def test_all_positions_priced_runs_normally(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=8, avg_cost=218.0, conviction_at_entry=68.0)
        inputs_by_ticker = {"NBIS": screener_input("NBIS", is_held=True)}
        gateway = FakeGateway(inputs=inputs_by_ticker, prices={"NBIS": 222.0})
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="x", material=False)),
            FakeResponse(parsed_output=memo(subscore=50.0)),
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS"], watchlist=[], scan_tickers=[]),
            held_tickers=["NBIS"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert briefing.blocked is None
        run_row = session.execute(select(Run)).scalar_one()
        assert run_row.status == "succeeded"

    def test_tolerance_above_zero_lets_the_run_through(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=8, avg_cost=218.0, conviction_at_entry=68.0)
        portfolio.add_manual_position("AMD", qty=3, avg_cost=150.0)

        gateway = FakeGateway(inputs={"AMD": screener_input("AMD", is_held=True)}, prices={"AMD": 150.0})
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="x", material=False)),
            FakeResponse(parsed_output=memo(subscore=50.0)),
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        config.risk.max_unpriced_held_positions = 1  # tolerate the one NBIS pricing failure
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS", "AMD"], watchlist=[], scan_tickers=[]),
            held_tickers=["NBIS", "AMD"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert briefing.blocked is None
        run_row = session.execute(select(Run)).scalar_one()
        assert run_row.status == "succeeded"
        # AMD's value made it into NAV; NBIS (unpriced) silently didn't —
        # a tolerated failure still means NAV understates the true book
        assert [b.ticker for b in briefing.book] == ["AMD"]


class TestUnresearchedHoldings:
    def test_stage1_fetch_failure_flags_the_holding(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=4, avg_cost=192.0, conviction_at_entry=68.0)
        # no "NBIS" entry in inputs -> get_screener_input raises KeyError
        gateway = FakeGateway(inputs={}, prices={"NBIS": 222.0})
        llm = make_llm(tmp_path, [])
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS"], watchlist=[], scan_tickers=[]),
            held_tickers=["NBIS"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert [u.ticker for u in briefing.unresearched_holdings] == ["NBIS"]
        assert "Stage 1 data fetch failed" in briefing.unresearched_holdings[0].reason
        assert briefing.book[0].no_research_coverage is True

    def test_research_context_failure_flags_the_holding_and_suppresses_thesis_decay(self, session, portfolio, tmp_path):
        # A real conviction_at_entry (68) that WOULD read as thesis decay if
        # a fabricated "now" score were compared against it — this test
        # exists to keep that guarantee from silently regressing.
        portfolio.add_manual_position("NBIS", qty=4, avg_cost=192.0, conviction_at_entry=68.0)
        gateway = FakeGateway(
            inputs={"NBIS": screener_input("NBIS", is_held=True)},
            prices={"NBIS": 200.0},
            context_failures={"NBIS"},
        )
        script = [FakeResponse(parsed_output=Stage2Verdict(verdict="x", material=False))]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS"], watchlist=[], scan_tickers=[]),
            held_tickers=["NBIS"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert [u.ticker for u in briefing.unresearched_holdings] == ["NBIS"]
        assert "Research context fetch failed" in briefing.unresearched_holdings[0].reason
        assert briefing.book[0].no_research_coverage is True
        assert briefing.book[0].has_exit_trigger is False  # no thesis-decay fired despite conviction_at_entry=68

    def test_banner_and_flag_absent_when_research_succeeds(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=4, avg_cost=192.0, conviction_at_entry=68.0)
        gateway = FakeGateway(inputs={"NBIS": screener_input("NBIS", is_held=True)}, prices={"NBIS": 200.0})
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="x", material=False)),
            FakeResponse(parsed_output=memo(subscore=60.0)),
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS"], watchlist=[], scan_tickers=[]),
            held_tickers=["NBIS"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert briefing.unresearched_holdings == []
        assert briefing.book[0].no_research_coverage is False


class TestConvictionFloorIntegration:
    def test_low_conviction_held_position_gets_an_exit_proposal(self, session, portfolio, tmp_path):
        # reproduces the exact live-run gap: RKLB, no entry baseline, price
        # essentially flat since purchase — nothing else would ever fire
        portfolio.add_manual_position("RKLB", qty=3, avg_cost=120.0, conviction_at_entry=None)
        gateway = FakeGateway(
            inputs={"RKLB": screener_input("RKLB", technical=technical(atr_14=2.0))},
            prices={"RKLB": 122.0},  # up slightly, nowhere near a profit band
        )
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="weak", material=True)),
            FakeResponse(parsed_output=memo(subscore=36.4, thesis_summary="accelerating cash burn")),
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["RKLB"], watchlist=[], scan_tickers=[]),
            held_tickers=["RKLB"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        proposals = {p.ticker: p for p in session.execute(select(Proposal)).scalars()}
        assert "RKLB" in proposals
        assert proposals["RKLB"].action == "SELL"
        assert proposals["RKLB"].trigger_type == "CONVICTION_FLOOR"
        assert [a.order.ticker for a in briefing.actions_today] == ["RKLB"]
        assert briefing.actions_today[0].headline.startswith("Conviction below floor")

    def test_conviction_at_or_above_floor_gets_no_proposal(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("RKLB", qty=3, avg_cost=120.0, conviction_at_entry=None)
        gateway = FakeGateway(
            inputs={"RKLB": screener_input("RKLB", technical=technical(atr_14=2.0))},
            prices={"RKLB": 122.0},
        )
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="ok", material=True)),
            FakeResponse(parsed_output=memo(subscore=40.0)),  # exactly at the floor
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["RKLB"], watchlist=[], scan_tickers=[]),
            held_tickers=["RKLB"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert briefing.actions_today == []


class TestEtfExemption:
    def test_held_etf_gets_researched_normally_no_false_banner(self, session, portfolio, tmp_path):
        # regression test: VGT (etc.) has no fundamentals in either source,
        # but is_etf=True must make it flow through the pipeline like any
        # other held position, not land in unresearched_holdings
        portfolio.add_manual_position("VGT", qty=14, avg_cost=95.0)
        gateway = FakeGateway(
            inputs={"VGT": screener_input("VGT", is_held=True, is_etf=True)},
            prices={"VGT": 117.0},
        )
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="etf, no news", material=False)),
            FakeResponse(parsed_output=memo(subscore=55.0)),
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["VGT"], watchlist=[], scan_tickers=[]),
            held_tickers=["VGT"],
            cash=usd(100.0),
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        assert briefing.unresearched_holdings == []
        assert briefing.book[0].no_research_coverage is False
        assert briefing.book[0].conviction_now == 55.0


class TestUnavailableFactorsPersistence:
    def test_memos_unavailable_factors_land_in_research_output_reasoning_json(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=4, avg_cost=192.0, conviction_at_entry=68.0)
        gateway = FakeGateway(inputs={"NBIS": screener_input("NBIS", is_held=True)}, prices={"NBIS": 200.0})
        script = [
            FakeResponse(parsed_output=Stage2Verdict(verdict="x", material=False)),
            FakeResponse(parsed_output=memo(subscore=60.0, ownership_flow=None, catalyst_path=None)),
        ]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(held_tickers=["NBIS"], watchlist=[], scan_tickers=[]),
            held_tickers=["NBIS"],
            cash=usd(100.0),
        )

        run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        research_output = session.execute(select(ResearchOutput)).scalar_one()
        reasoning = json.loads(research_output.reasoning_json)
        assert set(reasoning["unavailable_factors"]) == {"ownership_flow", "catalyst_path"}
        subscores = json.loads(research_output.subscores_json)
        assert "ownership_flow" not in subscores
        assert "catalyst_path" not in subscores
