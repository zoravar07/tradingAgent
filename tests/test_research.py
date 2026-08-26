"""Research Agent tests — same fake-Anthropic-client pattern as test_llm.py
and the Stage 2 tests. No test here may call a real API or spend real money."""

import pytest

from agents.research import (
    BearCase,
    Catalyst,
    RESEARCH_SUBSCORE_NAMES,
    ResearchContext,
    ResearchMemo,
    Subscore,
    run_research,
    run_research_batch,
)
from core.config import ResearchConfig
from core.llm import LLMClient, MonthlySpendTracker
from tests.test_llm import FakeClient, FakeResponse


def make_llm(tmp_path, script):
    return LLMClient(FakeClient(script), MonthlySpendTracker(tmp_path / "spend.json", 40.0, month_fn=lambda: "2026-08"))


def make_memo(**overrides) -> ResearchMemo:
    """Subscore fields accept a bare number (wrapped into an available
    Subscore) or None (wrapped into an unavailable one) for convenience —
    tests write `make_memo(ownership_flow=None)` to mark a factor as having
    no evidence, matching how the real schema expresses it."""
    subscore_defaults = dict(
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
    )
    fields: dict = {}
    for name, default in subscore_defaults.items():
        value = overrides.pop(name, default)
        fields[name] = Subscore(value=None, data_available=False) if value is None else Subscore(value=value, data_available=True)
    fields.update(
        consensus_view="Market sees this as a fairly priced compounder.",
        variant_view="We think margin expansion is underappreciated.",
        bear_case=BearCase(thesis="Demand softens if the macro rolls over", estimated_downside_pct=28),
        catalysts=[Catalyst(description="Q3 earnings", expected_date="2026-10-15")],
        key_risks=["Customer concentration in top 3 accounts"],
        thesis_summary="Underappreciated margin story with a dated catalyst.",
    )
    fields.update(overrides)
    return ResearchMemo(**fields)


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


class TestSubscoreAvailability:
    """The user's diagnosis: a factor with no evidence was defaulting to a
    hedged ~40-50 that got weighted into the roll-up as a real finding.
    These tests are the fix's actual contract — not just schema validation."""

    def test_data_available_true_requires_a_value(self):
        with pytest.raises(Exception):
            Subscore(value=None, data_available=True)

    def test_data_available_false_forbids_a_value(self):
        with pytest.raises(Exception):
            Subscore(value=50.0, data_available=False)

    def test_available_subscore_constructs_fine(self):
        s = Subscore(value=70.0, data_available=True)
        assert s.value == 70.0

    def test_unavailable_subscore_constructs_fine(self):
        s = Subscore(value=None, data_available=False)
        assert s.value is None

    def test_subscores_excludes_unavailable_factors(self):
        memo = make_memo(ownership_flow=None, catalyst_path=None)
        scores = memo.subscores()
        assert "ownership_flow" not in scores
        assert "catalyst_path" not in scores
        assert set(scores) == set(RESEARCH_SUBSCORE_NAMES) - {"ownership_flow", "catalyst_path"}

    def test_unavailable_factors_lists_exactly_the_flagged_ones(self):
        memo = make_memo(ownership_flow=None)
        assert memo.unavailable_factors() == ["ownership_flow"]

    def test_no_unavailable_factors_by_default(self):
        assert make_memo().unavailable_factors() == []

    def test_all_factors_unavailable_yields_empty_subscores(self):
        memo = make_memo(**{name: None for name in RESEARCH_SUBSCORE_NAMES})
        assert memo.subscores() == {}
        assert set(memo.unavailable_factors()) == set(RESEARCH_SUBSCORE_NAMES)

    def test_renormalization_excludes_unavailable_factor_not_zeros_it(self):
        # the actual point of the fix: verify against compute_conviction
        # directly, not just that subscores() drops the key
        from core.scoring import compute_conviction

        weights = {"business_quality": 0.5, "ownership_flow": 0.5}
        memo_with_gap = make_memo(business_quality=80, ownership_flow=None)
        result_with_gap = compute_conviction(memo_with_gap.subscores(), weights)
        # business_quality's weight absorbs ownership_flow's, so score == 80,
        # not (80*0.5 + <some fabricated middle>*0.5) which would land near 60
        assert result_with_gap.score == pytest.approx(80.0)
        assert result_with_gap.missing_factors == ["ownership_flow"]

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
