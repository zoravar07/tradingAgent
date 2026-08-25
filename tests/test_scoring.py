import pytest

from core.scoring import ScoringError, compute_conviction, normalize_weights


class TestNormalizeWeights:
    def test_normalizes_to_sum_one(self):
        result = normalize_weights({"a": 0.2, "b": 0.2}, present={"a", "b"})
        assert result["a"] == pytest.approx(0.5)
        assert result["b"] == pytest.approx(0.5)

    def test_excludes_zero_weights(self):
        result = normalize_weights({"a": 0.5, "b": 0.0}, present={"a", "b"})
        assert result == {"a": 1.0}

    def test_excludes_weights_missing_from_present(self):
        result = normalize_weights({"a": 0.5, "b": 0.5}, present={"a"})
        assert result == {"a": 1.0}

    def test_excludes_named_penalty_factors(self):
        result = normalize_weights({"a": 0.5, "portfolio_fit": 0.5}, present={"a", "portfolio_fit"}, exclude={"portfolio_fit"})
        assert result == {"a": 1.0}

    def test_empty_when_nothing_active(self):
        assert normalize_weights({}, present=set()) == {}
        assert normalize_weights({"a": 0.0}, present={"a"}) == {}


class TestComputeConviction:
    def test_single_factor_full_weight_equals_its_subscore(self):
        result = compute_conviction(subscores={"business_quality": 80}, weights={"business_quality": 1.0})
        assert result.score == pytest.approx(80.0)

    def test_two_equal_weighted_factors_average(self):
        result = compute_conviction(
            subscores={"business_quality": 80, "financial_health": 40},
            weights={"business_quality": 0.5, "financial_health": 0.5},
        )
        assert result.score == pytest.approx(60.0)

    def test_weights_auto_normalize_regardless_of_absolute_scale(self):
        # weights sum to 0.25 total, not 1.0 — still averages correctly
        result = compute_conviction(
            subscores={"a": 100, "b": 0},
            weights={"a": 0.1, "b": 0.15},
        )
        # a gets 0.1/0.25 = 0.4 weight, b gets 0.6 -> 100*0.4 + 0*0.6 = 40
        assert result.score == pytest.approx(40.0)

    def test_subscore_with_no_configured_weight_is_ignored(self):
        result = compute_conviction(
            subscores={"business_quality": 80, "some_untracked_factor": 0},
            weights={"business_quality": 1.0},
        )
        assert result.score == pytest.approx(80.0)
        assert "some_untracked_factor" not in result.contributions

    def test_configured_weight_with_missing_subscore_excluded_not_zeroed(self):
        # if it were treated as 0, score would be 40; excluding it entirely -> 80
        result = compute_conviction(
            subscores={"business_quality": 80},
            weights={"business_quality": 0.5, "financial_health": 0.5},
        )
        assert result.score == pytest.approx(80.0)
        assert result.missing_factors == ["financial_health"]

    def test_zero_weight_factor_never_flagged_as_missing(self):
        result = compute_conviction(subscores={"a": 80}, weights={"a": 1.0, "discord_signal": 0.0})
        assert result.missing_factors == []

    def test_portfolio_fit_excluded_from_rollup_applied_as_penalty(self):
        result = compute_conviction(
            subscores={"business_quality": 80, "portfolio_fit": 60},
            weights={"business_quality": 1.0, "portfolio_fit": 0.2},
        )
        assert result.base_score == pytest.approx(80.0)  # portfolio_fit didn't dilute the rollup
        assert result.penalty == pytest.approx(12.0)  # 0.2 * 60
        assert result.score == pytest.approx(68.0)

    def test_portfolio_fit_zero_weight_applies_no_penalty(self):
        result = compute_conviction(
            subscores={"business_quality": 80, "portfolio_fit": 90},
            weights={"business_quality": 1.0, "portfolio_fit": 0.0},
        )
        assert result.penalty == 0.0
        assert result.score == pytest.approx(80.0)

    def test_score_never_goes_below_zero(self):
        result = compute_conviction(
            subscores={"business_quality": 10, "portfolio_fit": 100},
            weights={"business_quality": 1.0, "portfolio_fit": 1.0},
        )
        assert result.score == 0.0

    def test_all_weights_missing_or_zero_yields_zero_score(self):
        result = compute_conviction(subscores={"business_quality": 80}, weights={"financial_health": 0.5})
        assert result.score == 0.0
        assert result.base_score == 0.0

    def test_derivation_contains_expected_keys(self):
        result = compute_conviction(subscores={"a": 80}, weights={"a": 1.0})
        derivation = result.derivation()
        assert set(derivation) == {"base_score", "penalty", "final_score", "contributions", "missing_factors"}

    def test_rejects_out_of_range_subscore(self):
        with pytest.raises(ScoringError):
            compute_conviction(subscores={"a": 150}, weights={"a": 1.0})

    def test_rejects_negative_subscore(self):
        with pytest.raises(ScoringError):
            compute_conviction(subscores={"a": -1}, weights={"a": 1.0})

    def test_rejects_non_numeric_subscore(self):
        with pytest.raises(ScoringError):
            compute_conviction(subscores={"a": "high"}, weights={"a": 1.0})

    def test_rejects_negative_weight(self):
        with pytest.raises(ScoringError):
            compute_conviction(subscores={"a": 80}, weights={"a": -0.5})

    def test_realistic_full_weight_set_from_spec(self):
        # §9's default conviction_weights, all factors present
        weights = {
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
            "portfolio_fit": 0.00,
            "discord_signal": 0.00,
        }
        subscores = {name: 70.0 for name in weights if name not in ("portfolio_fit", "discord_signal")}
        result = compute_conviction(subscores, weights)
        assert result.score == pytest.approx(70.0)
