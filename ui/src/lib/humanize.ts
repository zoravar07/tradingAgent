/**
 * Backend enum and key names rendered for a reader.
 *
 * A naive `capitalize` turns "ai_semis" into "Ai Semis" and leaves
 * "PROFIT_BAND" shouting, so both live here rather than being re-derived
 * per screen with slightly different results.
 */

/** Tokens that are acronyms, not words, and stay upper-case. */
const ACRONYMS = new Set(["ai", "ml", "us", "eu", "pe", "etf", "gpu", "cpu", "nav", "esg"]);

/** "business_quality" → "Business quality"; "ai_semis" → "AI semis". */
export function humanizeKey(key: string): string {
  const words = key.toLowerCase().split(/[_\s]+/).filter(Boolean);
  return words
    .map((w, i) => {
      if (ACRONYMS.has(w)) return w.toUpperCase();
      return i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w;
    })
    .join(" ");
}

/** "PROFIT_BAND" → "Profit band"; "DATA_FETCH_FAILED" → "Data fetch failed". */
export function humanizeEnum(value: string): string {
  return humanizeKey(value);
}
