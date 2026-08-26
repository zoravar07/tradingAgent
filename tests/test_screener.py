import pytest

from agents.screener import (
    ScreenerInput,
    Stage2Result,
    Stage2Verdict,
    evaluate_stage1,
    run_stage1,
    run_stage2_batch,
    run_stage2_triage,
    select_stage2_survivors,
    select_survivors,
)
from core.config import Stage1Config, Stage2Config
from core.llm import LLMClient, MonthlySpendTracker
from sources.prices import TechnicalSnapshot
from tests.test_llm import FakeClient, FakeResponse


def snapshot(**overrides) -> TechnicalSnapshot:
    base = dict(
        last_price=100.0,
        sma_50=95.0,
        sma_200=90.0,
        price_vs_sma_50_pct=5.0,
        price_vs_sma_200_pct=11.0,
        atr_14=2.0,
        atr_pct_of_price=2.0,
        atr_percentile_252d=50.0,
        relative_strength_vs_spy_pct=3.0,
        relative_strength_vs_sector_pct=1.0,
    )
    base.update(overrides)
    return TechnicalSnapshot(**base)


def candidate(ticker="AMD", **overrides) -> ScreenerInput:
    base = dict(
        ticker=ticker,
        market_cap_usd=5_000_000_000,
        avg_daily_volume_usd=50_000_000,
        technical=snapshot(),
        trailing_pe=20.0,
        free_cash_flow=100_000_000,
        revenue_growth_pct=10.0,
        days_to_earnings=30,
        is_held=False,
    )
    base.update(overrides)
    return ScreenerInput(**base)


DEFAULT_CONFIG = Stage1Config()


class TestLiquidityGate:
    def test_passes_with_sufficient_liquidity(self):
        result = evaluate_stage1(candidate(), DEFAULT_CONFIG)
        assert result.gates.liquidity_pass is True

    def test_fails_below_market_cap_floor(self):
        result = evaluate_stage1(candidate(market_cap_usd=500_000_000), DEFAULT_CONFIG)
        assert result.gates.liquidity_pass is False
        assert result.passed is False
        assert "market cap below floor" in result.reasons

    def test_fails_below_volume_floor(self):
        result = evaluate_stage1(candidate(avg_daily_volume_usd=1_000_000), DEFAULT_CONFIG)
        assert result.gates.liquidity_pass is False
        assert "avg daily volume below floor" in result.reasons

    def test_missing_market_cap_fails_gate(self):
        result = evaluate_stage1(candidate(market_cap_usd=None), DEFAULT_CONFIG)
        assert result.gates.liquidity_pass is False


class TestFundamentalFloor:
    def test_passes_on_positive_fcf_alone(self):
        result = evaluate_stage1(candidate(free_cash_flow=1, revenue_growth_pct=-10), DEFAULT_CONFIG)
        assert result.gates.fundamental_floor_pass is True

    def test_passes_on_growth_alone(self):
        result = evaluate_stage1(candidate(free_cash_flow=-1, revenue_growth_pct=20), DEFAULT_CONFIG)
        assert result.gates.fundamental_floor_pass is True

    def test_fails_on_neither(self):
        result = evaluate_stage1(candidate(free_cash_flow=-1, revenue_growth_pct=1), DEFAULT_CONFIG)
        assert result.gates.fundamental_floor_pass is False
        assert result.passed is False

    def test_growth_exactly_at_threshold_passes(self):
        result = evaluate_stage1(
            candidate(free_cash_flow=-1, revenue_growth_pct=DEFAULT_CONFIG.min_revenue_growth_pct), DEFAULT_CONFIG
        )
        assert result.gates.fundamental_floor_pass is True

    def test_etf_exempt_with_no_fundamentals_data_at_all(self):
        # regression test: VGT/IAU/VTI have no income statement in either
        # data source — this must be an exemption, not the same failure as
        # a company with genuinely bad fundamentals
        result = evaluate_stage1(
            candidate(is_etf=True, free_cash_flow=None, revenue_growth_pct=None), DEFAULT_CONFIG
        )
        assert result.gates.fundamental_floor_pass is True
        assert result.passed is True
        assert "ETF — fundamental floor not applicable" in result.reasons

    def test_etf_flag_does_not_affect_liquidity_gate(self):
        result = evaluate_stage1(
            candidate(is_etf=True, market_cap_usd=None, free_cash_flow=None, revenue_growth_pct=None), DEFAULT_CONFIG
        )
        assert result.gates.liquidity_pass is False
        assert result.passed is False  # ETF exemption is fundamentals-only, not a blanket pass


class TestValuationBand:
    def test_cheap(self):
        result = evaluate_stage1(candidate(trailing_pe=10), DEFAULT_CONFIG)
        assert result.gates.valuation_band == "cheap"

    def test_fair(self):
        result = evaluate_stage1(candidate(trailing_pe=20), DEFAULT_CONFIG)
        assert result.gates.valuation_band == "fair"

    def test_expensive(self):
        result = evaluate_stage1(candidate(trailing_pe=45), DEFAULT_CONFIG)
        assert result.gates.valuation_band == "expensive"

    def test_unknown_when_pe_missing_or_negative(self):
        assert evaluate_stage1(candidate(trailing_pe=None), DEFAULT_CONFIG).gates.valuation_band == "unknown"
        assert evaluate_stage1(candidate(trailing_pe=-5), DEFAULT_CONFIG).gates.valuation_band == "unknown"

    def test_valuation_never_excludes(self):
        # absurdly expensive but otherwise clean — still passes
        result = evaluate_stage1(candidate(trailing_pe=500), DEFAULT_CONFIG)
        assert result.passed is True


class TestEarningsProximity:
    def test_flagged_within_window(self):
        result = evaluate_stage1(candidate(days_to_earnings=2), DEFAULT_CONFIG)
        assert result.gates.earnings_soon is True

    def test_not_flagged_outside_window(self):
        result = evaluate_stage1(candidate(days_to_earnings=30), DEFAULT_CONFIG)
        assert result.gates.earnings_soon is False

    def test_earnings_proximity_never_excludes(self):
        result = evaluate_stage1(candidate(days_to_earnings=0), DEFAULT_CONFIG)
        assert result.passed is True

    def test_unknown_earnings_date_not_flagged(self):
        result = evaluate_stage1(candidate(days_to_earnings=None), DEFAULT_CONFIG)
        assert result.gates.earnings_soon is False


class TestHeldOverride:
    def test_held_position_survives_failed_liquidity(self):
        result = evaluate_stage1(candidate(is_held=True, market_cap_usd=100_000_000), DEFAULT_CONFIG)
        assert result.passed is True
        assert result.held_override is True
        assert "held — included despite failing gates" in result.reasons
        assert result.gates.liquidity_pass is False  # true gate result preserved, not laundered

    def test_held_position_passing_naturally_has_no_override_flag(self):
        result = evaluate_stage1(candidate(is_held=True), DEFAULT_CONFIG)
        assert result.passed is True
        assert result.held_override is False

    def test_non_held_failing_position_excluded(self):
        result = evaluate_stage1(candidate(is_held=False, market_cap_usd=100_000_000), DEFAULT_CONFIG)
        assert result.passed is False
        assert result.held_override is False


class TestRunStage1:
    def test_returns_one_result_per_input(self):
        items = [candidate("AMD"), candidate("NVDA"), candidate("BADCO", market_cap_usd=1_000)]
        results = run_stage1(items, DEFAULT_CONFIG)
        assert [r.ticker for r in results] == ["AMD", "NVDA", "BADCO"]
        assert results[2].passed is False


class TestSelectSurvivors:
    def test_held_always_included_on_top_of_cap(self):
        config = Stage1Config(max_survivors=1)
        items = [
            candidate("HELD", is_held=True, market_cap_usd=100),  # fails gates but held
            candidate("A", technical=snapshot(relative_strength_vs_spy_pct=10)),
            candidate("B", technical=snapshot(relative_strength_vs_spy_pct=5)),
        ]
        results = run_stage1(items, config)
        survivors = select_survivors(results, config)
        tickers = {r.ticker for r in survivors}
        assert "HELD" in tickers
        assert "A" in tickers  # higher relative strength wins the 1-slot cap
        assert "B" not in tickers
        assert len(survivors) == 2

    def test_ranking_prefers_higher_relative_strength(self):
        config = Stage1Config(max_survivors=2)
        items = [
            candidate("LOW", technical=snapshot(relative_strength_vs_spy_pct=-5)),
            candidate("MID", technical=snapshot(relative_strength_vs_spy_pct=2)),
            candidate("HIGH", technical=snapshot(relative_strength_vs_spy_pct=8)),
        ]
        survivors = select_survivors(run_stage1(items, config), config)
        assert [r.ticker for r in survivors] == ["HIGH", "MID"]

    def test_falls_back_to_price_vs_sma_200_when_rs_missing(self):
        config = Stage1Config(max_survivors=1)
        items = [
            candidate("A", technical=snapshot(relative_strength_vs_spy_pct=None, price_vs_sma_200_pct=1.0)),
            candidate("B", technical=snapshot(relative_strength_vs_spy_pct=None, price_vs_sma_200_pct=9.0)),
        ]
        survivors = select_survivors(run_stage1(items, config), config)
        assert [r.ticker for r in survivors] == ["B"]

    def test_failed_non_held_never_survive(self):
        config = Stage1Config(max_survivors=10)
        items = [candidate("BAD", market_cap_usd=100)]
        survivors = select_survivors(run_stage1(items, config), config)
        assert survivors == []


# -------------------------------------------------------------------- Stage 2

STAGE2_CONFIG = Stage2Config()


def make_llm(tmp_path, script):
    return LLMClient(FakeClient(script), MonthlySpendTracker(tmp_path / "spend.json", 40.0, month_fn=lambda: "2026-08"))


def stage1_result_for(ticker, is_held=False, rank_score=5.0):
    items = [candidate(ticker, is_held=is_held, technical=snapshot(relative_strength_vs_spy_pct=rank_score))]
    return run_stage1(items, DEFAULT_CONFIG)[0]


class TestRunStage2Triage:
    def test_material_verdict_passes_non_held(self, tmp_path):
        llm = make_llm(tmp_path, [FakeResponse(parsed_output=Stage2Verdict(verdict="new contract win", material=True))])
        result = run_stage2_triage(llm, stage1_result_for("AMD"), STAGE2_CONFIG)
        assert result.passed is True
        assert result.material is True
        assert result.ok is True

    def test_non_material_verdict_fails_non_held(self, tmp_path):
        llm = make_llm(tmp_path, [FakeResponse(parsed_output=Stage2Verdict(verdict="nothing new", material=False))])
        result = run_stage2_triage(llm, stage1_result_for("AMD"), STAGE2_CONFIG)
        assert result.passed is False

    def test_held_position_passes_regardless_of_verdict(self, tmp_path):
        llm = make_llm(tmp_path, [FakeResponse(parsed_output=Stage2Verdict(verdict="nothing new", material=False))])
        result = run_stage2_triage(llm, stage1_result_for("AMD", is_held=True), STAGE2_CONFIG)
        assert result.passed is True

    def test_llm_failure_does_not_raise(self, tmp_path):
        llm = make_llm(tmp_path, [RuntimeError("api down"), RuntimeError("still down"), RuntimeError("still down")])
        result = run_stage2_triage(llm, stage1_result_for("AMD"), STAGE2_CONFIG)
        assert result.ok is False
        assert "api down" in result.error or "still down" in result.error
        assert result.passed is False  # non-held, failed triage -> dropped

    def test_llm_failure_on_held_position_still_passes(self, tmp_path):
        llm = make_llm(tmp_path, [RuntimeError("api down"), RuntimeError("x"), RuntimeError("x")])
        result = run_stage2_triage(llm, stage1_result_for("AMD", is_held=True), STAGE2_CONFIG)
        assert result.ok is False
        assert result.passed is True  # held positions always enter the pipeline (§5)


class TestRunStage2Batch:
    def test_one_call_per_candidate(self, tmp_path):
        results = [
            stage1_result_for("AMD"),
            stage1_result_for("NVDA"),
        ]
        llm = make_llm(
            tmp_path,
            [
                FakeResponse(parsed_output=Stage2Verdict(verdict="a", material=True)),
                FakeResponse(parsed_output=Stage2Verdict(verdict="b", material=False)),
            ],
        )
        batch = run_stage2_batch(llm, results, STAGE2_CONFIG)
        assert [r.ticker for r in batch] == ["AMD", "NVDA"]


class TestSelectStage2Survivors:
    def test_held_always_included(self, tmp_path):
        config = Stage2Config(max_survivors=0)
        s1_held = stage1_result_for("HELD", is_held=True)
        results = [Stage2Result(ticker="HELD", verdict="", material=False, passed=True, is_held=True)]
        survivors = select_stage2_survivors(results, {"HELD": s1_held}, config)
        assert [r.ticker for r in survivors] == ["HELD"]

    def test_trims_material_candidates_by_stage1_rank(self, tmp_path):
        config = Stage2Config(max_survivors=1)
        s1_low = stage1_result_for("LOW", rank_score=1.0)
        s1_high = stage1_result_for("HIGH", rank_score=9.0)
        results = [
            Stage2Result(ticker="LOW", verdict="", material=True, passed=True, is_held=False),
            Stage2Result(ticker="HIGH", verdict="", material=True, passed=True, is_held=False),
        ]
        survivors = select_stage2_survivors(results, {"LOW": s1_low, "HIGH": s1_high}, config)
        assert [r.ticker for r in survivors] == ["HIGH"]

    def test_non_material_excluded_even_within_cap(self, tmp_path):
        config = Stage2Config(max_survivors=10)
        s1 = stage1_result_for("AMD")
        results = [Stage2Result(ticker="AMD", verdict="", material=False, passed=False, is_held=False)]
        survivors = select_stage2_survivors(results, {"AMD": s1}, config)
        assert survivors == []
