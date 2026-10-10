/**
 * One place for every plain-English gloss, so the wording is identical
 * everywhere a term appears. DESIGN.md §4: every domain term gets a gloss on
 * its first appearance per screen — the UI must never assume the reader
 * already knows what a profit band is.
 *
 * Definitions describe what the mechanism actually does in this system (see
 * core/risk_rules.py's ExitTriggerType), not textbook finance.
 */
export const GLOSSARY = {
  conviction:
    "A 0-100 confidence score from the research agent. Higher means stronger evidence behind the thesis.",
  convictionFloor:
    "The lowest conviction you'll keep holding at. Drop below it and the position is sold, whatever the price is doing.",
  trailingStop:
    "A sell line that follows the price up but never back down. If the price falls far enough from its peak, the position is sold automatically.",
  profitBand:
    "A price level where the plan takes some money off the table — sell part of a winner rather than all or nothing.",
  thesisDecay:
    "Conviction has been falling run after run. The reason you bought it is holding up less well than it was.",
  nav: "Net asset value — everything your portfolio is worth, positions plus cash.",
  thesis: "The short argument for why this stock should go up.",
  bearCase: "The strongest argument against the thesis — what would have to go wrong.",
  drawdown: "How far the portfolio has fallen from its highest value so far.",
  killSwitch:
    "An automatic brake. When it trips, the system stops proposing new trades until you clear it.",
  bookValue: "The total value of everything you currently hold. Doesn't include cash.",
  limitOrder: "An order that only fills at your price or better — never worse.",
} as const;

/**
 * Trigger explanations, keyed by the ExitTriggerType values the backend
 * actually emits (agents/order_builder.py). Each is one plain sentence: what
 * fired, and why. The card headline names the trigger; this says what the
 * mechanism is.
 */
export const TRIGGER_EXPLAINERS: Record<string, string> = {
  TRAILING_STOP: "The price fell far enough from its peak to hit your trailing stop.",
  PROFIT_BAND: "The price crossed a profit-taking level, so the plan banks some of the gain.",
  THESIS_DECAY: "Conviction has been sliding for a while — the original thesis looks weaker now.",
  CONVICTION_FLOOR: "Conviction dropped below your floor, regardless of what the price is doing.",
};

/** The term whose gloss best explains each trigger, for inline definition. */
export const TRIGGER_TERMS: Record<string, { text: string; definition: string }> = {
  TRAILING_STOP: { text: "trailing stop", definition: GLOSSARY.trailingStop },
  PROFIT_BAND: { text: "profit band", definition: GLOSSARY.profitBand },
  THESIS_DECAY: { text: "thesis decay", definition: GLOSSARY.thesisDecay },
  CONVICTION_FLOOR: { text: "conviction floor", definition: GLOSSARY.convictionFloor },
};

export function explainTrigger(triggerType: string | null): string {
  if (triggerType === null) {
    return "Not an automatic exit — this is a new idea proposed on its own merits.";
  }
  return TRIGGER_EXPLAINERS[triggerType] ?? `Triggered by ${triggerType.toLowerCase().replace(/_/g, " ")}.`;
}
