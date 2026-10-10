import clsx from "clsx";
import type { ReactNode } from "react";

export interface Stat {
  label: string;
  /** The figure itself, set at stat size. */
  value: ReactNode;
  /** Same-baseline suffix at label size — "share", "/ 100". */
  unit?: string;
  /** A line under the value, at label size — "of portfolio". */
  hint?: string;
  tone?: "gain" | "loss" | "risk";
}

const TONE: Record<NonNullable<Stat["tone"]>, string> = {
  gain: "text-gain",
  loss: "text-loss",
  risk: "text-risk",
};

/**
 * The reference's structured stat row: a fixed set of labelled columns
 * separated by hairline rules, each one label-above-value.
 *
 * This is the fix for the run-on line the previous build used
 * ("1 sh · LIMIT $478.53 · ~$479 · 13.8% of NAV"). Scanning down a column of
 * labels is what makes numbers readable; a run-on line forces you to parse
 * separators to work out which number is which. The rules between columns
 * are the reference's, and they do real work — without them four numbers in
 * a row read as one sentence again.
 *
 * `columns` is the count at the widest breakpoint; the row collapses to two
 * columns on narrow viewports rather than shrinking four past legibility.
 */
export function StatRow({
  stats,
  columns = 4,
  className,
}: {
  stats: Stat[];
  columns?: 3 | 4;
  className?: string;
}) {
  return (
    <dl
      className={clsx(
        "grid grid-cols-2 gap-y-sp-4",
        columns === 4 ? "sm:grid-cols-4" : "sm:grid-cols-3",
        className,
      )}
    >
      {stats.map((s, i) => (
        <div
          key={s.label}
          className={clsx(
            "flex flex-col gap-sp-1 px-sp-5 first:pl-0",
            // A rule on every cell but the first in its visual row. At two
            // columns that is the odd cells; at three or four it is every
            // cell after the first.
            "border-line",
            i % 2 === 1 ? "border-l" : "",
            columns === 4
              ? "sm:[&:nth-child(4n+1)]:border-l-0 sm:[&:nth-child(n+2)]:border-l sm:[&:nth-child(4n+1)]:pl-0"
              : "sm:[&:nth-child(3n+1)]:border-l-0 sm:[&:nth-child(n+2)]:border-l sm:[&:nth-child(3n+1)]:pl-0",
          )}
        >
          <dt className="t-meta text-ink-faint">{s.label}</dt>
          <dd className="flex items-baseline gap-sp-2">
            <span className={clsx("t-stat", s.tone ? TONE[s.tone] : "text-ink")}>{s.value}</span>
            {s.unit && <span className="t-body text-ink-dim">{s.unit}</span>}
          </dd>
          {s.hint && <p className="t-meta text-ink-faint">{s.hint}</p>}
        </div>
      ))}
    </dl>
  );
}
