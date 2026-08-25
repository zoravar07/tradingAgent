"""FMPClient tests — HTTP is a fake session, never a real request. No test in
this file may hit the network or spend real FMP quota."""

import datetime as dt

import pytest

from core.cache import BudgetExceeded, DailyCallBudget, FileCache
from sources.base import RunContext
from sources.fmp import FMPClient, FMPError, FMPFactorSource


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Records every call and serves canned responses keyed by path."""

    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params, timeout):
        self.calls.append((url, params))
        for path, response in self.responses.items():
            if url.endswith(path):
                return response
        raise AssertionError(f"no fake response registered for {url}")


def make_client(tmp_path, responses, daily_limit=250):
    cache = FileCache(tmp_path / "cache")
    budget = DailyCallBudget(tmp_path / "budget.json", daily_limit=daily_limit, today_fn=lambda: "2026-08-25")
    session = FakeSession(responses)
    client = FMPClient(api_key="test-key", cache=cache, budget=budget, session=session)
    return client, session


class TestFMPClientBasics:
    def test_get_profile_unwraps_list(self, tmp_path):
        client, session = make_client(
            tmp_path, {"/v3/profile/AMD": FakeResponse(payload=[{"symbol": "AMD", "mktCap": 1000}])}
        )
        profile = client.get_profile("AMD")
        assert profile == {"symbol": "AMD", "mktCap": 1000}

    def test_apikey_sent_as_query_param(self, tmp_path):
        client, session = make_client(
            tmp_path, {"/v3/quote/AMD": FakeResponse(payload=[{"symbol": "AMD", "price": 150}])}
        )
        client.get_quote("AMD")
        assert session.calls[0][1]["apikey"] == "test-key"

    def test_second_call_is_served_from_cache(self, tmp_path):
        client, session = make_client(
            tmp_path, {"/v3/quote/AMD": FakeResponse(payload=[{"symbol": "AMD", "price": 150}])}
        )
        client.get_quote("AMD")
        client.get_quote("AMD")
        assert len(session.calls) == 1  # second call hit the cache, no network

    def test_non_200_raises_fmp_error(self, tmp_path):
        client, session = make_client(tmp_path, {"/v3/quote/BAD": FakeResponse(status_code=404, text="not found")})
        with pytest.raises(FMPError):
            client.get_quote("BAD")

    def test_error_message_payload_raises_fmp_error(self, tmp_path):
        client, session = make_client(
            tmp_path, {"/v3/quote/BAD": FakeResponse(payload={"Error Message": "Invalid API key"})}
        )
        with pytest.raises(FMPError, match="Invalid API key"):
            client.get_quote("BAD")

    def test_failed_call_does_not_consume_budget_twice(self, tmp_path):
        # a raised FMPError still counts as one call against the budget —
        # it happened, it just wasn't useful
        client, session = make_client(tmp_path, {"/v3/quote/BAD": FakeResponse(status_code=500)}, daily_limit=1)
        with pytest.raises(FMPError):
            client.get_quote("BAD")
        assert client.budget.used_today() == 1

    def test_budget_exhaustion_prevents_further_calls(self, tmp_path):
        client, session = make_client(
            tmp_path,
            {
                "/v3/quote/AMD": FakeResponse(payload=[{"symbol": "AMD"}]),
                "/v3/quote/NVDA": FakeResponse(payload=[{"symbol": "NVDA"}]),
            },
            daily_limit=1,
        )
        client.get_quote("AMD")
        with pytest.raises(BudgetExceeded):
            client.get_quote("NVDA")

    def test_historical_prices_unwraps_historical_key(self, tmp_path):
        client, session = make_client(
            tmp_path,
            {
                "/v3/historical-price-full/AMD": FakeResponse(
                    payload={"symbol": "AMD", "historical": [{"date": "2026-08-24", "close": 168.5}]}
                )
            },
        )
        rows = client.get_historical_prices("AMD")
        assert rows == [{"date": "2026-08-24", "close": 168.5}]

    def test_v4_endpoint_uses_query_param_symbol(self, tmp_path):
        client, session = make_client(
            tmp_path, {"/v4/insider-trading": FakeResponse(payload=[{"symbol": "AMD", "transactionType": "S-Sale"}])}
        )
        rows = client.get_insider_trading("AMD")
        assert rows[0]["symbol"] == "AMD"
        assert session.calls[0][1]["symbol"] == "AMD"


class TestFMPFactorSource:
    def _responses(self):
        return {
            "/v3/profile/AMD": FakeResponse(payload=[{"symbol": "AMD"}]),
            "/v3/quote/AMD": FakeResponse(payload=[{"symbol": "AMD", "price": 168.5}]),
            "/v3/income-statement/AMD": FakeResponse(payload=[{"revenue": 1000}]),
            "/v3/cash-flow-statement/AMD": FakeResponse(payload=[{"freeCashFlow": 200}]),
            "/v3/earnings-surprises/AMD": FakeResponse(payload=[]),
            "/v3/analyst-estimates/AMD": FakeResponse(payload=[]),
            "/v4/price-target-summary": FakeResponse(payload=[]),
            "/v4/institutional-ownership/symbol-ownership": FakeResponse(payload=[]),
            "/v4/insider-trading": FakeResponse(payload=[]),
        }

    def test_fetch_assembles_all_fields(self, tmp_path):
        client, session = make_client(tmp_path, self._responses())
        source = FMPFactorSource(client)
        ctx = RunContext(run_id=1, as_of=dt.datetime(2026, 8, 25))

        result = source.fetch("AMD", ctx)

        assert result.ok
        assert result.source == "fmp"
        assert result.fields["profile"] == {"symbol": "AMD"}
        assert result.fields["quote"]["price"] == 168.5
        assert result.fields["income_statement"] == [{"revenue": 1000}]

    def test_fetch_returns_errored_factordata_on_failure(self, tmp_path):
        responses = self._responses()
        responses["/v3/profile/AMD"] = FakeResponse(status_code=500, text="boom")
        client, session = make_client(tmp_path, responses)
        source = FMPFactorSource(client)
        ctx = RunContext(run_id=1, as_of=dt.datetime(2026, 8, 25))

        result = source.fetch("AMD", ctx)

        assert not result.ok
        assert "500" in result.error
