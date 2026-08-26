"""YFinanceClient tests — price_fetcher/history_fetcher are fakes throughout.
No test in this file may call the real yfinance/Yahoo Finance API."""

import pytest

from core.cache import FileCache
from sources.yfinance_source import YFinanceClient, YFinanceError


def make_client(tmp_path, price_fetcher=None, history_fetcher=None):
    cache = FileCache(tmp_path / "cache")
    calls = []

    def default_price(ticker):
        calls.append(("price", ticker))
        return 150.0

    def default_history(ticker, period):
        calls.append(("history", ticker, period))
        return [
            {"date": "2026-08-24", "open": 148.0, "high": 152.0, "low": 147.0, "close": 150.0, "volume": 1000.0},
            {"date": "2026-08-25", "open": 150.0, "high": 155.0, "low": 149.0, "close": 153.0, "volume": 1200.0},
        ]

    client = YFinanceClient(
        cache=cache,
        price_fetcher=price_fetcher or default_price,
        history_fetcher=history_fetcher or default_history,
    )
    return client, calls


class TestGetCurrentPrice:
    def test_returns_price_from_fetcher(self, tmp_path):
        client, calls = make_client(tmp_path)
        assert client.get_current_price("AMD") == 150.0

    def test_second_call_served_from_cache(self, tmp_path):
        client, calls = make_client(tmp_path)
        client.get_current_price("AMD")
        client.get_current_price("AMD")
        assert calls.count(("price", "AMD")) == 1

    def test_different_tickers_dont_share_cache(self, tmp_path):
        client, calls = make_client(tmp_path)
        client.get_current_price("AMD")
        client.get_current_price("NVDA")
        assert ("price", "AMD") in calls
        assert ("price", "NVDA") in calls

    def test_fetcher_error_propagates(self, tmp_path):
        def failing(ticker):
            raise YFinanceError(f"no data for {ticker}")

        client, calls = make_client(tmp_path, price_fetcher=failing)
        with pytest.raises(YFinanceError):
            client.get_current_price("BADTICKER")


class TestGetHistoricalBars:
    def test_returns_bars_in_chronological_order(self, tmp_path):
        client, calls = make_client(tmp_path)
        bars = client.get_historical_bars("AMD")
        assert [b.date for b in bars] == ["2026-08-24", "2026-08-25"]
        assert bars[-1].close == 153.0

    def test_second_call_served_from_cache(self, tmp_path):
        client, calls = make_client(tmp_path)
        client.get_historical_bars("AMD")
        client.get_historical_bars("AMD")
        assert calls.count(("history", "AMD", "2y")) == 1

    def test_different_periods_have_independent_cache_entries(self, tmp_path):
        client, calls = make_client(tmp_path)
        client.get_historical_bars("AMD", period="2y")
        client.get_historical_bars("AMD", period="1y")
        assert ("history", "AMD", "2y") in calls
        assert ("history", "AMD", "1y") in calls

    def test_fetcher_error_propagates(self, tmp_path):
        def failing(ticker, period):
            raise YFinanceError(f"no historical data for {ticker}")

        client, calls = make_client(tmp_path, history_fetcher=failing)
        with pytest.raises(YFinanceError):
            client.get_historical_bars("BADTICKER")

    def test_covers_a_ticker_fmp_gated_in_the_real_account(self, tmp_path):
        # this is the whole reason this module exists — confirm the client
        # works uniformly regardless of ticker "type" (ETF vs large-cap)
        client, calls = make_client(tmp_path)
        bars = client.get_historical_bars("VTI")
        assert len(bars) == 2
