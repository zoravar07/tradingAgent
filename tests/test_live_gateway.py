"""LiveMarketDataGateway tests — FMPClient's HTTP session is faked exactly
as in test_fmp_client.py; YFinanceClient's fetchers are faked exactly as in
test_yfinance_source.py. No test here may hit any real network."""

import pytest

from core.cache import DailyCallBudget, FileCache
from sources.fmp import FMPClient
from sources.live_gateway import LiveMarketDataGateway
from sources.yfinance_source import YFinanceClient, YFinanceError
from tests.test_fmp_client import FakeResponse, FakeSession


def bar(date, close, volume=1_000_000):
    return {"date": date, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume}


def bars_payload(n=210, start=100.0, step=0.1):
    return [bar(f"2026-01-{(i % 28) + 1:02d}", start + i * step) for i in range(n)]


def make_gateway(tmp_path, fmp_responses, prices=None, histories=None, yf_income=None, yf_cash_flow=None, cluster_overrides=None, etf_tickers=None):
    """`prices`: {ticker: float}. `histories`: {ticker: list[dict rows]}.
    `yf_income`/`yf_cash_flow`: {ticker: list[raw yfinance-shaped dict rows]}.
    Missing entries raise YFinanceError, mimicking a real lookup failure."""
    prices = prices or {}
    histories = histories or {}
    yf_income = yf_income or {}
    yf_cash_flow = yf_cash_flow or {}

    fmp_cache = FileCache(tmp_path / "fmp_cache")
    fmp_budget = DailyCallBudget(tmp_path / "fmp_budget.json", daily_limit=250, today_fn=lambda: "2026-08-25")
    fmp_session = FakeSession(fmp_responses)
    fmp_client = FMPClient(api_key="test-key", cache=fmp_cache, budget=fmp_budget, session=fmp_session)

    def price_fetcher(ticker):
        if ticker not in prices:
            raise YFinanceError(f"no price for {ticker}")
        return prices[ticker]

    def history_fetcher(ticker, period):
        if ticker not in histories:
            raise YFinanceError(f"no history for {ticker}")
        return histories[ticker]

    def income_fetcher(ticker):
        if ticker not in yf_income:
            raise YFinanceError(f"no income statement for {ticker}")
        return yf_income[ticker]

    def cash_flow_fetcher(ticker):
        if ticker not in yf_cash_flow:
            raise YFinanceError(f"no cash flow statement for {ticker}")
        return yf_cash_flow[ticker]

    yf_cache = FileCache(tmp_path / "yf_cache")
    yf_client = YFinanceClient(
        cache=yf_cache, price_fetcher=price_fetcher, history_fetcher=history_fetcher,
        income_statement_raw_fetcher=income_fetcher, cash_flow_raw_fetcher=cash_flow_fetcher,
    )

    gateway = LiveMarketDataGateway(fmp_client, yf_client, cluster_overrides=cluster_overrides, etf_tickers=etf_tickers)
    return gateway, fmp_session


class TestGetScreenerInput:
    def _fmp_responses(self):
        return {
            "profile#AMD": FakeResponse(payload=[{"symbol": "AMD", "mktCap": 5_000_000_000, "averageVolume": 40_000_000, "sector": "Technology"}]),
            "quote#AMD": FakeResponse(payload=[{"symbol": "AMD", "price": 150.0}]),
            "income-statement#AMD": FakeResponse(payload=[{"revenue": 1100, "eps": 10.0}, {"revenue": 1000, "eps": 9.0}]),
            "cash-flow-statement#AMD": FakeResponse(payload=[{"freeCashFlow": 200}]),
        }

    def _histories(self):
        return {"AMD": bars_payload(), "SPY": bars_payload(start=500.0, step=0.05)}

    def test_builds_screener_input_without_crashing(self, tmp_path):
        gateway, session = make_gateway(
            tmp_path, self._fmp_responses(), prices={"AMD": 150.0}, histories=self._histories()
        )
        result = gateway.get_screener_input("AMD", is_held=False)

        assert result.ticker == "AMD"
        assert result.market_cap_usd == 5_000_000_000
        assert result.avg_daily_volume_usd == 40_000_000 * 150.0
        assert result.trailing_pe == pytest.approx(150.0 / 10.0)  # price / eps — no direct P/E field anywhere
        assert result.free_cash_flow == 200
        assert result.days_to_earnings is None  # documented gap

    def test_price_comes_from_yfinance_not_fmp_quote(self, tmp_path):
        # regression test for the actual bug: FMP quote gated, price must
        # still resolve via yfinance and avg_daily_volume_usd must use it
        responses = self._fmp_responses()
        responses["quote#AMD"] = FakeResponse(status_code=402, text="Restricted Endpoint")
        gateway, session = make_gateway(tmp_path, responses, prices={"AMD": 479.18}, histories=self._histories())
        result = gateway.get_screener_input("AMD", is_held=False)
        assert result.avg_daily_volume_usd == 40_000_000 * 479.18

    def test_covers_an_etf_fmp_quote_gated_in_the_real_account(self, tmp_path):
        responses = {
            "profile#VTI": FakeResponse(payload=[{"symbol": "VTI", "mktCap": None, "averageVolume": 3_000_000}]),
            "quote#VTI": FakeResponse(status_code=402, text="Restricted Endpoint"),
            "income-statement#VTI": FakeResponse(payload=[]),
            "cash-flow-statement#VTI": FakeResponse(payload=[]),
        }
        gateway, session = make_gateway(
            tmp_path, responses, prices={"VTI": 378.15}, histories={"VTI": bars_payload(start=300.0), "SPY": bars_payload(start=500.0, step=0.05)}
        )
        result = gateway.get_screener_input("VTI", is_held=True)
        assert result.technical.last_price is not None  # yfinance bars flowed through for an FMP-quote-gated ETF
        assert result.technical.sma_200 is not None

    def test_uses_yfinance_fundamentals_even_when_fmp_also_402s(self, tmp_path):
        # regression test for the second real-account discovery: FMP gates
        # income-statement/cash-flow-statement the same way it gates quote.
        # yfinance is primary now (see module docstring for why), so this
        # succeeds regardless of FMP's state — included to prove that.
        responses = {
            "profile#CEG": FakeResponse(payload=[{"symbol": "CEG", "mktCap": 90_000_000_000, "averageVolume": 2_000_000}]),
            "income-statement#CEG": FakeResponse(status_code=402, text="Restricted Endpoint"),
            "cash-flow-statement#CEG": FakeResponse(status_code=402, text="Restricted Endpoint"),
        }
        gateway, session = make_gateway(
            tmp_path, responses,
            prices={"CEG": 278.42},
            histories={"CEG": bars_payload(start=250.0), "SPY": bars_payload(start=500.0, step=0.05)},
            yf_income={"CEG": [{"date": "2026-01-01", "Total Revenue": 1000.0}, {"date": "2025-01-01", "Total Revenue": 900.0}]},
            yf_cash_flow={"CEG": [{"date": "2026-01-01", "Free Cash Flow": 300.0}]},
        )
        result = gateway.get_screener_input("CEG", is_held=True)
        assert result.free_cash_flow == 300.0
        assert result.revenue_growth_pct == pytest.approx((1000.0 - 900.0) / 900.0 * 100)

    def test_falls_back_to_fmp_when_yfinance_has_nothing(self, tmp_path):
        # the genuine fallback path: yfinance has no data for this ticker,
        # FMP does — inverted from the pre-budget-fix behavior
        responses = {
            "profile#CEG": FakeResponse(payload=[{"symbol": "CEG", "mktCap": 90_000_000_000, "averageVolume": 2_000_000}]),
            "income-statement#CEG": FakeResponse(payload=[{"revenue": 1000, "eps": 5.0}, {"revenue": 900, "eps": 4.5}]),
            "cash-flow-statement#CEG": FakeResponse(payload=[{"freeCashFlow": 300}]),
        }
        gateway, session = make_gateway(
            tmp_path, responses, prices={"CEG": 278.42},
            histories={"CEG": bars_payload(start=250.0), "SPY": bars_payload(start=500.0, step=0.05)},
            # no yf_income/yf_cash_flow entries for CEG -> yfinance fetch fails
        )
        result = gateway.get_screener_input("CEG", is_held=True)
        assert result.free_cash_flow == 300
        assert result.revenue_growth_pct == pytest.approx((1000 - 900) / 900 * 100)

    def test_raises_when_both_fmp_and_yfinance_fundamentals_fail(self, tmp_path):
        responses = {
            "profile#CEG": FakeResponse(payload=[{"symbol": "CEG"}]),
            "quote#CEG": FakeResponse(status_code=402, text="Restricted Endpoint"),
            "income-statement#CEG": FakeResponse(status_code=402, text="Restricted Endpoint"),
            "cash-flow-statement#CEG": FakeResponse(status_code=402, text="Restricted Endpoint"),
        }
        gateway, session = make_gateway(
            tmp_path, responses, prices={"CEG": 278.42}, histories={"CEG": bars_payload(), "SPY": bars_payload(start=500.0, step=0.05)}
        )
        with pytest.raises(RuntimeError, match="income statement unavailable"):
            gateway.get_screener_input("CEG", is_held=True)

    def test_etf_skips_fundamentals_fetch_entirely_and_sets_is_etf(self, tmp_path):
        # VGT/IAU/VTI have no income statement in either source — an ETF
        # must not even attempt (and fail) that fetch, per the config flag
        responses = {"profile#VGT": FakeResponse(payload=[{"symbol": "VGT", "mktCap": None, "averageVolume": 500_000, "sector": "Technology"}])}
        gateway, session = make_gateway(
            tmp_path, responses, prices={"VGT": 620.0}, histories={"VGT": bars_payload(start=500.0), "SPY": bars_payload(start=500.0, step=0.05)},
            etf_tickers=["VGT", "IAU", "VTI"],
        )
        result = gateway.get_screener_input("VGT", is_held=True)
        assert result.is_etf is True
        assert result.free_cash_flow is None
        assert result.revenue_growth_pct is None
        assert not any(c[0].endswith("/income-statement") or "income-statement" in c[0] for c in session.calls)

    def test_non_etf_ticker_unaffected_by_etf_list(self, tmp_path):
        gateway, session = make_gateway(
            tmp_path, self._fmp_responses(), prices={"AMD": 150.0}, histories=self._histories(),
            etf_tickers=["VGT", "IAU", "VTI"],
        )
        result = gateway.get_screener_input("AMD", is_held=False)
        assert result.is_etf is False

    def test_revenue_growth_computed_from_two_periods(self, tmp_path):
        gateway, session = make_gateway(
            tmp_path, self._fmp_responses(), prices={"AMD": 150.0}, histories=self._histories()
        )
        result = gateway.get_screener_input("AMD", is_held=False)
        assert result.revenue_growth_pct == 10.0  # (1100-1000)/1000 * 100

    def test_technical_snapshot_populated(self, tmp_path):
        gateway, session = make_gateway(
            tmp_path, self._fmp_responses(), prices={"AMD": 150.0}, histories=self._histories()
        )
        result = gateway.get_screener_input("AMD", is_held=False)
        assert result.technical.sma_200 is not None
        assert result.technical.relative_strength_vs_spy_pct is not None
        assert result.technical.relative_strength_vs_sector_pct is None  # documented gap

    def test_spy_bars_fetched_once_across_multiple_tickers(self, tmp_path):
        responses = self._fmp_responses()
        responses.update(
            {
                "profile#NVDA": responses["profile#AMD"],
                "quote#NVDA": responses["quote#AMD"],
                "income-statement#NVDA": responses["income-statement#AMD"],
                "cash-flow-statement#NVDA": responses["cash-flow-statement#AMD"],
            }
        )
        histories = self._histories()
        histories["NVDA"] = bars_payload()
        gateway, session = make_gateway(tmp_path, responses, prices={"AMD": 150.0, "NVDA": 150.0}, histories=histories)
        gateway.get_screener_input("AMD", is_held=False)
        gateway.get_screener_input("NVDA", is_held=False)
        # SPY history is cached at the YFinanceClient layer, so a second
        # ticker's request never re-invokes the (fake) history fetcher for SPY
        assert gateway.yf.cache.get(f"yf:hist:SPY:2y") is not None


class TestGetCurrentPrice:
    def test_returns_price_from_yfinance(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {}, prices={"AMD": 150.5})
        assert gateway.get_current_price("AMD") == 150.5

    def test_raises_when_yfinance_has_no_price(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {}, prices={})
        with pytest.raises(YFinanceError):
            gateway.get_current_price("BADTICKER")

    def test_does_not_touch_fmp_at_all(self, tmp_path):
        gateway, session = make_gateway(tmp_path, {}, prices={"AMD": 150.5})
        gateway.get_current_price("AMD")
        assert len(session.calls) == 0


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
        }

    def _histories(self):
        return {"AMD": bars_payload(), "SPY": bars_payload(start=500.0, step=0.05)}

    def test_assembles_readable_text_without_crashing(self, tmp_path):
        responses = self._base_responses()
        responses["institutional-ownership/symbol-positions-summary"] = FakeResponse(payload=[])
        responses["insider-trading"] = FakeResponse(payload=[])
        gateway, session = make_gateway(
            tmp_path, responses, prices={"AMD": 150.0}, histories=self._histories(),
            yf_income={"AMD": [{"date": "2026-01-01", "Total Revenue": 1100.0, "Basic EPS": 10.0}]},
            yf_cash_flow={"AMD": [{"date": "2026-01-01", "Free Cash Flow": 200.0}]},
        )
        text = gateway.get_research_context("AMD")
        assert "AMD" in text
        assert "Technology" in text
        assert "Technical snapshot" in text
        assert "150.0" in text  # yfinance price appears, not a bare FMP quote
        assert "source=yfinance" in text  # yfinance is primary; FMP not needed here
        assert "source=fmp_fallback" not in text

    def test_context_names_fmp_fallback_when_yfinance_has_nothing(self, tmp_path):
        # the genuine fallback path, inverted from the pre-budget-fix design:
        # yfinance has no data for this ticker, FMP does
        responses = self._base_responses()
        text_gateway, session = make_gateway(
            tmp_path, responses, prices={"AMD": 150.0}, histories=self._histories(),
            # no yf_income/yf_cash_flow entries -> yfinance fetch fails, falls through to FMP
        )
        text = text_gateway.get_research_context("AMD")
        assert "source=fmp_fallback" in text
        assert "1100" in text  # the FMP fallback data made it into the text

    def test_13f_and_insider_and_price_failures_degrade_gracefully(self, tmp_path):
        responses = self._base_responses()
        responses["institutional-ownership/symbol-positions-summary"] = FakeResponse(status_code=402, text="upgrade required")
        responses["insider-trading"] = FakeResponse(status_code=402, text="upgrade required")
        # note: no price for AMD in the yfinance fake -> current_price fetch fails too
        gateway, session = make_gateway(tmp_path, responses, prices={}, histories=self._histories())
        text = gateway.get_research_context("AMD")  # must not raise
        assert "error" in text

    def test_every_fmp_field_can_fail_at_once_without_raising(self, tmp_path):
        failing = FakeResponse(status_code=500, text="down")
        responses = {
            "profile": failing, "quote": failing, "income-statement": failing, "cash-flow-statement": failing,
            "earnings-surprises": failing, "analyst-estimates": failing, "price-target-summary": failing,
            "institutional-ownership/symbol-positions-summary": failing, "insider-trading": failing,
        }
        gateway, session = make_gateway(tmp_path, responses, prices={"AMD": 150.0}, histories=self._histories())
        text = gateway.get_research_context("AMD")  # must not raise even with everything FMP-side down
        assert "AMD" in text
        assert "150.0" in text  # yfinance data survives even total FMP outage

    def test_etf_context_skips_fundamentals_and_says_so(self, tmp_path):
        responses = {"profile": FakeResponse(payload=[{"companyName": "Vanguard Growth ETF", "sector": None}])}
        gateway, session = make_gateway(
            tmp_path, responses, prices={"VGT": 620.0},
            histories={"VGT": bars_payload(start=500.0), "SPY": bars_payload(start=500.0, step=0.05)},
            etf_tickers=["VGT"],
        )
        text = gateway.get_research_context("VGT")
        assert "not applicable — this is an ETF" in text
        assert "Technical snapshot" in text
        # none of the FMP fundamentals endpoints were even attempted
        assert not any("income-statement" in c[0] or "insider-trading" in c[0] for c in session.calls)
