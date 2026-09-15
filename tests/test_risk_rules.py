import pytest

from core.config import ConvictionScalingConfig, RiskConfig, SleeveConfig
from core.risk_rules import (
    ScoredProposal,
    check_kill_switches,
    conviction_floor_triggered,
    enforce_daily_proposal_cap,
    evaluate_held_position,
    hard_stop_breached,
    lerp_by_conviction,
    meets_entry_floor,
    profit_band_crossed,
    runner_trim_triggered,
    size_new_position,
    size_speculative_position,
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


class TestMeetsEntryFloor:
    def test_below_c_enter_rejected(self):
        assert meets_entry_floor(57.9, RISK) is False

    def test_at_c_enter_accepted(self):
        assert meets_entry_floor(58.0, RISK) is True

    def test_above_c_enter_accepted(self):
        assert meets_entry_floor(60.8, RISK) is True  # Run 8's best new candidate


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


class TestSizeNewPositionSleeveRoom:
    def test_sleeve_room_caps_position_size(self):
        result = size_new_position(
            conviction_score=90, atr_pct_of_price=None, nav_usd=100_000, sector=None, cluster=None,
            current_sector_pct={}, current_cluster_pct={}, cash_available_usd=100_000,
            scaling=SCALING, config=RISK, sleeve_room=3.0,
        )
        assert result.approved is True
        assert result.position_pct == pytest.approx(3.0)
        assert any("sleeve room" in r for r in result.reasons)

    def test_zero_sleeve_room_rejects_the_buy(self):
        result = size_new_position(
            conviction_score=90, atr_pct_of_price=None, nav_usd=100_000, sector=None, cluster=None,
            current_sector_pct={}, current_cluster_pct={}, cash_available_usd=100_000,
            scaling=SCALING, config=RISK, sleeve_room=0.0,
        )
        assert result.approved is False

    def test_none_sleeve_room_means_uncapped(self):
        # existing callers that don't know about sleeves yet keep working
        result = size_new_position(
            conviction_score=90, atr_pct_of_price=None, nav_usd=100_000, sector=None, cluster=None,
            current_sector_pct={}, current_cluster_pct={}, cash_available_usd=100_000,
            scaling=SCALING, config=RISK,
        )
        assert result.approved is True


SPECULATIVE = SleeveConfig(
    target_pct=7, band_low_pct=0, band_high_pct=12, tickers=["RKLB", "SOFI"],
    slot_count=5, slot_pct=2.5, hard_stop_pct=-60, reclass_at_pct=15,
)


class TestSizeSpeculativePosition:
    def test_sizes_at_fixed_slot_pct_regardless_of_room(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=10.0,
            open_speculative_slots=1, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.approved is True
        assert result.position_pct == pytest.approx(2.5)
        assert result.position_usd == pytest.approx(2_500.0)

    def test_all_slots_filled_rejects(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=10.0,
            open_speculative_slots=5, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.approved is False
        assert any("slots filled" in r for r in result.reasons)

    def test_sleeve_room_caps_slot_size(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=1.0,
            open_speculative_slots=0, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.position_pct == pytest.approx(1.0)

    def test_cash_available_caps_position(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=1_000, sleeve_room=10.0,
            open_speculative_slots=0, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.position_usd == pytest.approx(1_000.0)

    def test_below_min_order_value_rejects(self):
        tiny_risk = RiskConfig(min_order_value_usd=10_000)
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=10.0,
            open_speculative_slots=0, sleeve_config=SPECULATIVE, config=tiny_risk,
        )
        assert result.approved is False


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
    def test_gain_below_activation_threshold_stays_unactivated(self):
        # avg_cost 100, conviction 48 -> threshold ~21% (lerp(48, 8, 35)).
        # 4.5% gain (IAU's actual run-up) never clears it.
        assert update_peak_price(None, 104.5, avg_cost=100, conviction_score=48, scaling=SCALING) is None

    def test_gain_clearing_activation_threshold_sets_peak(self):
        assert update_peak_price(None, 125, avg_cost=100, conviction_score=48, scaling=SCALING) == 125

    def test_already_activated_peak_keeps_tracking_even_if_gain_now_below_threshold(self):
        # Once activated, §6's "never recompute from scratch" applies — the
        # running max persists even if price pulls back under the threshold.
        assert update_peak_price(130, 95, avg_cost=100, conviction_score=48, scaling=SCALING) == 130

    def test_already_activated_new_high_updates_peak(self):
        assert update_peak_price(125, 140, avg_cost=100, conviction_score=48, scaling=SCALING) == 140

    def test_no_conviction_score_cannot_activate(self):
        # Without a real conviction score there's no threshold to test gain
        # against, so the position must stay unactivated rather than guess.
        assert update_peak_price(None, 200, avg_cost=100, conviction_score=None, scaling=SCALING) is None

    def test_iau_scenario_never_activates_and_never_generates_trailing_stop(self):
        """Regression test for the IAU bug: a position whose gain from cost
        never clears its conviction-scaled activation threshold must never
        acquire a peak_price_since_activation, and therefore must never be
        able to produce a TRAILING_STOP exit — no matter how far it later
        falls or how tight the ATR-implied stop would be."""
        avg_cost = 83.995
        conviction = 48.0  # threshold ~21% at this conviction
        peak: float | None = None
        for price in (84.0, 86.0, 87.76, 85.0, 82.0):  # never exceeds ~4.5% gain
            peak = update_peak_price(peak, price, avg_cost=avg_cost, conviction_score=conviction, scaling=SCALING)

        assert peak is None

        evaluation = evaluate_held_position(
            ticker="IAU",
            current_price=82.0,  # -2.4% from cost
            avg_cost=avg_cost,
            peak_price=peak,
            atr_14=2.0,  # tight ATR that would trivially breach a bogus peak
            conviction_now=conviction,
            conviction_at_entry=None,
            scaling=SCALING,
            config=RISK,
        )
        assert not any(t.type == "TRAILING_STOP" for t in evaluation.triggers)


class TestRunnerTrimTriggered:
    def test_breaches_above_trigger_pct(self):
        breached, detail = runner_trim_triggered(weight_pct=31.0, config=RISK)
        assert breached is True
        assert detail["trigger_pct"] == 30.0
        assert detail["target_pct"] == 25.0

    def test_does_not_breach_at_or_below_trigger_pct(self):
        breached, _ = runner_trim_triggered(weight_pct=30.0, config=RISK)
        assert breached is False
        breached, _ = runner_trim_triggered(weight_pct=12.0, config=RISK)
        assert breached is False


class TestHardStopBreached:
    def test_breaches_at_or_below_threshold(self):
        breached, detail = hard_stop_breached(current_price=40.0, avg_cost=100.0, hard_stop_pct=-60)
        assert breached is True
        assert detail["gain_pct"] == pytest.approx(-60.0)

    def test_does_not_breach_above_threshold(self):
        breached, _ = hard_stop_breached(current_price=45.0, avg_cost=100.0, hard_stop_pct=-60)
        assert breached is False

    def test_no_cost_basis_never_breaches(self):
        breached, detail = hard_stop_breached(current_price=40.0, avg_cost=0.0, hard_stop_pct=-60)
        assert breached is False
        assert detail["reason"] == "no cost basis"


class TestEvaluateHeldPositionSleeveGating:
    def test_core_position_never_triggers_signal_based_exits(self):
        # Numbers that would trivially trigger TRAILING_STOP, PROFIT_BAND,
        # THESIS_DECAY, and CONVICTION_FLOOR all at once for a SWING position.
        evaluation = evaluate_held_position(
            ticker="VTI", current_price=50.0, avg_cost=100.0, peak_price=200.0, atr_14=1.0,
            conviction_now=10.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
            sleeve="CORE",
        )
        assert evaluation.triggers == []

    def test_hedge_cash_position_never_triggers_signal_based_exits(self):
        evaluation = evaluate_held_position(
            ticker="IAU", current_price=50.0, avg_cost=100.0, peak_price=200.0, atr_14=1.0,
            conviction_now=10.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
            sleeve="HEDGE_CASH",
        )
        assert evaluation.triggers == []

    def test_swing_position_keeps_existing_behavior_by_default(self):
        # sleeve defaults to "SWING" — every pre-existing call site/test in
        # this file keeps working unchanged.
        evaluation = evaluate_held_position(
            ticker="AMD", current_price=105, avg_cost=100, peak_price=108, atr_14=2.0,
            conviction_now=70, conviction_at_entry=70, scaling=SCALING, config=RISK,
        )
        assert evaluation.has_exit_signal is False

    def test_speculative_position_ignores_conviction_floor_and_uses_hard_stop(self):
        # conviction_now=0 would trivially trigger CONVICTION_FLOOR on SWING;
        # SPECULATIVE must ignore it and only check the hard stop.
        evaluation = evaluate_held_position(
            ticker="RKLB", current_price=100.0, avg_cost=100.0, peak_price=150.0, atr_14=1.0,
            conviction_now=0.0, conviction_at_entry=50.0, scaling=SCALING, config=RISK,
            sleeve="SPECULATIVE", hard_stop_pct=-60,
        )
        assert evaluation.triggers == []

    def test_speculative_position_hard_stop_fires(self):
        evaluation = evaluate_held_position(
            ticker="RKLB", current_price=39.0, avg_cost=100.0, peak_price=150.0, atr_14=1.0,
            conviction_now=50.0, conviction_at_entry=50.0, scaling=SCALING, config=RISK,
            sleeve="SPECULATIVE", hard_stop_pct=-60,
        )
        assert evaluation.has_exit_signal is True
        assert evaluation.primary_trigger.type == "HARD_STOP"


class TestEvaluateHeldPositionRunnerTrim:
    """The runner rule applies to every sleeve, unconditionally — including
    when there's no fresh (or any) conviction score this run, since it's a
    structural concentration cap, not a thesis judgment."""

    def test_fires_for_core_despite_no_other_signal_based_exits(self):
        evaluation = evaluate_held_position(
            ticker="VTI", current_price=100.0, avg_cost=100.0, peak_price=100.0, atr_14=1.0,
            weight_pct=31.0, conviction_now=90.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
            sleeve="CORE",
        )
        assert [t.type for t in evaluation.triggers] == ["RUNNER_TRIM"]

    def test_fires_for_hedge_cash(self):
        evaluation = evaluate_held_position(
            ticker="IAU", current_price=100.0, avg_cost=100.0, peak_price=100.0, atr_14=1.0,
            weight_pct=31.0, conviction_now=90.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
            sleeve="HEDGE_CASH",
        )
        assert [t.type for t in evaluation.triggers] == ["RUNNER_TRIM"]

    def test_fires_for_speculative_alongside_hard_stop_check(self):
        evaluation = evaluate_held_position(
            ticker="RKLB", current_price=100.0, avg_cost=100.0, peak_price=100.0, atr_14=1.0,
            weight_pct=31.0, conviction_now=90.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
            sleeve="SPECULATIVE", hard_stop_pct=-60,
        )
        assert [t.type for t in evaluation.triggers] == ["RUNNER_TRIM"]

    def test_fires_even_with_no_conviction_score_at_all(self):
        # An unresearched position still gets the runner rule — it's not a
        # thesis judgment, it needs no conviction score to apply.
        evaluation = evaluate_held_position(
            ticker="NVDA", current_price=100.0, avg_cost=100.0, peak_price=100.0, atr_14=1.0,
            weight_pct=31.0, conviction_now=None, conviction_at_entry=None, scaling=SCALING, config=RISK,
        )
        assert [t.type for t in evaluation.triggers] == ["RUNNER_TRIM"]

    def test_no_conviction_score_and_below_trigger_produces_no_signal(self):
        evaluation = evaluate_held_position(
            ticker="NVDA", current_price=100.0, avg_cost=100.0, peak_price=100.0, atr_14=1.0,
            weight_pct=10.0, conviction_now=None, conviction_at_entry=None, scaling=SCALING, config=RISK,
        )
        assert evaluation.has_exit_signal is False

    def test_is_first_priority_for_swing_over_all_other_triggers(self):
        # Rig it so trailing stop, thesis decay, and conviction floor would
        # all also fire — RUNNER_TRIM must still win as primary_trigger.
        evaluation = evaluate_held_position(
            ticker="AMD", current_price=50.0, avg_cost=100.0, peak_price=200.0, atr_14=1.0,
            weight_pct=31.0, conviction_now=0.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
        )
        assert evaluation.primary_trigger.type == "RUNNER_TRIM"

    def test_below_trigger_pct_never_fires(self):
        evaluation = evaluate_held_position(
            ticker="AMD", current_price=100.0, avg_cost=100.0, peak_price=100.0, atr_14=1.0,
            weight_pct=12.0, conviction_now=90.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
        )
        assert evaluation.has_exit_signal is False

    def test_default_weight_pct_never_fires(self):
        # weight_pct defaults to 0.0 — every pre-existing call site/test
        # that doesn't know about the runner rule keeps working unchanged.
        evaluation = evaluate_held_position(
            ticker="AMD", current_price=105, avg_cost=100, peak_price=108, atr_14=2.0,
            conviction_now=70, conviction_at_entry=70, scaling=SCALING, config=RISK,
        )
        assert evaluation.has_exit_signal is False


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
            conviction_now=45,  # >= min_hold_conviction (42), but still a >=15pt drop from entry
            conviction_at_entry=68,
            scaling=SCALING,
            config=RISK,
        )
        assert [t.type for t in evaluation.triggers] == ["THESIS_DECAY"]

    def test_conviction_floor_fires_with_no_price_move_and_no_baseline(self):
        # the RKLB/MP gap: no entry baseline, price hasn't dropped, but
        # conviction is just low — nothing else would ever catch this
        evaluation = evaluate_held_position(
            ticker="RKLB",
            current_price=105,  # up slightly, nowhere near a profit band
            avg_cost=100,
            peak_price=106,  # tight enough peak that a sane ATR shouldn't breach
            atr_14=2.0,
            conviction_now=36.4,
            conviction_at_entry=None,  # no baseline recorded
            scaling=SCALING,
            config=RISK,
        )
        assert [t.type for t in evaluation.triggers] == ["CONVICTION_FLOOR"]

    def test_conviction_floor_does_not_fire_at_or_above_threshold(self):
        evaluation = evaluate_held_position(
            ticker="AMD", current_price=105, avg_cost=100, peak_price=106, atr_14=2.0,
            conviction_now=RISK.min_hold_conviction, conviction_at_entry=None, scaling=SCALING, config=RISK,
        )
        assert evaluation.has_exit_signal is False

    def test_conviction_floor_suppressed_when_conviction_not_fresh(self):
        # an unresearched position must not exit on a fabricated fallback
        # conviction_now, same principle as thesis-decay's own guard
        evaluation = evaluate_held_position(
            ticker="RKLB", current_price=105, avg_cost=100, peak_price=106, atr_14=2.0,
            conviction_now=30.0, conviction_at_entry=None, scaling=SCALING, config=RISK,
            conviction_is_fresh=False,
        )
        assert evaluation.has_exit_signal is False

    def test_conviction_floor_is_lowest_priority(self):
        # rig it so trailing stop AND the conviction floor would both fire
        evaluation = evaluate_held_position(
            ticker="AMD", current_price=100, avg_cost=50, peak_price=102, atr_14=1.0,
            conviction_now=0, conviction_at_entry=None, scaling=SCALING, config=RISK,
        )
        types = [t.type for t in evaluation.triggers]
        assert "TRAILING_STOP" in types
        assert "CONVICTION_FLOOR" in types
        assert evaluation.primary_trigger.type == "TRAILING_STOP"


class TestConvictionFloor:
    def test_triggers_below_threshold(self):
        triggered, detail = conviction_floor_triggered(36.4, RISK)
        assert triggered is True
        assert detail["conviction_now"] == 36.4
        assert detail["min_hold_conviction"] == RISK.min_hold_conviction

    def test_no_trigger_at_threshold(self):
        triggered, _ = conviction_floor_triggered(RISK.min_hold_conviction, RISK)
        assert triggered is False

    def test_no_trigger_above_threshold(self):
        triggered, _ = conviction_floor_triggered(70.0, RISK)
        assert triggered is False
