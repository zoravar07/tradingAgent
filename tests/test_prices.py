import pytest

from sources.prices import (
    Bar,
    atr_percentile,
    bars_from_fmp,
    compute_technical_snapshot,
    price_vs_ma_pct,
    relative_strength_pct,
    sma,
    trailing_return_pct,
    wilder_atr,
)


def make_bars(closes, high_offset=1.0, low_offset=1.0):
    return [
        Bar(date=f"2026-01-{i+1:02d}", open=c, high=c + high_offset, low=c - low_offset, close=c, volume=1000)
        for i, c in enumerate(closes)
    ]


class TestBarsFromFmp:
    def test_sorts_newest_first_payload_into_chronological_order(self):
        raw = [
            {"date": "2026-08-24", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
            {"date": "2026-08-22", "open": 1, "high": 2, "low": 0.5, "close": 1.4, "volume": 100},
            {"date": "2026-08-23", "open": 1, "high": 2, "low": 0.5, "close": 1.45, "volume": 100},
        ]
        bars = bars_from_fmp(raw)
        assert [b.date for b in bars] == ["2026-08-22", "2026-08-23", "2026-08-24"]


class TestSma:
    def test_none_until_window_filled(self):
        result = sma([1, 2, 3], window=5)
        assert result == [None, None, None]

    def test_simple_average(self):
        result = sma([1, 2, 3, 4], window=2)
        assert result == [None, 1.5, 2.5, 3.5]

    def test_rolling_window_matches_manual_calc(self):
        closes = [10, 20, 30, 40, 50]
        result = sma(closes, window=3)
        assert result == [None, None, 20, 30, 40]


class TestWilderAtr:
    def test_none_until_window_filled(self):
        bars = make_bars([100, 101, 102])
        result = wilder_atr(bars, window=14)
        assert all(v is None for v in result)

    def test_seed_value_is_plain_average_of_first_window_true_ranges(self):
        # constant high-low spread of 2.0 on every bar, no gaps -> TR is always 2.0
        bars = make_bars([100] * 14, high_offset=1.0, low_offset=1.0)
        result = wilder_atr(bars, window=14)
        assert result[13] == pytest.approx(2.0)

    def test_smooths_after_seed(self):
        bars = make_bars([100] * 15, high_offset=1.0, low_offset=1.0)
        result = wilder_atr(bars, window=14)
        # constant TR everywhere -> smoothed value stays at the seed
        assert result[14] == pytest.approx(2.0)


class TestAtrPercentile:
    def test_none_when_no_values(self):
        assert atr_percentile([None, None]) is None

    def test_latest_max_is_100th_percentile(self):
        series = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert atr_percentile(series) == 100.0

    def test_latest_min_is_low_percentile(self):
        series = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert atr_percentile(series) == pytest.approx(20.0)

    def test_ignores_leading_nones(self):
        series = [None, None, 1.0, 2.0, 3.0]
        assert atr_percentile(series) == 100.0


class TestTrailingReturn:
    def test_basic_return(self):
        closes = [100, 105, 110, 121]
        assert trailing_return_pct(closes, lookback=3) == pytest.approx(21.0)

    def test_none_when_insufficient_history(self):
        assert trailing_return_pct([100, 105], lookback=5) is None


class TestRelativeStrength:
    def test_outperformance_is_positive(self):
        ticker = [100, 110, 120, 130]  # +30%
        benchmark = [100, 102, 104, 106]  # +6%
        result = relative_strength_pct(ticker, benchmark, lookback=3)
        assert result == pytest.approx(24.0, abs=0.01)

    def test_underperformance_is_negative(self):
        ticker = [100, 95, 90, 85]
        benchmark = [100, 102, 104, 106]
        result = relative_strength_pct(ticker, benchmark, lookback=3)
        assert result < 0


class TestPriceVsMa:
    def test_above_ma_is_positive(self):
        assert price_vs_ma_pct(110, 100) == pytest.approx(10.0)

    def test_none_when_ma_missing(self):
        assert price_vs_ma_pct(110, None) is None


class TestComputeTechnicalSnapshot:
    def test_empty_bars_returns_all_none(self):
        snapshot = compute_technical_snapshot([])
        assert snapshot.last_price is None
        assert snapshot.sma_50 is None

    def test_full_snapshot_with_benchmarks(self):
        closes = [100 + i * 0.5 for i in range(210)]  # steady uptrend, 210 bars
        bars = make_bars(closes)
        spy_bars = make_bars([100 + i * 0.1 for i in range(210)])
        sector_bars = make_bars([100 + i * 0.3 for i in range(210)])

        snapshot = compute_technical_snapshot(bars, spy_bars, sector_bars)

        assert snapshot.last_price == closes[-1]
        assert snapshot.sma_50 is not None
        assert snapshot.sma_200 is not None
        assert snapshot.price_vs_sma_50_pct > 0  # uptrend, price above MA
        assert snapshot.atr_14 is not None
        assert snapshot.atr_percentile_252d is not None
        assert snapshot.relative_strength_vs_spy_pct > 0  # outperformed the slower-rising SPY series
        assert snapshot.relative_strength_vs_sector_pct > 0

    def test_snapshot_without_benchmarks_leaves_rs_none(self):
        bars = make_bars([100 + i for i in range(60)])
        snapshot = compute_technical_snapshot(bars)
        assert snapshot.relative_strength_vs_spy_pct is None
        assert snapshot.relative_strength_vs_sector_pct is None
