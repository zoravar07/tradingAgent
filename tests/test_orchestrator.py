"""Orchestrator integration test — one full nightly run through fakes for
the FMP gateway and the Anthropic client. No network, no real API spend.
Verifies wiring/sequencing/persistence, not the pure logic inside each stage
(that's covered by test_screener.py / test_scoring.py / test_risk_rules.py /
test_order_builder.py / test_briefing.py already).
"""

import datetime as dt

from sqlalchemy import select

from agents.research import BearCase, Catalyst, ResearchMemo
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
from core.models import Candidate, Conviction, Proposal, ResearchOutput, Run
from core.orchestrator import NightlyRunInputs, build_universe, run_nightly
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
    base = {name: subscore for name in CONVICTION_WEIGHTS}
    base.update(
        consensus_view="consensus", variant_view="variant",
        bear_case=BearCase(thesis="bear thesis", estimated_downside_pct=25),
        catalysts=[Catalyst(description="cat", expected_date=None)],
        key_risks=["risk"], thesis_summary="summary",
    )
    base.update(overrides)
    return ResearchMemo(**base)


class FakeGateway:
    def __init__(self, inputs: dict, prices: dict, sectors: dict = None, clusters: dict = None, contexts: dict = None):
        self.inputs = inputs
        self.prices = prices
        self.sectors = sectors or {}
        self.clusters = clusters or {}
        self.contexts = contexts or {}

    def get_screener_input(self, ticker, is_held):
        return self.inputs[ticker]

    def get_research_context(self, ticker):
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
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(sp500_tickers=["AMD", "NVDA", "BADCO"], watchlist=[], held_tickers=["NBIS"]),
            held_tickers=["NBIS"],
            nav_usd=100_000,
            cash_available_usd=50_000,
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

    def test_kill_switch_blocks_new_buys_but_not_exits(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NBIS", qty=8, avg_cost=218.0, opened_at=dt.datetime(2026, 7, 1), conviction_at_entry=68.0)

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
        run_inputs = NightlyRunInputs(
            as_of=dt.datetime(2026, 8, 25, 22, 0, 0),
            universe_tickers=build_universe(["AMD"], [], ["NBIS"]),
            held_tickers=["NBIS"],
            nav_usd=100_000,
            cash_available_usd=50_000,
            daily_loss_pct=10.0,  # above max_daily_loss_pct -> kill switch triggers
        )

        briefing = run_nightly(session=session, config=config, gateway=gateway, llm=llm, portfolio=portfolio, inputs=run_inputs)

        proposals = {p.ticker: p for p in session.execute(select(Proposal)).scalars()}
        assert "AMD" not in proposals  # kill switch blocked the new BUY
        assert "NBIS" in proposals  # but the thesis-decay exit still went through
        assert proposals["NBIS"].action == "SELL"
