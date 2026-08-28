import { WarningOctagon } from "@phosphor-icons/react";
import type { BookEntry } from "../../types/briefing";
import { fmtPct, fmtUsd } from "../../lib/format";
import { StatusPill } from "../StatusPill";
import { HelpTip } from "../HelpTip";
import { EmptySection, SectionShell } from "./SectionShell";

function ConvictionCell({ entry }: { entry: BookEntry }) {
  const { conviction_now, conviction_at_entry, no_research_coverage } = entry;

  if (conviction_now !== null && conviction_at_entry !== null) {
    return (
      <span className="num text-[var(--color-ink)]">
        {conviction_now.toFixed(0)}{" "}
        <span className="text-[var(--color-ink-faint)]">(was {conviction_at_entry.toFixed(0)})</span>
      </span>
    );
  }
  if (conviction_now !== null) {
    return (
      <span className="num text-[var(--color-ink)]">
        {conviction_now.toFixed(0)} <span className="text-[var(--color-ink-faint)]">(no baseline)</span>
      </span>
    );
  }
  // Bug fix: conviction_at_entry used to be silently dropped here whenever
  // conviction_now was null but an entry score still existed — the "was X"
  // history disappeared even though the data was right there.
  if (conviction_at_entry !== null) {
    return (
      <span className="num text-[var(--color-ink-faint)]">
        — <span>(was {conviction_at_entry.toFixed(0)})</span>
      </span>
    );
  }
  if (no_research_coverage) {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap text-[var(--color-risk)]">
        <WarningOctagon size={13} weight="fill" />
        no coverage
      </span>
    );
  }
  return <span className="text-[var(--color-ink-faint)]">n/a</span>;
}

function BookRow({ entry }: { entry: BookEntry }) {
  const pnlTone = entry.unrealized_pnl_pct >= 0 ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]";
  const stopBreached =
    entry.distance_to_trailing_stop_pct !== null && entry.distance_to_trailing_stop_pct <= 0;
  const needsAttention = stopBreached || entry.has_exit_trigger;

  return (
    <tr className={`border-b border-[var(--color-hairline)] last:border-0 ${needsAttention ? "bg-[var(--color-loss-wash)]/40" : ""}`}>
      <td className="py-2.5 pr-4">
        <div className="flex items-center gap-2">
          <span className="num font-semibold text-[var(--color-ink)]">{entry.ticker}</span>
          {entry.has_exit_trigger && <StatusPill tone="loss">exit triggered</StatusPill>}
        </div>
      </td>
      <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{entry.qty.toLocaleString()}</td>
      <td className="num py-2.5 pr-4 text-[var(--color-ink)]">{fmtUsd(entry.value_usd)}</td>
      <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{entry.weight_pct.toFixed(1)}%</td>
      <td className={`num py-2.5 pr-4 font-medium ${pnlTone}`}>{fmtPct(entry.unrealized_pnl_pct)}</td>
      <td className="py-2.5 pr-4">
        <ConvictionCell entry={entry} />
      </td>
      <td className={`num py-2.5 pr-4 ${stopBreached ? "font-medium text-[var(--color-loss)]" : "text-[var(--color-ink-faint)]"}`}>
        {entry.distance_to_trailing_stop_pct !== null ? `${entry.distance_to_trailing_stop_pct.toFixed(1)}%` : "—"}
      </td>
      <td className="num py-2.5 text-[var(--color-ink-faint)]">
        {entry.next_profit_band_pct !== null ? `${entry.next_profit_band_pct.toFixed(1)}%` : "—"}
      </td>
    </tr>
  );
}

export function BookSection({ book }: { book: BookEntry[] }) {
  return (
    <SectionShell title="Your book" subtitle="Every position you're currently holding." count={book.length}>
      {book.length === 0 ? (
        <EmptySection label="No open positions." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-[var(--color-hairline-strong)] text-left text-xs text-[var(--color-ink-faint)]">
                <th className="pb-2 pr-4 font-medium whitespace-nowrap">Ticker</th>
                <th className="pb-2 pr-4 font-medium whitespace-nowrap">Qty</th>
                <th className="pb-2 pr-4 font-medium whitespace-nowrap">Value</th>
                <th className="pb-2 pr-4 font-medium whitespace-nowrap">Weight</th>
                <th className="pb-2 pr-4 font-medium whitespace-nowrap">P&amp;L</th>
                <th className="pb-2 pr-4 font-medium whitespace-nowrap">
                  <span className="inline-flex items-center gap-1">
                    Conviction
                    <HelpTip text="Current confidence score (0–100), and what it was when the position was opened." />
                  </span>
                </th>
                <th className="pb-2 pr-4 font-medium whitespace-nowrap">
                  <span className="inline-flex items-center gap-1">
                    To trailing stop
                    <HelpTip text="How far the price can drop before the stop-loss sells it automatically. 0% or below means the stop already triggered." />
                  </span>
                </th>
                <th className="pb-2 font-medium whitespace-nowrap">
                  <span className="inline-flex items-center gap-1">
                    Next profit band
                    <HelpTip text="Distance to the next price level where the plan calls for trimming some profit." />
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {book.map((entry) => (
                <BookRow key={entry.ticker} entry={entry} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}
