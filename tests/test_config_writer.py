"""core/config_writer.py — comment-preserving round-trip read/write for the
Settings screen. Always operates on a tmp_path fixture file, never the real
config.yaml."""

from core.config_writer import apply_updates, default_values, editable_snapshot, read_raw, write_raw

SAMPLE_YAML = """\
version: 1

portfolio:
  # this comment must survive a write that doesn't touch allow_fractional
  allow_fractional: true

risk:
  max_position_pct: 12
  max_sector_pct: 40
  max_correlated_cluster_pct: 50
  max_daily_proposals: 5
  max_daily_loss_pct: 3
  max_drawdown_pct: 12
  min_order_value_usd: 150
  min_hold_conviction: 40.0
  max_unpriced_held_positions: 0

screener:
  stage1:
    min_avg_daily_volume_usd: 20000000
    min_market_cap_usd: 2000000000
    max_survivors: 40
    min_revenue_growth_pct: 5.0
    valuation_pe_cheap_max: 15.0
    valuation_pe_expensive_min: 30.0
    earnings_proximity_days: 5

budget:
  monthly_api_cap_usd: 40

schedule:
  nightly_run: "0 22 * * 0-4"

# an unmodeled section the app doesn't read yet -- must round-trip untouched
sleeves:
  core_longterm: 35
  thematic: 45
"""


def write_sample(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(SAMPLE_YAML)
    return p


class TestRoundTrip:
    def test_reads_editable_fields_correctly(self, tmp_path):
        raw = read_raw(write_sample(tmp_path))
        snap = editable_snapshot(raw)
        assert snap["risk"]["max_position_pct"] == 12
        assert snap["portfolio"]["allow_fractional"] is True
        assert snap["screener"]["stage1"]["valuation_pe_cheap_max"] == 15.0
        assert snap["schedule"]["nightly_run"] == "0 22 * * 0-4"

    def test_write_preserves_comments_and_unmodeled_sections(self, tmp_path):
        path = write_sample(tmp_path)
        raw = read_raw(path)
        apply_updates(raw, {"risk": {"max_position_pct": 15}})
        write_raw(path, raw)

        text = path.read_text()
        assert "this comment must survive" in text
        assert "sleeves:" in text
        assert "core_longterm: 35" in text
        # and the actual edit landed
        assert "max_position_pct: 15" in text

    def test_apply_updates_only_touches_listed_fields(self, tmp_path):
        raw = read_raw(write_sample(tmp_path))
        before = editable_snapshot(raw)
        apply_updates(raw, {"budget": {"monthly_api_cap_usd": 100}})
        after = editable_snapshot(raw)

        assert after["budget"]["monthly_api_cap_usd"] == 100
        # everything else unchanged
        after.pop("budget")
        before.pop("budget")
        assert after == before

    def test_missing_field_falls_back_to_pydantic_default(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("version: 1\n")  # nothing else present
        raw = read_raw(path)
        snap = editable_snapshot(raw)
        assert snap["risk"]["min_hold_conviction"] == 42.0  # RiskConfig()'s own default


class TestDefaultValues:
    def test_matches_the_real_pydantic_defaults(self):
        from core.config import RiskConfig

        defaults = default_values()
        assert defaults["risk"]["max_position_pct"] == RiskConfig().max_position_pct
