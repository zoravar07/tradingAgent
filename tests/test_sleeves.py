from core.config import SleeveConfig, SleevesConfig, SpeculativeLookConfig
from core.sleeves import (
    SleeveBreachStatus,
    SleeveDrift,
    averaging_down_blocked,
    find_sleeve_drift,
    oversized_speculative,
    resolve_sleeve,
    sleeve_room,
    speculative_look_reasons,
    update_breach_streak,
)

SLEEVES = SleevesConfig()


class TestResolveSleeve:
    def test_core_ticker_resolves_to_core(self):
        assert resolve_sleeve("VTI", SLEEVES) == "CORE"
        assert resolve_sleeve("VGT", SLEEVES) == "CORE"

    def test_hedge_cash_ticker_resolves(self):
        assert resolve_sleeve("IAU", SLEEVES) == "HEDGE_CASH"

    def test_speculative_ticker_resolves(self):
        assert resolve_sleeve("RKLB", SLEEVES) == "SPECULATIVE"
        assert resolve_sleeve("SOFI", SLEEVES) == "SPECULATIVE"

    def test_unlisted_ticker_defaults_to_swing(self):
        assert resolve_sleeve("NVDA", SLEEVES) == "SWING"
        assert resolve_sleeve("SOME_NEW_NAME", SLEEVES) == "SWING"

    def test_case_insensitive(self):
        assert resolve_sleeve("vti", SLEEVES) == "CORE"


class TestFindSleeveDrift:
    def test_no_drift_when_stored_matches_resolved(self):
        holdings = [("VTI", "CORE"), ("NVDA", "SWING"), ("IAU", "HEDGE_CASH")]
        assert find_sleeve_drift(holdings, SLEEVES) == []

    def test_flags_mismatch(self):
        holdings = [("VTI", "SWING")]  # someone edited config after VTI was already tagged CORE
        drift = find_sleeve_drift(holdings, SLEEVES)
        assert drift == [SleeveDrift(ticker="VTI", stored_sleeve="SWING", resolved_sleeve="CORE")]

    def test_multiple_mismatches_all_reported(self):
        holdings = [("VTI", "SWING"), ("RKLB", "SWING"), ("NVDA", "SWING")]
        drift = find_sleeve_drift(holdings, SLEEVES)
        assert {d.ticker for d in drift} == {"VTI", "RKLB"}


class TestSleeveRoom:
    def test_room_when_under_band(self):
        swing = SLEEVES.definitions["SWING"]  # band_high_pct=40
        assert sleeve_room(20.0, swing) == 20.0

    def test_zero_room_when_at_band_high(self):
        swing = SLEEVES.definitions["SWING"]
        assert sleeve_room(40.0, swing) == 0.0

    def test_zero_room_never_negative_when_over_band(self):
        swing = SLEEVES.definitions["SWING"]
        assert sleeve_room(55.0, swing) == 0.0


class TestUpdateBreachStreak:
    def setup_method(self):
        self.swing = SLEEVES.definitions["SWING"]  # band 15-40, target 30

    def test_within_band_resets_to_zero(self):
        previous = SleeveBreachStatus(direction="OVER", streak_days=6)
        result = update_breach_streak(previous, weight_pct=30.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction=None, streak_days=0)

    def test_breach_within_margin_does_not_count(self):
        # band_high=40, +5 margin -> only >45 counts; 43 is over-band but not by enough
        previous = SleeveBreachStatus(direction=None, streak_days=0)
        result = update_breach_streak(previous, weight_pct=43.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction=None, streak_days=0)

    def test_first_day_over_margin_starts_streak_at_one(self):
        previous = SleeveBreachStatus(direction=None, streak_days=0)
        result = update_breach_streak(previous, weight_pct=46.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="OVER", streak_days=1)

    def test_same_direction_continues_streak(self):
        previous = SleeveBreachStatus(direction="OVER", streak_days=9)
        result = update_breach_streak(previous, weight_pct=47.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="OVER", streak_days=10)

    def test_under_band_by_more_than_margin_streaks_under(self):
        # band_low=15, -5 margin -> only <10 counts
        previous = SleeveBreachStatus(direction=None, streak_days=0)
        result = update_breach_streak(previous, weight_pct=8.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="UNDER", streak_days=1)

    def test_direction_flip_resets_streak_to_one(self):
        previous = SleeveBreachStatus(direction="OVER", streak_days=9)
        result = update_breach_streak(previous, weight_pct=8.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="UNDER", streak_days=1)


LOOK = SpeculativeLookConfig()  # market_cap_below_usd=10_000_000_000


class TestSpeculativeLookReasons:
    def test_no_reasons_for_a_clean_large_cap(self):
        reasons = speculative_look_reasons(
            market_cap_usd=500_000_000_000, free_cash_flow=5_000_000_000, trailing_pe=25.0, config=LOOK
        )
        assert reasons == []

    def test_flags_small_market_cap(self):
        reasons = speculative_look_reasons(
            market_cap_usd=2_000_000_000, free_cash_flow=100_000_000, trailing_pe=20.0, config=LOOK
        )
        assert any("market cap" in r for r in reasons)

    def test_flags_negative_free_cash_flow(self):
        reasons = speculative_look_reasons(
            market_cap_usd=50_000_000_000, free_cash_flow=-10_000_000, trailing_pe=20.0, config=LOOK
        )
        assert any("free cash flow" in r for r in reasons)

    def test_flags_no_earnings(self):
        reasons = speculative_look_reasons(
            market_cap_usd=50_000_000_000, free_cash_flow=100_000_000, trailing_pe=None, config=LOOK
        )
        assert any("earnings" in r for r in reasons)

    def test_multiple_reasons_all_reported(self):
        reasons = speculative_look_reasons(
            market_cap_usd=1_000_000_000, free_cash_flow=-1.0, trailing_pe=None, config=LOOK
        )
        assert len(reasons) == 3

    def test_missing_market_cap_is_not_treated_as_small(self):
        # None means unknown, not "below threshold" — don't manufacture a signal from missing data
        reasons = speculative_look_reasons(
            market_cap_usd=None, free_cash_flow=100_000_000, trailing_pe=20.0, config=LOOK
        )
        assert reasons == []


class TestAveragingDownBlocked:
    def test_blocks_when_price_below_avg_cost(self):
        assert averaging_down_blocked(current_price=10.0, avg_cost=15.0) is True

    def test_allows_when_price_above_avg_cost(self):
        assert averaging_down_blocked(current_price=20.0, avg_cost=15.0) is False

    def test_allows_at_exactly_avg_cost(self):
        assert averaging_down_blocked(current_price=15.0, avg_cost=15.0) is False


SPECULATIVE = SleeveConfig(
    target_pct=7, band_low_pct=0, band_high_pct=12, tickers=["RKLB", "SOFI"],
    slot_count=5, slot_pct=2.5, hard_stop_pct=-60, reclass_at_pct=15, oversized_slot_multiple=2.0,
)


class TestOversizedSpeculative:
    def test_flags_position_well_above_slot_size(self):
        # RKLB's real scenario: sized under old conviction-based rules,
        # assigned to SPECULATIVE rather than sized into it (slot=2.5%,
        # threshold at 2x = 5%)
        assert oversized_speculative(weight_pct=8.0, sleeve_config=SPECULATIVE) is True

    def test_does_not_flag_a_position_sized_at_one_slot(self):
        assert oversized_speculative(weight_pct=2.5, sleeve_config=SPECULATIVE) is False

    def test_does_not_flag_exactly_at_threshold(self):
        assert oversized_speculative(weight_pct=5.0, sleeve_config=SPECULATIVE) is False

    def test_flags_just_above_threshold(self):
        assert oversized_speculative(weight_pct=5.01, sleeve_config=SPECULATIVE) is True

    def test_no_multiple_configured_never_flags(self):
        no_multiple = SleeveConfig(target_pct=7, band_low_pct=0, band_high_pct=12, slot_pct=2.5)
        assert oversized_speculative(weight_pct=100.0, sleeve_config=no_multiple) is False

    def test_no_slot_pct_configured_never_flags(self):
        no_slot = SleeveConfig(target_pct=30, band_low_pct=15, band_high_pct=40)
        assert oversized_speculative(weight_pct=100.0, sleeve_config=no_slot) is False
