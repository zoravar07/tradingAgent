from core.config import Config, SleeveConfig, SleevesConfig, SpeculativeLookConfig


class TestSleevesConfig:
    def test_defaults_seed_the_four_sleeves(self):
        sleeves = SleevesConfig()
        assert set(sleeves.definitions.keys()) == {"CORE", "HEDGE_CASH", "SWING", "SPECULATIVE"}
        assert sleeves.definitions["CORE"].tickers == ["VTI", "VGT"]
        assert sleeves.definitions["HEDGE_CASH"].tickers == ["IAU"]
        assert sleeves.definitions["HEDGE_CASH"].includes_account_cash is True
        assert sleeves.definitions["SWING"].tickers == []
        assert sleeves.definitions["SPECULATIVE"].tickers == ["RKLB", "SOFI"]
        assert sleeves.definitions["SPECULATIVE"].slot_count == 5
        assert sleeves.definitions["SPECULATIVE"].slot_pct == 2.5
        assert sleeves.definitions["SPECULATIVE"].hard_stop_pct == -60
        assert sleeves.definitions["SPECULATIVE"].reclass_at_pct == 15
        assert sleeves.default_sleeve == "SWING"
        assert sleeves.breach_sustain_days == 10
        assert sleeves.breach_margin_pct == 5.0

    def test_bands_match_target(self):
        sleeves = SleevesConfig()
        core = sleeves.definitions["CORE"]
        assert (core.target_pct, core.band_low_pct, core.band_high_pct) == (50, 40, 65)
        hedge = sleeves.definitions["HEDGE_CASH"]
        assert (hedge.target_pct, hedge.band_low_pct, hedge.band_high_pct) == (13, 8, 25)
        swing = sleeves.definitions["SWING"]
        assert (swing.target_pct, swing.band_low_pct, swing.band_high_pct) == (30, 15, 40)
        spec = sleeves.definitions["SPECULATIVE"]
        assert (spec.target_pct, spec.band_low_pct, spec.band_high_pct) == (7, 0, 12)


class TestSpeculativeLookConfig:
    def test_default_market_cap_threshold(self):
        assert SpeculativeLookConfig().market_cap_below_usd == 10_000_000_000


class TestConfigIncludesSleeves:
    def test_config_default_has_sleeves_and_speculative_look(self):
        config = Config()
        assert isinstance(config.sleeves, SleevesConfig)
        assert isinstance(config.speculative_look, SpeculativeLookConfig)
