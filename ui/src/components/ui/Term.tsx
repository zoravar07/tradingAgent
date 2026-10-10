/**
 * Inline jargon gloss: dotted underline, definition on hover and focus.
 * Used on a term's FIRST appearance per screen, not on every repeat —
 * dotting every instance turns the gloss into visual noise and stops it
 * reading as a definition.
 */
export function Term({ text, definition }: { text: string; definition: string }) {
  return (
    <span
      tabIndex={0}
      title={definition}
      aria-label={`${text}: ${definition}`}
      className="cursor-help underline decoration-dotted decoration-ink-faint underline-offset-[3px] transition-colors duration-[var(--dur-hover)] hover:decoration-ink-dim focus-visible:decoration-accent"
    >
      {text}
    </span>
  );
}
