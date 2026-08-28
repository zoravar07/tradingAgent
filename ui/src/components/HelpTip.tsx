import { Question } from "@phosphor-icons/react";

/**
 * Inline "what does this mean" affordance for dense labels (table headers,
 * stat tiles) where a full plain-language sentence won't fit. Section-level
 * concepts get a visible subtitle instead — this is reserved for one-word
 * jargon (conviction, trailing stop, sleeve, kill switch) inside tight
 * layouts. Native title attr: no new dependency, keyboard-focusable.
 */
export function HelpTip({ text }: { text: string }) {
  return (
    <span
      tabIndex={0}
      title={text}
      aria-label={text}
      className="inline-flex shrink-0 cursor-help items-center text-[var(--color-ink-faint)] outline-none transition-colors hover:text-[var(--color-ink-dim)] focus-visible:text-[var(--color-accent)]"
    >
      <Question size={12} weight="bold" />
    </span>
  );
}
