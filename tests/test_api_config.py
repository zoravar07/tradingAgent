"""API tests for the Settings screen backend — FastAPI's TestClient against
isolated temp-file DB *and* config.yaml per test, never the real files."""

from fastapi.testclient import TestClient

from api.server import create_app

SAMPLE_YAML = """\
version: 1

portfolio:
  import_reminder_days: 7
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

sleeves:
  core_longterm: 35
"""


def make_client(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(SAMPLE_YAML)
    db_path = tmp_path / "test.db"
    app = create_app(db_path=db_path, config_path=config_path)
    return TestClient(app), config_path


def valid_body(**overrides):
    body = {
        "portfolio": {"import_reminder_days": 7, "allow_fractional": True},
        "risk": {
            "max_position_pct": 12, "max_sector_pct": 40, "max_correlated_cluster_pct": 50,
            "max_daily_proposals": 5, "max_daily_loss_pct": 3, "max_drawdown_pct": 12,
            "min_order_value_usd": 150, "min_hold_conviction": 40.0, "max_unpriced_held_positions": 0,
        },
        "screener": {"stage1": {
            "min_avg_daily_volume_usd": 20_000_000, "min_market_cap_usd": 2_000_000_000,
            "max_survivors": 40, "min_revenue_growth_pct": 5.0,
            "valuation_pe_cheap_max": 15.0, "valuation_pe_expensive_min": 30.0,
            "earnings_proximity_days": 5,
        }},
        "budget": {"monthly_api_cap_usd": 40},
        "schedule": {"nightly_run": "0 22 * * 0-4"},
    }
    for section, fields in overrides.items():
        body[section].update(fields)
    return body


class TestGetConfig:
    def test_returns_editable_defaults_and_raw_text(self, tmp_path):
        client, _ = make_client(tmp_path)
        resp = client.get("/api/config")
        body = resp.json()

        assert resp.status_code == 200
        assert body["editable"]["risk"]["max_position_pct"] == 12
        assert body["defaults"]["risk"]["max_position_pct"] == 12.0  # RiskConfig()'s own default, coincidentally same
        assert "sleeves:" in body["yaml_text"]


class TestUpdateConfig:
    def test_valid_update_persists_and_snapshots(self, tmp_path):
        client, config_path = make_client(tmp_path)

        resp = client.post("/api/config/update", json=valid_body(risk={"max_position_pct": 20}))
        body = resp.json()

        assert resp.status_code == 200
        assert body["editable"]["risk"]["max_position_pct"] == 20
        assert "max_position_pct: 20" in config_path.read_text()
        assert "sleeves:" in config_path.read_text()  # unmodeled section untouched

        from core.db import make_engine, make_session_factory
        from core.models import ConfigVersion

        engine = make_engine(tmp_path / "test.db")
        session = make_session_factory(engine)()
        versions = session.query(ConfigVersion).all()
        assert len(versions) == 1
        assert versions[0].version == 1

    def test_out_of_range_percentage_rejected(self, tmp_path):
        client, config_path = make_client(tmp_path)
        original = config_path.read_text()

        resp = client.post("/api/config/update", json=valid_body(risk={"max_position_pct": 150}))

        assert resp.status_code == 422
        assert config_path.read_text() == original  # nothing written on a rejected update

    def test_cheap_pe_must_be_below_expensive_pe(self, tmp_path):
        client, _ = make_client(tmp_path)

        resp = client.post(
            "/api/config/update",
            json=valid_body(screener={"stage1": {
                "min_avg_daily_volume_usd": 20_000_000, "min_market_cap_usd": 2_000_000_000,
                "max_survivors": 40, "min_revenue_growth_pct": 5.0,
                "valuation_pe_cheap_max": 35.0, "valuation_pe_expensive_min": 30.0,
                "earnings_proximity_days": 5,
            }}),
        )

        assert resp.status_code == 422
        assert "valuation_pe_cheap_max" in str(resp.json()["detail"])

    def test_invalid_cron_rejected(self, tmp_path):
        client, _ = make_client(tmp_path)

        resp = client.post("/api/config/update", json=valid_body(schedule={"nightly_run": "not a cron"}))

        assert resp.status_code == 422

    def test_second_update_increments_version(self, tmp_path):
        client, tmp_config = make_client(tmp_path)
        client.post("/api/config/update", json=valid_body(risk={"max_position_pct": 15}))
        client.post("/api/config/update", json=valid_body(risk={"max_position_pct": 18}))

        from core.db import make_engine, make_session_factory
        from core.models import ConfigVersion

        engine = make_engine(tmp_path / "test.db")
        session = make_session_factory(engine)()
        versions = sorted(session.query(ConfigVersion).all(), key=lambda v: v.version)
        assert [v.version for v in versions] == [1, 2]


class TestResetConfig:
    def test_resets_editable_fields_to_pydantic_defaults(self, tmp_path):
        client, config_path = make_client(tmp_path)
        client.post("/api/config/update", json=valid_body(risk={"max_position_pct": 99}))

        resp = client.post("/api/config/reset")
        body = resp.json()

        assert resp.status_code == 200
        from core.config import RiskConfig

        assert body["editable"]["risk"]["max_position_pct"] == RiskConfig().max_position_pct
        assert "sleeves:" in config_path.read_text()  # still untouched
