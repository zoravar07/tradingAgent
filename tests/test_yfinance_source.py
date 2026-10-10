"""YFinanceClient tests — price_fetcher/history_fetcher are fakes throughout.
No test in this file may call the real yfinance/Yahoo Finance API."""

import pytest

from core.cache import FileCache
from sources.yfinance_source import YFinanceClient, YFinanceError


def make_client(tmp_path, price_fetcher=None, history_fetcher=None, income_fetcher=None, cash_flow_fetcher=None):
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

    def default_income(ticker):
        calls.append(("income", ticker))
        return [
            {"date": "2026-01-01", "Total Revenue": 1000.0, "Basic EPS": 2.0},
            {"date": "2025-01-01", "Total Revenue": 900.0, "Basic EPS": 1.8},
        ]

    def default_cash_flow(ticker):
        calls.append(("cashflow", ticker))
        return [
            {"date": "2026-01-01", "Free Cash Flow": 500.0},
            {"date": "2025-01-01", "Free Cash Flow": 450.0},
        ]

    client = YFinanceClient(
        cache=cache,
        price_fetcher=price_fetcher or default_price,
        history_fetcher=history_fetcher or default_history,
        income_statement_raw_fetcher=income_fetcher or default_income,
        cash_flow_raw_fetcher=cash_flow_fetcher or default_cash_flow,
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


class TestGetIncomeStatement:
    def test_returns_mapped_rows_most_recent_first(self, tmp_path):
        client, calls = make_client(tmp_path)
        rows = client.get_income_statement("AMD")
        assert rows[0]["revenue"] == 1000.0
        assert rows[0]["eps"] == 2.0
        assert rows[1]["revenue"] == 900.0

    def test_respects_limit(self, tmp_path):
        client, calls = make_client(tmp_path)
        rows = client.get_income_statement("AMD", limit=1)
        assert len(rows) == 1

    def test_second_call_served_from_cache(self, tmp_path):
        client, calls = make_client(tmp_path)
        client.get_income_statement("AMD")
        client.get_income_statement("AMD")
        assert calls.count(("income", "AMD")) == 1

    def test_fetcher_error_propagates(self, tmp_path):
        def failing(ticker):
            raise YFinanceError(f"no income statement for {ticker}")

        client, calls = make_client(tmp_path, income_fetcher=failing)
        with pytest.raises(YFinanceError):
            client.get_income_statement("BADTICKER")


class TestGetCashFlowStatement:
    def test_returns_mapped_rows_most_recent_first(self, tmp_path):
        client, calls = make_client(tmp_path)
        rows = client.get_cash_flow_statement("AMD")
        assert rows[0]["freeCashFlow"] == 500.0
        assert rows[1]["freeCashFlow"] == 450.0

    def test_respects_limit(self, tmp_path):
        client, calls = make_client(tmp_path)
        rows = client.get_cash_flow_statement("AMD", limit=1)
        assert len(rows) == 1

    def test_second_call_served_from_cache(self, tmp_path):
        client, calls = make_client(tmp_path)
        client.get_cash_flow_statement("AMD")
        client.get_cash_flow_statement("AMD")
        assert calls.count(("cashflow", "AMD")) == 1

    def test_fetcher_error_propagates(self, tmp_path):
        def failing(ticker):
            raise YFinanceError(f"no cash flow data for {ticker}")

        client, calls = make_client(tmp_path, cash_flow_fetcher=failing)
        with pytest.raises(YFinanceError):
            client.get_cash_flow_statement("BADTICKER")


class TestQuoteSnapshot:
    def test_uses_injected_fetcher_and_caches(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient

        calls = []

        def quote_fetcher(ticker):
            calls.append(ticker)
            return {"market_cap": 5e9, "three_month_avg_volume": 2_000_000.0, "last_price": 100.0, "quote_type": "EQUITY"}

        client = YFinanceClient(cache=FileCache(tmp_path / "cache"), quote_fetcher=quote_fetcher)
        snap = client.get_quote_snapshot("AMD")
        again = client.get_quote_snapshot("AMD")
        assert snap.market_cap == 5e9
        assert snap.avg_daily_volume_usd == 2_000_000.0 * 100.0
        assert again == snap
        assert calls == ["AMD"]  # second call served from cache

    def test_etf_has_no_market_cap_but_still_has_volume(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient

        client = YFinanceClient(
            cache=FileCache(tmp_path / "cache"),
            quote_fetcher=lambda t: {"market_cap": None, "three_month_avg_volume": 3e6, "last_price": 377.6, "quote_type": "ETF"},
        )
        snap = client.get_quote_snapshot("VTI")
        assert snap.market_cap is None
        assert snap.avg_daily_volume_usd == 3e6 * 377.6

    def test_missing_volume_gives_none_adv_not_zero(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient

        client = YFinanceClient(
            cache=FileCache(tmp_path / "cache"),
            quote_fetcher=lambda t: {"market_cap": 1e9, "three_month_avg_volume": None, "last_price": 10.0, "quote_type": "EQUITY"},
        )
        assert client.get_quote_snapshot("X").avg_daily_volume_usd is None


class TestPrefetchHistory:
    def _rows(self):
        return [{"date": "2026-08-25", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]

    def test_batch_fetch_populates_cache_so_per_ticker_fetch_is_never_called(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient

        per_ticker_calls = []
        batch_calls = []

        def history_fetcher(ticker, period):
            per_ticker_calls.append(ticker)
            raise AssertionError("per-ticker history should not be called after prefetch")

        def batch_fetcher(tickers, period):
            batch_calls.append((list(tickers), period))
            return {t: self._rows() for t in tickers}

        client = YFinanceClient(cache=FileCache(tmp_path / "cache"), history_fetcher=history_fetcher, batch_history_fetcher=batch_fetcher)
        cached = client.prefetch_history(["AMD", "NVDA", "SPY"])
        assert cached == 3
        assert batch_calls == [(["AMD", "NVDA", "SPY"], "2y")]
        assert client.get_historical_bars("AMD")[0].close == 1.5
        assert client.get_historical_bars("SPY")[0].close == 1.5
        assert per_ticker_calls == []

    def test_already_cached_tickers_are_skipped(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient

        batch_calls = []
        client = YFinanceClient(
            cache=FileCache(tmp_path / "cache"),
            history_fetcher=lambda t, p: self._rows(),
            batch_history_fetcher=lambda tickers, period: (batch_calls.append(list(tickers)) or {t: self._rows() for t in tickers}),
        )
        client.get_historical_bars("AMD")  # per-ticker path, now cached
        client.prefetch_history(["AMD", "NVDA"])
        assert batch_calls == [["NVDA"]]

    def test_missing_tickers_in_batch_fall_through_to_per_ticker_fetch(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient, YFinanceError

        client = YFinanceClient(
            cache=FileCache(tmp_path / "cache"),
            history_fetcher=lambda t, p: (_ for _ in ()).throw(YFinanceError(f"no history for {t}")),
            batch_history_fetcher=lambda tickers, period: {"AMD": self._rows()},  # NVDA absent
        )
        assert client.prefetch_history(["AMD", "NVDA"]) == 1
        with pytest.raises(YFinanceError):
            client.get_historical_bars("NVDA")

    def test_batch_fetcher_failure_is_swallowed_and_returns_zero(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient

        def boom(tickers, period):
            raise RuntimeError("yahoo down")

        client = YFinanceClient(cache=FileCache(tmp_path / "cache"), history_fetcher=lambda t, p: self._rows(), batch_history_fetcher=boom)
        assert client.prefetch_history(["AMD"]) == 0
        assert client.get_historical_bars("AMD")[0].close == 1.5  # per-ticker path still works


class TestPrefetchQuotes:
    def test_seeded_quotes_skip_the_fetcher(self, tmp_path):
        from core.cache import FileCache
        from sources.yfinance_source import YFinanceClient

        def boom(ticker):
            raise AssertionError("fast_info should not be called for a seeded ticker")

        client = YFinanceClient(cache=FileCache(tmp_path / "cache"), quote_fetcher=boom)
        n = client.prefetch_quotes({"amd": {"market_cap": 1e10, "three_month_avg_volume": 1e6, "last_price": 100.0, "quote_type": "EQUITY"}})
        assert n == 1
        snap = client.get_quote_snapshot("AMD")
        assert snap.market_cap == 1e10 and snap.avg_daily_volume_usd == 1e8
        assert client.prefetch_quotes({"AMD": {"market_cap": 0}}) == 0  # already cached, not overwritten
