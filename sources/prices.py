"""Bars → ATR, moving averages, relative strength — §4's `sources/prices.py`,
feeding §5.1 Stage 1's "price vs 50/200 DMA · relative strength vs sector ETF
and SPY · ATR percentile".

Everything below is a pure function over plain float sequences — no I/O, no
network client dependency — so it's testable with hand-built price series and
doesn't need network mocking. Bars themselves come from
sources/yfinance_source.py's `YFinanceClient.get_historical_bars` (FMP's
historical-price-eod endpoint was dropped once yfinance proved to cover every
ticker for free — see sources/live_gateway.py's module docstring). Sector-ETF-
per-ticker mapping is left to the screener (step 4) to supply, since that's a
universe/config concern, not a pricing-math one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


# ------------------------------------------------------------- pure math

def sma(closes: Sequence[float], window: int) -> list[float | None]:
    """Simple moving average, aligned to `closes` (None until enough history)."""
    out: list[float | None] = []
    total = 0.0
    for i, price in enumerate(closes):
        total += price
        if i >= window:
            total -= closes[i - window]
        out.append(total / window if i >= window - 1 else None)
    return out


def true_range(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    prev_close = None
    for bar in bars:
        if prev_close is None:
            out.append(bar.high - bar.low)
        else:
            out.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
        prev_close = bar.close
    return out


def wilder_atr(bars: Sequence[Bar], window: int = 14) -> list[float | None]:
    """Average True Range with Wilder's smoothing. First `window` entries are
    None (not enough data); index `window - 1` is a plain average of the first
    `window` true ranges, every entry after that is Wilder-smoothed."""
    trs = true_range(bars)
    out: list[float | None] = [None] * len(trs)
    if len(trs) < window:
        return out
    seed = sum(trs[:window]) / window
    out[window - 1] = seed
    prev = seed
    for i in range(window, len(trs)):
        prev = (prev * (window - 1) + trs[i]) / window
        out[i] = prev
    return out


def atr_percentile(atr_series: Sequence[float | None], lookback: int = 252) -> float | None:
    """Percentile rank (0-100) of the most recent ATR value within the
    trailing `lookback` window of ATR values. None if there's no current
    value or fewer than 2 comparable values in the window."""
    values = [v for v in atr_series if v is not None]
    if not values:
        return None
    current = values[-1]
    window = values[-lookback:]
    if len(window) < 2:
        return None
    rank = sum(1 for v in window if v <= current)
    return (rank / len(window)) * 100


def trailing_return_pct(closes: Sequence[float], lookback: int) -> float | None:
    """% change from `lookback` bars ago to the most recent close."""
    if len(closes) <= lookback or lookback <= 0:
        return None
    start = closes[-lookback - 1]
    end = closes[-1]
    if start == 0:
        return None
    return (end - start) / start * 100


def relative_strength_pct(closes: Sequence[float], benchmark_closes: Sequence[float], lookback: int = 63) -> float | None:
    """Ticker's trailing return minus the benchmark's trailing return over the
    same lookback window, in percentage points. Positive = outperforming."""
    ticker_return = trailing_return_pct(closes, lookback)
    benchmark_return = trailing_return_pct(benchmark_closes, lookback)
    if ticker_return is None or benchmark_return is None:
        return None
    return ticker_return - benchmark_return


def price_vs_ma_pct(price: float, ma: float | None) -> float | None:
    if not ma:
        return None
    return (price - ma) / ma * 100


@dataclass
class TechnicalSnapshot:
    last_price: float | None
    sma_50: float | None
    sma_200: float | None
    price_vs_sma_50_pct: float | None
    price_vs_sma_200_pct: float | None
    atr_14: float | None
    atr_pct_of_price: float | None
    atr_percentile_252d: float | None
    relative_strength_vs_spy_pct: float | None
    relative_strength_vs_sector_pct: float | None


def compute_technical_snapshot(
    bars: Sequence[Bar],
    spy_bars: Sequence[Bar] | None = None,
    sector_bars: Sequence[Bar] | None = None,
    rs_lookback: int = 63,
) -> TechnicalSnapshot:
    if not bars:
        return TechnicalSnapshot(*([None] * 10))

    closes = [b.close for b in bars]
    last_price = closes[-1]
    sma_50_series = sma(closes, 50)
    sma_200_series = sma(closes, 200)
    sma_50 = sma_50_series[-1]
    sma_200 = sma_200_series[-1]
    atr_series = wilder_atr(bars, 14)
    atr_14 = atr_series[-1]

    rs_spy = rs_sector = None
    if spy_bars:
        rs_spy = relative_strength_pct(closes, [b.close for b in spy_bars], rs_lookback)
    if sector_bars:
        rs_sector = relative_strength_pct(closes, [b.close for b in sector_bars], rs_lookback)

    return TechnicalSnapshot(
        last_price=last_price,
        sma_50=sma_50,
        sma_200=sma_200,
        price_vs_sma_50_pct=price_vs_ma_pct(last_price, sma_50),
        price_vs_sma_200_pct=price_vs_ma_pct(last_price, sma_200),
        atr_14=atr_14,
        atr_pct_of_price=(atr_14 / last_price * 100) if atr_14 and last_price else None,
        atr_percentile_252d=atr_percentile(atr_series, 252),
        relative_strength_vs_spy_pct=rs_spy,
        relative_strength_vs_sector_pct=rs_sector,
    )
