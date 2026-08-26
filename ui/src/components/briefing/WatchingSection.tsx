import type { WatchlistItem } from "../../types/briefing";
import { EmptySection, SectionShell } from "./SectionShell";

export function WatchingSection({ watching }: { watching: WatchlistItem[] }) {
  return (
    <SectionShell title="Watching" count={watching.length}>
      {watching.length === 0 ? (
        <EmptySection label="Nothing on watch." />
      ) : (
        <div className="flex flex-col gap-2">
          {watching.map((w) => (
            <div key={w.ticker} className="flex items-center gap-3 text-sm">
              <span className="num w-14 shrink-0 font-semibold text-[var(--color-ink)]">{w.ticker}</span>
              <span className="flex-1 text-[var(--color-ink-dim)]">{w.reason}</span>
              {w.distance_to_trigger_pct !== null && (
                <span className="num shrink-0 text-[var(--color-ink-faint)]">
                  {w.distance_to_trigger_pct.toFixed(1)}% away
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </SectionShell>
  );
}
