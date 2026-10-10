import type { Tile } from "../../types/dashboard";
import { fmtPctPlain } from "../../lib/format";
import { Sparkline } from "./Sparkline";

function formatValue(tile: Tile): string {
  if (tile.unit === "$") return `$${tile.value.toFixed(2)}`;
  if (tile.unit === "%") return fmtPctPlain(tile.value);
  return tile.value.toLocaleString("en-US");
}

/**
 * One compact metric: label, figure, a hint, and the trend across recent
 * runs. The spend tile has no per-run series — the counter is monthly — so
 * it shows progress against the cap instead of pretending to have one.
 */
export function MetricTile({ tile }: { tile: Tile }) {
  const isSpend = tile.key === "api_spend_mtd";
  const pct = isSpend && tile.cap ? Math.min(100, (tile.value / tile.cap) * 100) : null;
  return (
    <div className="flex flex-col gap-sp-2 rounded-card border border-line bg-surface px-sp-4 py-sp-3 shadow-card">
      <p className="t-meta text-ink-faint">{tile.label}</p>
      <div className="flex items-end justify-between gap-sp-3">
        <p className="t-stat text-ink">{formatValue(tile)}</p>
        {!isSpend && <Sparkline values={tile.series.map((p) => p.value)} />}
      </div>
      {isSpend && pct !== null ? (
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-conviction-track"
          role="meter"
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${tile.label} ${Math.round(pct)}% of cap`}
        >
          <div className={`h-full rounded-full ${pct >= 80 ? "bg-risk" : "bg-accent"}`} style={{ width: `${pct}%` }} />
        </div>
      ) : null}
      <p className="t-meta text-ink-faint">
        {tile.hint}
        {isSpend && tile.fmp_calls_today !== undefined ? ` · FMP ${tile.fmp_calls_today} calls today` : ""}
      </p>
    </div>
  );
}
