import { NewspaperClipping } from "@phosphor-icons/react";

export function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-24 text-center">
      <NewspaperClipping size={28} className="text-[var(--color-ink-faint)]" />
      <p className="text-sm font-medium text-[var(--color-ink)]">No runs yet</p>
      <p className="max-w-sm text-sm text-[var(--color-ink-dim)]">
        Z Money hasn't produced a briefing yet. Kick off a nightly run to populate this screen.
      </p>
      <code className="mt-1 rounded-md bg-[var(--color-panel-raised)] px-3 py-1.5 text-xs text-[var(--color-ink-dim)]">
        .venv/bin/python scripts/run_live_briefing.py
      </code>
    </div>
  );
}
