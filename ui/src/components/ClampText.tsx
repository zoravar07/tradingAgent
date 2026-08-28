import { useState } from "react";

const CLAMP_CLASS: Record<number, string> = { 1: "line-clamp-1", 2: "line-clamp-2", 3: "line-clamp-3" };
// Rough char-count heuristic for "would this actually overflow" — avoids
// pulling in a ResizeObserver just to decide whether to show a toggle.
const OVERFLOW_CHARS: Record<number, number> = { 1: 80, 2: 150, 3: 220 };

/**
 * The research agent writes real paragraphs — shortening the text itself
 * would mean inventing a fake, dumbed-down thesis. So the fix lives in the
 * display: clamp to N lines by default, one tap to read the rest. Scannable
 * by default, nothing lost.
 */
export function ClampText({
  text,
  lines = 2,
  className = "",
}: {
  text: string;
  lines?: 1 | 2 | 3;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const mightOverflow = text.length > (OVERFLOW_CHARS[lines] ?? 150);

  return (
    <div>
      <p className={`${className} ${expanded ? "" : CLAMP_CLASS[lines]}`}>{text}</p>
      {mightOverflow && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="mt-1 text-xs font-medium text-[var(--color-accent)] hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
