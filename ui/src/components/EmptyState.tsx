import { Sparkle } from "@phosphor-icons/react";

/**
 * No run has happened yet — distinct from a screen whose data is genuinely
 * empty ("nothing on watch"), which says so in place with an EmptyRow.
 */
export function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-sp-3 rounded-card border border-dashed border-line px-sp-6 py-sp-8 text-center">
      <Sparkle size={28} className="text-ink-faint" />
      <p className="t-title text-ink">No runs yet</p>
      <p className="max-w-[48ch] t-body text-ink-dim">
        Z Money hasn't produced a briefing yet. Kick off a nightly run to populate this screen.
      </p>
      <code className="mt-sp-1 rounded-inner bg-inset-strong px-sp-3 py-sp-2 t-meta text-ink-dim">
        .venv/bin/python scripts/run_live_briefing.py
      </code>
    </div>
  );
}
