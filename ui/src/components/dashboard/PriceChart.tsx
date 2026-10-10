import clsx from "clsx";
import { useEffect, useState } from "react";
import { ApiError, fetchPrices } from "../../api/client";
import type { PriceBar, PriceRange, PricesResponse } from "../../types/dashboard";
import { fmtDate, fmtPct, fmtUsd2 } from "../../lib/format";
import { companyName } from "../../lib/tickers";

const RANGES: PriceRange[] = ["1W", "1M", "3M", "1Y"];
const W = 640;
const H = 168;
const PAD = { top: 8, right: 50, bottom: 20, left: 4 };
const VOLUME_H = 26;

type Loaded = { kind: "loaded"; data: PricesResponse; ticker: string; range: PriceRange };
type Failed = { kind: "error"; message: string; ticker: string; range: PriceRange };

/**
 * Daily OHLC candles with a volume strip, from the bars the last run priced
 * against. Up candles use the gain color and down candles the loss color —
 * that is the one place a status color is the data, not decoration. There
 * is no 1D: intraday bars are not stored, so the toggle says so instead of
 * drawing something that isn't there.
 */
export function PriceChart({ ticker, name }: { ticker: string | null; name?: string | null }) {
  const [range, setRange] = useState<PriceRange>("1M");
  const [result, setResult] = useState<Loaded | Failed | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  // "Loading" is derived: a result for a different ticker/range is stale.
  // The effect only touches state after the fetch resolves — the same
  // external-system rule useAsyncData follows.
  const current = result && result.ticker === ticker && result.range === range ? result : null;
  const state = current ?? ({ kind: "loading" } as const);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    const wanted = { ticker, range };
    void (async () => {
      try {
        const data = await fetchPrices(ticker, range);
        if (!cancelled) setResult({ kind: "loaded", data, ...wanted });
      } catch (err) {
        if (!cancelled) {
          setResult({ kind: "error", message: err instanceof ApiError ? err.message : "Couldn't load prices.", ...wanted });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, range]);

  if (!ticker) {
    return <p className="px-sp-5 py-sp-6 t-body text-ink-faint">Select a name to see its chart.</p>;
  }

  const bars = state.kind === "loaded" ? state.data.bars : [];
  const last = bars[bars.length - 1];
  const first = bars[0];
  const changePct = last && first && first.close ? ((last.close - first.close) / first.close) * 100 : null;

  return (
    <div className="flex flex-col gap-sp-2 px-sp-5 py-sp-3">
      <div className="flex flex-wrap items-start justify-between gap-sp-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-sp-3">
            <p className="t-title text-ink">{ticker}</p>
            {last && (
              <>
                <span className="num-table t-title text-ink">{fmtUsd2(last.close)}</span>
                {changePct !== null && (
                  <span className={clsx("num-table t-meta font-medium", changePct >= 0 ? "text-gain" : "text-loss")}>
                    {fmtPct(changePct, 2)} over {range}
                  </span>
                )}
              </>
            )}
          </div>
          {(name ?? companyName(ticker)) && <p className="t-meta text-ink-faint">{name ?? companyName(ticker)}</p>}
        </div>
        <div className="flex items-center gap-sp-1 rounded-inner bg-inset p-[3px]" role="tablist" aria-label="Timeframe">
          <button
            type="button"
            disabled
            title="Intraday bars aren't stored — only daily closes from the nightly run."
            className="rounded-chip px-sp-2 py-[3px] t-meta text-ink-faint opacity-50"
          >
            1D
          </button>
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              role="tab"
              aria-selected={r === range}
              onClick={() => setRange(r)}
              className={clsx(
                "pressable rounded-chip px-sp-2 py-[3px] t-meta font-medium",
                r === range ? "bg-ink text-canvas" : "text-ink-dim hover:text-ink",
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {state.kind === "loading" && <div className="h-[168px] animate-pulse rounded-inner bg-inset" />}
      {state.kind === "error" && (
        <div className="flex h-[168px] items-center justify-center rounded-inner border border-dashed border-line">
          <p className="max-w-[40ch] text-center t-meta text-ink-faint">{state.message}</p>
        </div>
      )}
      {state.kind === "loaded" && bars.length > 0 && (
        <Candles bars={bars} hover={hover} setHover={setHover} />
      )}
      {state.kind === "loaded" && (
        <p className="t-meta text-ink-faint">
          Daily closes, {bars.length} sessions{state.data.as_of ? `, as of ${fmtDate(state.data.as_of)}` : ""}. Not live.
        </p>
      )}
    </div>
  );
}

function Candles({ bars, hover, setHover }: { bars: PriceBar[]; hover: number | null; setHover: (i: number | null) => void }) {
  const plotW = W - PAD.left - PAD.right;
  const priceH = H - PAD.top - PAD.bottom - VOLUME_H - 6;
  const lo = Math.min(...bars.map((b) => b.low));
  const hi = Math.max(...bars.map((b) => b.high));
  const span = hi - lo || 1;
  const vMax = Math.max(...bars.map((b) => b.volume)) || 1;
  const slot = plotW / bars.length;
  const bodyW = Math.max(2, Math.min(10, slot * 0.6));
  const sx = (i: number) => PAD.left + slot * (i + 0.5);
  const sy = (p: number) => PAD.top + (1 - (p - lo) / span) * priceH;
  const volTop = PAD.top + priceH + 6;
  const ticks = [lo, lo + span / 2, hi];
  const labelEvery = Math.max(1, Math.round(bars.length / 4));
  const active = hover === null ? null : bars[hover];

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Daily price candles, ${bars.length} sessions`} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={sy(t)} y2={sy(t)} stroke="var(--color-line)" strokeWidth="1" />
            <text x={W - PAD.right + 8} y={sy(t)} dominantBaseline="middle" fill="var(--color-ink-faint)" fontSize="11" style={{ fontVariantNumeric: "tabular-nums" }}>
              {t.toFixed(t >= 100 ? 0 : 2)}
            </text>
          </g>
        ))}
        {bars.map((b, i) => {
          const up = b.close >= b.open;
          const color = up ? "var(--color-gain)" : "var(--color-loss)";
          const top = sy(Math.max(b.open, b.close));
          const bottom = sy(Math.min(b.open, b.close));
          return (
            <g key={b.date}>
              <line x1={sx(i)} x2={sx(i)} y1={sy(b.high)} y2={sy(b.low)} stroke={color} strokeWidth="1" />
              <rect x={sx(i) - bodyW / 2} y={top} width={bodyW} height={Math.max(1, bottom - top)} fill={color} rx="1" />
              <rect x={sx(i) - bodyW / 2} y={volTop + VOLUME_H * (1 - b.volume / vMax)} width={bodyW} height={VOLUME_H * (b.volume / vMax)} fill={color} opacity="0.28" />
              <rect x={sx(i) - slot / 2} y={PAD.top} width={slot} height={H - PAD.top - PAD.bottom} fill="transparent" onMouseEnter={() => setHover(i)} />
              {i % labelEvery === 0 && (
                <text x={sx(i)} y={H - 6} textAnchor="middle" fill="var(--color-ink-faint)" fontSize="11">
                  {new Date(b.date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                </text>
              )}
            </g>
          );
        })}
        {hover !== null && (
          <line x1={sx(hover)} x2={sx(hover)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--color-ink-faint)" strokeDasharray="3 3" />
        )}
      </svg>
      {active && hover !== null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-inner border border-line bg-surface px-sp-3 py-sp-2 shadow-card"
          style={{ left: `${(sx(hover) / W) * 100}%`, top: 0 }}
        >
          <p className="t-meta font-medium text-ink">{fmtDate(active.date)}</p>
          <p className="num-table t-meta text-ink-dim">
            O {active.open.toFixed(2)} · H {active.high.toFixed(2)} · L {active.low.toFixed(2)} · C {active.close.toFixed(2)}
          </p>
          <p className="num-table t-meta text-ink-faint">Vol {Math.round(active.volume).toLocaleString("en-US")}</p>
        </div>
      )}
    </div>
  );
}
