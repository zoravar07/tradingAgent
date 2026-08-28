import type { Briefing } from "../../types/briefing";
import { fmtUsd } from "../../lib/format";
import { StatTile } from "../StatTile";

/**
 * The "read this in 5 seconds" row: five numbers the backend already sends
 * (nothing derived that isn't verifiable from the wire shape — "book value"
 * is a real sum of BookEntry.value_usd, not a guessed NAV, since we don't
 * have a cash dollar amount to add to it, only cash_pct).
 */
export function SummaryStrip({ briefing }: { briefing: Briefing }) {
  const bookValue = briefing.book.reduce((sum, entry) => sum + entry.value_usd, 0);
  const killTriggered = briefing.portfolio_health.kill_switch?.triggered ?? false;
  const actionsCount = briefing.actions_today.length;

  return (
    <div className="flex shrink-0 flex-wrap items-stretch divide-x divide-[var(--color-hairline)] overflow-hidden rounded-xl border border-[var(--color-hairline)] bg-[var(--color-panel)]">
      <StatTile label="Book value" value={fmtUsd(bookValue)} help="Sum of everything you currently hold — doesn't include cash." />
      <StatTile
        label="Actions today"
        value={String(actionsCount)}
        tone={actionsCount > 0 ? "accent" : undefined}
      />
      <StatTile label="Cash" value={`${briefing.portfolio_health.cash_pct.toFixed(1)}%`} />
      <StatTile
        label="Drawdown from peak"
        value={`${briefing.portfolio_health.drawdown_from_peak_pct.toFixed(1)}%`}
        tone={briefing.portfolio_health.drawdown_from_peak_pct > 0 ? "loss" : undefined}
      />
      <StatTile
        label="Kill switch"
        value={killTriggered ? "Triggered" : "OK"}
        tone={killTriggered ? "loss" : "gain"}
        help="An automatic safety brake — when triggered, the system stops proposing new trades."
      />
    </div>
  );
}
