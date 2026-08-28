import { Eye } from "@phosphor-icons/react";
import type { WatchlistItem } from "../../types/briefing";
import { EmptySection, SectionShell } from "./SectionShell";

function ProximityBadge({ pct }: { pct: number }) {
  const close = pct <= 3;
  return (
    <span
      className={`num shrink-0 rounded-md px-1.5 py-0.5 text-xs font-medium ${
        close
          ? "bg-[var(--color-risk-wash)] text-[var(--color-risk)]"
          : "bg-[var(--color-panel-raised)] text-[var(--color-ink-faint)]"
      }`}
    >
      {pct.toFixed(1)}% away
    </span>
  );
}

export function WatchingSection({ watching }: { watching: WatchlistItem[] }) {
  return (
    <SectionShell
      title="Watching"
      subtitle="Getting close to a trigger. No action needed yet."
      count={watching.length}
      icon={Eye}
    >
      {watching.length === 0 ? (
        <EmptySection label="Nothing on watch." />
      ) : (
        <div className="flex flex-col gap-2.5">
          {watching.map((w) => (
            <div key={w.ticker} className="flex items-center gap-3 text-sm">
              <span className="num w-14 shrink-0 font-semibold text-[var(--color-ink)]">{w.ticker}</span>
              <span className="flex-1 text-[var(--color-ink-dim)]">{w.reason}</span>
              {w.distance_to_trigger_pct !== null && <ProximityBadge pct={w.distance_to_trigger_pct} />}
            </div>
          ))}
        </div>
      )}
    </SectionShell>
  );
}
