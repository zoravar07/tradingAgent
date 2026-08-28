import { Sparkle } from "@phosphor-icons/react";
import type { ReactNode } from "react";

/**
 * Marks a screen's content as illustrative, not live data — used on
 * Positions / Research / History while their backends don't exist yet
 * (see SPEC.md §6-7). Distinct from EmptyState/ErrorPanel: this isn't
 * "nothing happened," it's "here's the shape, populated with sample
 * numbers so it's never mistaken for a real position."
 */
export function PreviewBanner({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-[var(--color-accent)]/25 bg-[var(--color-accent-wash)] p-4">
      <Sparkle size={18} weight="fill" className="mt-0.5 shrink-0 text-[var(--color-accent)]" />
      <p className="text-sm text-[var(--color-ink-dim)]">{children}</p>
    </div>
  );
}
