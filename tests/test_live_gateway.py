"""FmpMarketDataGateway tests — FMPClient's HTTP session is faked exactly as
in test_fmp_client.py. No test here may hit the network."""

from core.cache import DailyCallBudget, FileCache
from sources.fmp import FMPClient
from sources.live_gateway import FmpMarketDataGateway
from tests.test_fmp_client import FakeResponse, FakeSession


def bar(date, close, volume=1_000_000):
    return {"date": date, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume}


def make_gateway(tmp_path, responses, cluster_overrides=None):
    cache = FileCache(tmp_path / "cache")
    budget = DailyCallBudget(tmp_path / "budget.json", daily_limit=250, today_fn=lambda: "2026-08-25")
    session = FakeSession(responses)
    client = FMPClient(api_key="test-key", cache=cache, budget=budget, session=session)
    return FmpMarketDataGateway(client, cluster_overrides=cluster_overrides), session


def bars_payload(n=210, start=100.0, step=0.1):
    return [bar(f"2026-01-{(i % 28) + 1:02d}", start + i * step) for i in range(n)]


class TestGetScreenerInput:
    def _responses(self):
        return {
            "profile#AMD": FakeResponse(payload=[{"symbol": "AMD", "mktCap": 5_000_000_000, "volAvg": 40_000_000, "pe": 22.5, "sector": "Technology"}]),
            "quote#AMD": FakeResponse(payload=[{"symbol": "AMD", "price": 150.0, "pe": 22.5}]),
            "income-statement#AMD": FakeResponse(payload=[{"revenue": 1100}, {"revenue": 1000}]),
            "cash-flow-statement#AMD": FakeResponse(payload=[{"freeCashFlow": 200}]),
            "historical-price-eod/full#AMD": FakeResponse(payload=bars_payload()),
            "historical-price-eod/full#SPY": FakeResponse(payload=bars_payload(start=500.0, step=0.05)),
        }

    def test_builds_screener_input_without_crashing(self, tmp_path):
        gateway, session = make_gateway(tmp_path, self._responses())
        result = gateway.get_screener_input("AMD", is_held=False)

        assert result.ticker == "AMD"
        assert result.market_cap_usd == 5_000_000_000
        assert result.avg_daily_volume_usd == 40_000_000 * 150.0
        assert result.trailing_pe == 22.5
        assert result.free_cash_flow == 200
        assert result.days_to_earnings is None  # documented gap

    def test_revenue_growth_computed_from_two_periods(self, tmp_path):
        gateway, session = make_gateway(tmp_path, self._responses())
        result = gateway.get_screener_input("AMD", is_held=False)
        assert result.revenue_growth_pct == 10.0  # (1100-1000)/1000 * 100

    def test_technical_snapshot_populated(self, tmp_path):
        gateway, session = make_gateway(tmp_path, self._responses())
        result = gateway.get_screener_input("AMD", is_held=False)
        assert result.technical.sma_200 is not None
        assert result.technical.relative_strength_vs_spy_pct is not None
        assert result.technical.relative_strength_vs_sector_pct is None  # documented gap

    def test_spy_bars_fetched_once_across_multiple_tickers(self, tmp_path):
        responses = self._responses()
        responses.update(
            {
                "profile#NVDA": responses["profile#AMD"],
                "quote#NVDA": responses["quote#AMD"],
                "income-statement#NVDA": responses["income-statement#AMD"],
                "cash-flow-statement#NVDA": responses["cash-flow-statement#AMD"],
                "historical-price-eod/full#NVDA": responses["historical-price-eod/full#AMD"],
            }
        )
        gateway, session = make_gateway(tmp_path, responses)
        gateway.get_screener_input("AMD", is_held=False)
        gateway.get_screener_input("NVDA", is_held=False)
        spy_calls = [c for c in session.calls if c[1].get("symbol") == "SPY"]
        assert len(spy_calls) == 1  # cached in-process after the first fetch


class TestGetCurrentPrice:
    def test_returns_price(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {"quote": FakeResponse(payload=[{"price": 150.5}])})
        assert gateway.get_current_price("AMD") == 150.5

    def test_raises_when_price_missing(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {"quote": FakeResponse(payload=[{"symbol": "AMD"}])})
        try:
            gateway.get_current_price("AMD")
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestSectorAndCluster:
    def test_sector_from_profile(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {"profile": FakeResponse(payload=[{"sector": "Technology"}])})
        assert gateway.get_sector("AMD") == "Technology"

    def test_cluster_from_override_map(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {}, cluster_overrides={"AMD": "ai_semis"})
        assert gateway.get_cluster("amd") == "ai_semis"  # case-insensitive lookup

    def test_cluster_none_when_not_in_override_map(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {}, cluster_overrides={"AMD": "ai_semis"})
        assert gateway.get_cluster("MSFT") is None


class TestGetResearchContext:
    def _base_responses(self):
        return {
            "profile": FakeResponse(payload=[{"companyName": "AMD", "sector": "Technology", "industry": "Semis", "mktCap": 5e9, "pe": 22.5, "description": "Chipmaker"}]),
            "quote": FakeResponse(payload=[{"price": 150.0}]),
            "income-statement": FakeResponse(payload=[{"revenue": 1100}]),
            "cash-flow-statement": FakeResponse(payload=[{"freeCashFlow": 200}]),
            "earnings-surprises": FakeResponse(payload=[]),
            "analyst-estimates": FakeResponse(payload=[]),
            "price-target-summary": FakeResponse(payload=[]),
            "historical-price-eod/full#AMD": FakeResponse(payload=bars_payload()),
            "historical-price-eod/full#SPY": FakeResponse(payload=bars_payload(start=500.0, step=0.05)),
        }

    def test_assembles_readable_text_without_crashing(self, tmp_path):
        responses = self._base_responses()
        responses["institutional-ownership/symbol-positions-summary"] = FakeResponse(payload=[])
        responses["insider-trading"] = FakeResponse(payload=[])
        gateway, session = make_gateway(tmp_path, responses)
        text = gateway.get_research_context("AMD")
        assert "AMD" in text
        assert "Technology" in text
        assert "Technical snapshot" in text

    def test_13f_and_insider_failures_degrade_gracefully(self, tmp_path):
        responses = self._base_responses()
        responses["institutional-ownership/symbol-positions-summary"] = FakeResponse(status_code=402, text="upgrade required")
        responses["insider-trading"] = FakeResponse(status_code=402, text="upgrade required")
        gateway, session = make_gateway(tmp_path, responses)
        text = gateway.get_research_context("AMD")  # must not raise
        assert "error" in text

    def test_earnings_surprises_and_price_target_failures_degrade_gracefully(self, tmp_path):
        # confirmed against the real FMP API during development: these two
        # can 404 even when profile/quote/income-statement work fine
        responses = self._base_responses()
        responses["earnings-surprises"] = FakeResponse(status_code=404, text="not found")
        responses["price-target-summary"] = FakeResponse(status_code=404, text="not found")
        responses["institutional-ownership/symbol-positions-summary"] = FakeResponse(payload=[])
        responses["insider-trading"] = FakeResponse(payload=[])
        gateway, session = make_gateway(tmp_path, responses)
        text = gateway.get_research_context("AMD")  # must not raise
        assert "AMD" in text

    def test_every_field_can_fail_at_once_without_raising(self, tmp_path):
        failing = FakeResponse(status_code=500, text="down")
        responses = {
            "profile": failing, "quote": failing, "income-statement": failing, "cash-flow-statement": failing,
            "earnings-surprises": failing, "analyst-estimates": failing, "price-target-summary": failing,
            "institutional-ownership/symbol-positions-summary": failing, "insider-trading": failing,
            "historical-price-eod/full#AMD": FakeResponse(payload=bars_payload()),
            "historical-price-eod/full#SPY": FakeResponse(payload=bars_payload(start=500.0, step=0.05)),
        }
        gateway, session = make_gateway(tmp_path, responses)
        text = gateway.get_research_context("AMD")  # must not raise even with everything else down
        assert "AMD" in text
