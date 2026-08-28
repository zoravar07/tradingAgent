import type { OvernightChange } from "../../types/briefing";
import { EmptySection, SectionShell } from "./SectionShell";

export function OvernightSection({ changes }: { changes: OvernightChange[] }) {
  return (
    <SectionShell
      title="Overnight changes"
      subtitle="News and moves on what you already own."
      count={changes.length}
    >
      {changes.length === 0 ? (
        <EmptySection label="Nothing material overnight." />
      ) : (
        <div className="flex flex-col gap-2">
          {changes.map((c, i) => (
            <div key={`${c.ticker}-${i}`} className="flex items-start gap-3 text-sm">
              <span className="num w-14 shrink-0 font-semibold text-[var(--color-ink)]">{c.ticker}</span>
              <span className="flex-1 text-[var(--color-ink-dim)]">{c.summary}</span>
            </div>
          ))}
        </div>
      )}
    </SectionShell>
  );
}
