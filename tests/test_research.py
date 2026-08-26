"""Research Agent tests — same fake-Anthropic-client pattern as test_llm.py
and the Stage 2 tests. No test here may call a real API or spend real money."""

import pytest

from agents.research import (
    BearCase,
    Catalyst,
    RESEARCH_SUBSCORE_NAMES,
    ResearchContext,
    ResearchMemo,
    run_research,
    run_research_batch,
)
from core.config import ResearchConfig
from core.llm import LLMClient, MonthlySpendTracker
from tests.test_llm import FakeClient, FakeResponse


def make_llm(tmp_path, script):
    return LLMClient(FakeClient(script), MonthlySpendTracker(tmp_path / "spend.json", 40.0, month_fn=lambda: "2026-08"))


def make_memo(**overrides) -> ResearchMemo:
    base = dict(
        business_quality=70,
        financial_health=65,
        whats_priced_in=55,
        variant_perception=60,
        earnings_quality=68,
        catalyst_path=72,
        downside_asymmetry=40,
        ownership_flow=58,
        analyst_signals=62,
        news_sentiment=50,
        technical_momentum=66,
        consensus_view="Market sees this as a fairly priced compounder.",
        variant_view="We think margin expansion is underappreciated.",
        bear_case=BearCase(thesis="Demand softens if the macro rolls over", estimated_downside_pct=28),
        catalysts=[Catalyst(description="Q3 earnings", expected_date="2026-10-15")],
        key_risks=["Customer concentration in top 3 accounts"],
        thesis_summary="Underappreciated margin story with a dated catalyst.",
    )
    base.update(overrides)
    return ResearchMemo(**base)


CONFIG = ResearchConfig()


class TestResearchMemoSchema:
    def test_subscores_returns_expected_keys(self):
        memo = make_memo()
        assert set(memo.subscores()) == set(RESEARCH_SUBSCORE_NAMES)

    def test_portfolio_fit_and_discord_signal_not_in_schema(self):
        assert "portfolio_fit" not in ResearchMemo.model_fields
        assert "discord_signal" not in ResearchMemo.model_fields

    def test_rejects_out_of_range_subscore(self):
        with pytest.raises(Exception):
            make_memo(business_quality=150)

    def test_bear_case_downside_bounded(self):
        with pytest.raises(Exception):
            BearCase(thesis="x", estimated_downside_pct=-5)


class TestRunResearch:
    def test_successful_memo(self, tmp_path):
        llm = make_llm(tmp_path, [FakeResponse(parsed_output=make_memo())])
        result = run_research(llm, ResearchContext(ticker="AMD", context_text="some data"), CONFIG)

        assert result.ok is True
        assert result.memo.thesis_summary.startswith("Underappreciated")
        assert result.usage is not None
        assert result.usage.model == CONFIG.model

    def test_uses_configured_model(self, tmp_path):
        llm = make_llm(tmp_path, [FakeResponse(parsed_output=make_memo())])
        config = ResearchConfig(model="claude-sonnet-4-6")
        run_research(llm, ResearchContext(ticker="AMD", context_text="x"), config)
        assert llm.client.messages.calls[0]["model"] == "claude-sonnet-4-6"

    def test_llm_failure_does_not_raise(self, tmp_path):
        llm = make_llm(tmp_path, [RuntimeError("down"), RuntimeError("down"), RuntimeError("down")])
        result = run_research(llm, ResearchContext(ticker="AMD", context_text="x"), CONFIG)
        assert result.ok is False
        assert result.memo is None
        assert "down" in result.error

    def test_context_text_and_ticker_reach_the_prompt(self, tmp_path):
        llm = make_llm(tmp_path, [FakeResponse(parsed_output=make_memo())])
        run_research(llm, ResearchContext(ticker="NBIS", context_text="ATR percentile: 80"), CONFIG)
        sent = llm.client.messages.calls[0]["messages"][0]["content"]
        assert "NBIS" in sent
        assert "ATR percentile: 80" in sent


class TestRunResearchBatch:
    def test_one_call_per_context(self, tmp_path):
        llm = make_llm(tmp_path, [FakeResponse(parsed_output=make_memo()), FakeResponse(parsed_output=make_memo())])
        contexts = [ResearchContext("AMD", "x"), ResearchContext("NVDA", "y")]
        results = run_research_batch(llm, contexts, CONFIG)
        assert [r.ticker for r in results] == ["AMD", "NVDA"]
        assert all(r.ok for r in results)

    def test_one_failure_does_not_lose_the_rest(self, tmp_path):
        llm = make_llm(
            tmp_path,
            [
                FakeResponse(parsed_output=make_memo()),
                RuntimeError("boom"),
                RuntimeError("boom"),
                RuntimeError("boom"),
                FakeResponse(parsed_output=make_memo()),
            ],
        )
        contexts = [ResearchContext("AMD", "x"), ResearchContext("BAD", "y"), ResearchContext("NVDA", "z")]
        results = run_research_batch(llm, contexts, CONFIG)
        assert [r.ok for r in results] == [True, False, True]
