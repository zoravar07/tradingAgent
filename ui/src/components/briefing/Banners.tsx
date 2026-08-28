import { Prohibit, WarningOctagon, ClockCounterClockwise } from "@phosphor-icons/react";
import type { BlockedStatus, DriftStatus, UnresearchedHolding } from "../../types/briefing";

/**
 * Three distinct banner states, all rendered with real color/border weight
 * (not just bold text) per the user's explicit request that missing
 * research coverage be "impossible to read the briefing and not notice" —
 * see core/briefing.py's BlockedStatus / UnresearchedHolding docstrings for
 * why these exist and why blocked always wins (NAV is unknown, so nothing
 * below it is trustworthy).
 */

export function BlockedBanner({ blocked }: { blocked: BlockedStatus }) {
  return (
    <div className="rounded-xl border border-[var(--color-loss)]/40 bg-[var(--color-loss-wash)] p-4">
      <div className="flex items-start gap-3">
        <Prohibit size={20} weight="fill" className="mt-0.5 shrink-0 text-[var(--color-loss)]" />
        <div className="flex-1">
          <p className="text-sm font-semibold text-[var(--color-loss)]">Run blocked — no proposals generated</p>
          <p className="mt-1 text-sm text-[var(--color-ink-dim)]">{blocked.reason}</p>
          <ul className="mt-3 flex flex-col gap-1">
            {blocked.unpriced_positions.map((u) => (
              <li key={u.ticker} className="flex gap-2 text-sm">
                <span className="num font-medium text-[var(--color-ink)]">{u.ticker}</span>
                <span className="text-[var(--color-ink-dim)]">{u.error}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function UnresearchedBanner({ holdings }: { holdings: UnresearchedHolding[] }) {
  if (holdings.length === 0) return null;
  return (
    <div className="rounded-xl border border-[var(--color-risk)]/40 bg-[var(--color-risk-wash)] p-4">
      <div className="flex items-start gap-3">
        <WarningOctagon size={20} weight="fill" className="mt-0.5 shrink-0 text-[var(--color-risk)]" />
        <div className="flex-1">
          <p className="text-sm font-semibold text-[var(--color-risk)]">
            No research coverage — {holdings.length} held position{holdings.length === 1 ? "" : "s"} unmonitored this run
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink-dim)]">
            No fresh research on these — no decay warning, no smart stop or profit target. Treat them
            as unreviewed, not safe.
          </p>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
            {holdings.map((u) => (
              <li key={u.ticker} className="flex gap-2 text-sm">
                <span className="num font-medium text-[var(--color-ink)]">{u.ticker}</span>
                <span className="text-[var(--color-ink-dim)]">{u.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function DriftBanner({ drift }: { drift: DriftStatus }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-[var(--color-hairline-strong)] bg-[var(--color-panel-raised)] px-4 py-3">
      <ClockCounterClockwise size={18} className="shrink-0 text-[var(--color-ink-dim)]" />
      <p className="text-sm text-[var(--color-ink-dim)]">
        {drift.last_import_at === null ? (
          <>Positions have never been imported from a broker CSV.</>
        ) : (
          <>
            Last import was{" "}
            <span className="num text-[var(--color-ink)]">{drift.days_since_import?.toFixed(1)}</span> days ago
            (threshold {drift.threshold_days}). Positions may be stale.
          </>
        )}
      </p>
    </div>
  );
}
