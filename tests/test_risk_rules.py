import pytest

from core.config import ConvictionScalingConfig, RiskConfig
from core.risk_rules import (
    ScoredProposal,
    check_kill_switches,
    enforce_daily_proposal_cap,
    evaluate_held_position,
    lerp_by_conviction,
    profit_band_crossed,
    size_new_position,
    thesis_decay_triggered,
    trailing_stop_breached,
    update_peak_price,
    volatility_size_multiplier,
)

RISK = RiskConfig()
SCALING = ConvictionScalingConfig()


class TestLerpByConviction:
    def test_zero_conviction_gives_at_0(self):
        assert lerp_by_conviction(0, at_0=8, at_100=35) == 8

    def test_full_conviction_gives_at_100(self):
        assert lerp_by_conviction(100, at_0=8, at_100=35) == 35

    def test_midpoint_interpolates_linearly(self):
        assert lerp_by_conviction(50, at_0=8, at_100=35) == pytest.approx(21.5)

    def test_clamps_out_of_range_scores(self):
        assert lerp_by_conviction(150, at_0=8, at_100=35) == 35
        assert lerp_by_conviction(-10, at_0=8, at_100=35) == 8


class TestKillSwitches:
    def test_no_trigger_below_caps(self):
        status = check_kill_switches(daily_loss_pct=1.0, drawdown_pct=5.0, config=RISK)
        assert status.triggered is False

    def test_daily_loss_triggers(self):
        status = check_kill_switches(daily_loss_pct=3.5, drawdown_pct=0, config=RISK)
        assert status.triggered is True
        assert any("daily loss" in r for r in status.reasons)

    def test_drawdown_triggers(self):
        status = check_kill_switches(daily_loss_pct=0, drawdown_pct=15.0, config=RISK)
        assert status.triggered is True
        assert any("drawdown" in r for r in status.reasons)

    def test_at_exact_cap_triggers(self):
        status = check_kill_switches(daily_loss_pct=RISK.max_daily_loss_pct, drawdown_pct=0, config=RISK)
        assert status.triggered is True

    def test_both_can_trigger_together(self):
        status = check_kill_switches(daily_loss_pct=10, drawdown_pct=20, config=RISK)
        assert len(status.reasons) == 2


class TestVolatilityMultiplier:
    def test_normal_volatility_no_reduction(self):
        assert volatility_size_multiplier(RISK.reference_atr_pct_of_price, RISK) == 1.0

    def test_low_volatility_not_boosted_above_one(self):
        assert volatility_size_multiplier(1.0, RISK) == 1.0

    def test_high_volatility_reduces_size(self):
        mult = volatility_size_multiplier(RISK.reference_atr_pct_of_price * 2, RISK)
        assert mult == pytest.approx(0.5)

    def test_floored_at_min_multiplier(self):
        mult = volatility_size_multiplier(RISK.reference_atr_pct_of_price * 100, RISK)
        assert mult == RISK.min_volatility_size_multiplier

    def test_none_or_zero_atr_treated_as_no_adjustment(self):
        assert volatility_size_multiplier(None, RISK) == 1.0
        assert volatility_size_multiplier(0, RISK) == 1.0


class TestSizeNewPosition:
    def base_kwargs(self, **overrides):
        kwargs = dict(
            conviction_score=100,
            atr_pct_of_price=RISK.reference_atr_pct_of_price,
            nav_usd=100_000,
            sector="Technology",
            cluster="ai_semis",
            current_sector_pct={},
            current_cluster_pct={},
            cash_available_usd=100_000,
            scaling=SCALING,
            config=RISK,
        )
        kwargs.update(overrides)
        return kwargs

    def test_full_conviction_hits_max_position_cap(self):
        # at_100 activation_threshold_pct is 35%, but max_position_pct caps at 12%
        result = size_new_position(**self.base_kwargs())
        assert result.approved is True
        assert result.position_pct == pytest.approx(RISK.max_position_pct)
        assert result.position_usd == pytest.approx(12_000)

    def test_low_conviction_sizes_below_cap(self):
        result = size_new_position(**self.base_kwargs(conviction_score=0))
        assert result.position_pct == pytest.approx(SCALING.activation_threshold_pct.at_0)

    def test_sector_room_caps_size(self):
        result = size_new_position(**self.base_kwargs(current_sector_pct={"Technology": 38}))
        assert result.position_pct == pytest.approx(2.0)  # 40 - 38 room
        assert any("sector room" in r for r in result.reasons)

    def test_cluster_room_caps_size(self):
        result = size_new_position(**self.base_kwargs(current_cluster_pct={"ai_semis": 49}))
        assert result.position_pct == pytest.approx(1.0)  # 50 - 49 room

    def test_cash_available_caps_size(self):
        result = size_new_position(**self.base_kwargs(cash_available_usd=5_000))
        assert result.position_usd == pytest.approx(5_000)
        assert any("cash available" in r for r in result.reasons)

    def test_rejected_below_min_order_value(self):
        result = size_new_position(**self.base_kwargs(nav_usd=1_000, conviction_score=0))
        # at_0 target 8% of tiny NAV -> well under min_order_value_usd
        assert result.approved is False
        assert result.position_usd == 0.0

    def test_high_volatility_shrinks_size(self):
        normal = size_new_position(**self.base_kwargs())
        volatile = size_new_position(**self.base_kwargs(atr_pct_of_price=RISK.reference_atr_pct_of_price * 5))
        assert volatile.position_pct < normal.position_pct

    def test_no_sector_or_cluster_skips_those_caps(self):
        result = size_new_position(**self.base_kwargs(sector=None, cluster=None))
        assert result.approved is True


class TestDailyProposalCap:
    def test_trims_to_cap_keeping_highest_conviction(self):
        proposals = [ScoredProposal(f"T{i}", conviction=i) for i in range(10)]
        kept = enforce_daily_proposal_cap(proposals, RISK)
        assert len(kept) == RISK.max_daily_proposals
        assert [p.ticker for p in kept] == ["T9", "T8", "T7", "T6", "T5"]

    def test_fewer_than_cap_returns_all(self):
        proposals = [ScoredProposal("A", conviction=50)]
        assert enforce_daily_proposal_cap(proposals, RISK) == proposals


class TestTrailingStop:
    def test_breach_when_price_at_or_below_stop(self):
        breached, detail = trailing_stop_breached(
            current_price=100, peak_price=110, atr_14=2.0, conviction_score=100, scaling=SCALING
        )
        # at conviction 100, multiple = 4.5 -> stop = 110 - 9 = 101; price 100 <= 101 -> breached
        assert breached is True

    def test_no_breach_with_wide_stop(self):
        breached, detail = trailing_stop_breached(
            current_price=108, peak_price=110, atr_14=2.0, conviction_score=100, scaling=SCALING
        )
        # stop = 110 - 4.5*2 = 101; price 108 > 101 -> not breached
        assert breached is False

    def test_breach_at_low_conviction_tighter_stop(self):
        # conviction 0 -> multiple 1.5 -> stop = 110 - 3 = 107; price 108 > 107 -> not breached
        breached, detail = trailing_stop_breached(
            current_price=108, peak_price=110, atr_14=2.0, conviction_score=0, scaling=SCALING
        )
        assert breached is False
        # but price 106 would breach the tighter stop
        breached2, _ = trailing_stop_breached(
            current_price=106, peak_price=110, atr_14=2.0, conviction_score=0, scaling=SCALING
        )
        assert breached2 is True

    def test_missing_data_never_breaches(self):
        breached, _ = trailing_stop_breached(100, None, 2.0, 50, SCALING)
        assert breached is False
        breached, _ = trailing_stop_breached(100, 110, None, 50, SCALING)
        assert breached is False


class TestProfitBand:
    def test_crossed_when_gain_exceeds_threshold(self):
        # conviction 100 -> threshold 60%; cost 100 -> price 165 = +65%
        crossed, detail = profit_band_crossed(current_price=165, avg_cost=100, conviction_score=100, scaling=SCALING)
        assert crossed is True

    def test_not_crossed_below_threshold(self):
        crossed, detail = profit_band_crossed(current_price=150, avg_cost=100, conviction_score=100, scaling=SCALING)
        assert crossed is False  # +50% < 60% threshold at full conviction

    def test_lower_conviction_lower_threshold(self):
        # conviction 0 -> threshold 15%; +20% gain crosses it
        crossed, _ = profit_band_crossed(current_price=120, avg_cost=100, conviction_score=0, scaling=SCALING)
        assert crossed is True

    def test_no_cost_basis_never_crosses(self):
        crossed, _ = profit_band_crossed(current_price=120, avg_cost=0, conviction_score=50, scaling=SCALING)
        assert crossed is False


class TestThesisDecay:
    def test_triggers_at_or_above_threshold_drop(self):
        triggered, detail = thesis_decay_triggered(conviction_now=50, conviction_at_entry=65, config=RISK)
        assert triggered is True
        assert detail["drop_pts"] == 15

    def test_no_trigger_below_threshold(self):
        triggered, _ = thesis_decay_triggered(conviction_now=60, conviction_at_entry=68, config=RISK)
        assert triggered is False  # NBIS example from §3: 68 -> 61, an 7pt drop

    def test_conviction_increase_never_triggers(self):
        triggered, _ = thesis_decay_triggered(conviction_now=90, conviction_at_entry=60, config=RISK)
        assert triggered is False

    def test_no_entry_conviction_recorded_never_triggers(self):
        triggered, _ = thesis_decay_triggered(conviction_now=10, conviction_at_entry=None, config=RISK)
        assert triggered is False


class TestUpdatePeakPrice:
    def test_first_observation_becomes_peak(self):
        assert update_peak_price(None, 100) == 100

    def test_new_high_updates_peak(self):
        assert update_peak_price(100, 110) == 110

    def test_lower_price_does_not_lower_peak(self):
        assert update_peak_price(110, 100) == 110


class TestEvaluateHeldPosition:
    def test_no_triggers_when_all_clear(self):
        evaluation = evaluate_held_position(
            ticker="AMD",
            current_price=105,
            avg_cost=100,
            peak_price=108,
            atr_14=2.0,
            conviction_now=70,
            conviction_at_entry=70,
            scaling=SCALING,
            config=RISK,
        )
        assert evaluation.has_exit_signal is False
        assert evaluation.primary_trigger is None

    def test_trailing_stop_is_first_priority(self):
        # rig it so both trailing stop and profit band would fire
        evaluation = evaluate_held_position(
            ticker="AMD",
            current_price=100,
            avg_cost=50,  # +100% gain, way past any profit threshold
            peak_price=102,  # tight peak so a small ATR still breaches
            atr_14=1.0,
            conviction_now=0,  # tightest trailing stop (1.5x) AND lowest profit threshold (15%)
            conviction_at_entry=0,
            scaling=SCALING,
            config=RISK,
        )
        types = [t.type for t in evaluation.triggers]
        assert "TRAILING_STOP" in types
        assert "PROFIT_BAND" in types
        assert evaluation.primary_trigger.type == "TRAILING_STOP"

    def test_thesis_decay_only(self):
        evaluation = evaluate_held_position(
            ticker="NBIS",
            current_price=222,
            avg_cost=218,
            peak_price=241,
            atr_14=50.0,  # huge ATR so trailing stop doesn't also fire
            conviction_now=40,
            conviction_at_entry=68,
            scaling=SCALING,
            config=RISK,
        )
        assert [t.type for t in evaluation.triggers] == ["THESIS_DECAY"]
