"""FMPClient tests — HTTP is a fake session, never a real request. No test in
this file may hit the network or spend real FMP quota.

The stable API keys most calls by a `symbol` query param rather than a
distinct URL path per ticker, so FakeSession's responses are keyed by
resource path (e.g. "profile") when a test doesn't care which ticker was
asked for, or "resource#SYMBOL" (e.g. "quote#AMD") when a test needs
different responses for different tickers hitting the same resource.
"""

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
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params, timeout):
        self.calls.append((url, params))
        symbol = params.get("symbol")

        if symbol:
            for key, response in self.responses.items():
                if "#" not in key:
                    continue
                path_part, _, sym_part = key.rpartition("#")
                if url.endswith(path_part) and sym_part == symbol:
                    return response

        for key, response in self.responses.items():
            if "#" in key:
                continue
            if url.endswith(key):
                return response

        raise AssertionError(f"no fake response registered for {url} params={params}")


def make_client(tmp_path, responses, daily_limit=250):
    cache = FileCache(tmp_path / "cache")
    budget = DailyCallBudget(tmp_path / "budget.json", daily_limit=daily_limit, today_fn=lambda: "2026-08-25")
    session = FakeSession(responses)
    client = FMPClient(api_key="test-key", cache=cache, budget=budget, session=session)
    return client, session


class TestFMPClientBasics:
    def test_get_profile_unwraps_list(self, tmp_path):
        client, session = make_client(
            tmp_path, {"profile": FakeResponse(payload=[{"symbol": "AMD", "mktCap": 1000}])}
        )
        profile = client.get_profile("AMD")
        assert profile == {"symbol": "AMD", "mktCap": 1000}

    def test_apikey_sent_as_query_param(self, tmp_path):
        client, session = make_client(
            tmp_path, {"quote": FakeResponse(payload=[{"symbol": "AMD", "price": 150}])}
        )
        client.get_quote("AMD")
        assert session.calls[0][1]["apikey"] == "test-key"

    def test_symbol_sent_as_query_param(self, tmp_path):
        client, session = make_client(
            tmp_path, {"quote": FakeResponse(payload=[{"symbol": "AMD", "price": 150}])}
        )
        client.get_quote("AMD")
        assert session.calls[0][1]["symbol"] == "AMD"
        assert session.calls[0][0].endswith("/stable/quote")  # ticker not in the URL path

    def test_second_call_is_served_from_cache(self, tmp_path):
        client, session = make_client(
            tmp_path, {"quote": FakeResponse(payload=[{"symbol": "AMD", "price": 150}])}
        )
        client.get_quote("AMD")
        client.get_quote("AMD")
        assert len(session.calls) == 1  # second call hit the cache, no network

    def test_non_200_raises_fmp_error(self, tmp_path):
        client, session = make_client(tmp_path, {"quote": FakeResponse(status_code=404, text="not found")})
        with pytest.raises(FMPError):
            client.get_quote("BAD")

    def test_error_message_payload_raises_fmp_error(self, tmp_path):
        client, session = make_client(
            tmp_path, {"quote": FakeResponse(payload={"Error Message": "Invalid API key"})}
        )
        with pytest.raises(FMPError, match="Invalid API key"):
            client.get_quote("BAD")

    def test_failed_call_does_not_consume_budget_twice(self, tmp_path):
        # a raised FMPError still counts as one call against the budget —
        # it happened, it just wasn't useful
        client, session = make_client(tmp_path, {"quote": FakeResponse(status_code=500)}, daily_limit=1)
        with pytest.raises(FMPError):
            client.get_quote("BAD")
        assert client.budget.used_today() == 1

    def test_budget_exhaustion_prevents_further_calls(self, tmp_path):
        client, session = make_client(
            tmp_path,
            {
                "quote#AMD": FakeResponse(payload=[{"symbol": "AMD"}]),
                "quote#NVDA": FakeResponse(payload=[{"symbol": "NVDA"}]),
            },
            daily_limit=1,
        )
        client.get_quote("AMD")
        with pytest.raises(BudgetExceeded):
            client.get_quote("NVDA")

    def test_insider_trading_uses_symbol_query_param(self, tmp_path):
        client, session = make_client(
            tmp_path, {"insider-trading": FakeResponse(payload=[{"symbol": "AMD", "transactionType": "S-Sale"}])}
        )
        rows = client.get_insider_trading("AMD")
        assert rows[0]["symbol"] == "AMD"
        assert session.calls[0][1]["symbol"] == "AMD"

    def test_sp500_constituents_returns_sorted_unique_symbols(self, tmp_path):
        client, session = make_client(
            tmp_path,
            {"sp500-constituent": FakeResponse(payload=[{"symbol": "nvda"}, {"symbol": "AMD"}, {"symbol": "AMD"}])},
        )
        constituents = client.get_sp500_constituents()
        assert constituents == ["AMD", "NVDA"]

    def test_sp500_constituents_is_one_call_regardless_of_pool_size(self, tmp_path):
        client, session = make_client(
            tmp_path, {"sp500-constituent": FakeResponse(payload=[{"symbol": f"T{i}"} for i in range(500)])}
        )
        client.get_sp500_constituents()
        client.get_sp500_constituents()
        assert len(session.calls) == 1  # second call served from cache


class TestFMPFactorSource:
    def _responses(self):
        return {
            "profile": FakeResponse(payload=[{"symbol": "AMD"}]),
            "quote": FakeResponse(payload=[{"symbol": "AMD", "price": 168.5}]),
            "income-statement": FakeResponse(payload=[{"revenue": 1000}]),
            "cash-flow-statement": FakeResponse(payload=[{"freeCashFlow": 200}]),
            "earnings-surprises": FakeResponse(payload=[]),
            "analyst-estimates": FakeResponse(payload=[]),
            "price-target-summary": FakeResponse(payload=[]),
            "institutional-ownership/symbol-positions-summary": FakeResponse(payload=[]),
            "insider-trading": FakeResponse(payload=[]),
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
        responses["profile"] = FakeResponse(status_code=500, text="boom")
        client, session = make_client(tmp_path, responses)
        source = FMPFactorSource(client)
        ctx = RunContext(run_id=1, as_of=dt.datetime(2026, 8, 25))

        result = source.fetch("AMD", ctx)

        assert not result.ok
        assert "500" in result.error
