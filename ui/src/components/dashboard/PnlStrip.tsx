import { Link } from "react-router-dom";
import clsx from "clsx";
import type { Pnl, PnlWindow } from "../../types/dashboard";
import { fmtDate, fmtPct, fmtUsd } from "../../lib/format";
import { Sparkline } from "./Sparkline";

const WINDOWS: { key: keyof Pick<Pnl, "daily" | "weekly" | "monthly">; label: string }[] = [
  { key: "daily", label: "Today" },
  { key: "weekly", label: "This week" },
  { key: "monthly", label: "This month" },
];

function Figure({ label, window }: { label: string; window: PnlWindow | null }) {
  const tone = window === null ? "text-ink-faint" : window.usd >= 0 ? "text-gain" : "text-loss";
  return (
    <div className="flex min-w-0 flex-col gap-[2px] px-sp-4 py-sp-3">
      <span className="t-meta text-ink-faint">{label}</span>
      <span className={clsx("t-stat", tone)}>{window === null ? "—" : fmtPct(window.pct)}</span>
      <span className="num-table t-meta text-ink-faint">
        {window === null ? "not enough history yet" : `${window.usd >= 0 ? "+" : "−"}${fmtUsd(Math.abs(window.usd))} since ${fmtDate(window.since)}`}
      </span>
    </div>
  );
}

/**
 * Portfolio change over three windows plus the value line, all one link to
 * the Performance page. Figures come from the pipeline's own value
 * readings; a window with no reading old enough shows a dash rather than a
 * number stretched over a shorter span.
 */
export function PnlStrip({ pnl }: { pnl: Pnl }) {
  return (
    <Link
      to="/performance"
      className="pressable flex min-w-0 flex-1 items-stretch divide-x divide-line rounded-card border border-line bg-surface shadow-card hover:border-line-strong"
      aria-label="Open the Performance page"
    >
      {WINDOWS.map((w) => (
        <Figure key={w.key} label={w.label} window={pnl[w.key]} />
      ))}
      <div className="flex min-w-0 flex-col justify-between px-sp-4 py-sp-3">
        <span className="t-meta text-ink-faint">Portfolio value</span>
        <span className="num-table t-body font-semibold text-ink">{pnl.current_nav_usd === null ? "—" : fmtUsd(pnl.current_nav_usd)}</span>
        <Sparkline values={pnl.series.map((p) => p.nav_usd)} width={120} height={26} />
      </div>
    </Link>
  );
}
