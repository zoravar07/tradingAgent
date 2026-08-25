import pytest

from agents.screener import ScreenerInput, evaluate_stage1, run_stage1, select_survivors
from core.config import Stage1Config
from sources.prices import TechnicalSnapshot


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
