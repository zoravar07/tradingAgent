/**
 * Sample data for the Positions / Research / History stubs — none of these
 * screens have a backend yet (only /api/briefing/latest and /api/config
 * exist, see api/routes/). Shaped to match SPEC.md §6's actual table
 * columns, not invented fields, so the preview is honest about what's
 * coming. Tickers (ANET, NBIS, CRDO, MP, VRT) are reused from SPEC.md §3's
 * own illustrative examples for continuity — real, well-known companies,
 * not placeholder "Acme Corp" names, and every screen tells the same
 * consistent fictional portfolio's story instead of three unrelated ones.
 */

export interface SamplePosition {
  ticker: string;
  qty: number;
  avgCost: number;
  openedAt: string;
  source: "CSV import" | "Manual entry" | "Marked as filled";
  lastVerifiedAt: string;
  convictionAtEntry: number;
  peakSinceEntry: number;
}

export const SAMPLE_POSITIONS: SamplePosition[] = [
  { ticker: "ANET", qty: 3, avgCost: 138.2, openedAt: "Jul 12, 2026", source: "Manual entry", lastVerifiedAt: "Aug 20, 2026", convictionAtEntry: 62, peakSinceEntry: 146.8 },
  { ticker: "NBIS", qty: 4, avgCost: 203.5, openedAt: "Jul 2, 2026", source: "CSV import", lastVerifiedAt: "Aug 20, 2026", convictionAtEntry: 75, peakSinceEntry: 241.15 },
  { ticker: "CRDO", qty: 12, avgCost: 61.4, openedAt: "Jun 18, 2026", source: "CSV import", lastVerifiedAt: "Aug 20, 2026", convictionAtEntry: 58, peakSinceEntry: 74.9 },
  { ticker: "MP", qty: 8, avgCost: 44.75, openedAt: "May 3, 2026", source: "Manual entry", lastVerifiedAt: "Aug 20, 2026", convictionAtEntry: 59, peakSinceEntry: 52.1 },
  { ticker: "VRT", qty: 5, avgCost: 118.9, openedAt: "Apr 22, 2026", source: "Marked as filled", lastVerifiedAt: "Aug 25, 2026", convictionAtEntry: 66, peakSinceEntry: 132.4 },
];

export interface SampleMemo {
  date: string;
  conviction: number;
  note: string;
}

export interface SampleResearchTicker {
  ticker: string;
  trend: "strengthening" | "decaying" | "steady";
  memos: SampleMemo[]; // most recent first
}

export const SAMPLE_RESEARCH: SampleResearchTicker[] = [
  {
    ticker: "ANET",
    trend: "strengthening",
    memos: [
      { date: "Aug 24, 2026", conviction: 74, note: "Cloud capex guide raised again — still the cleanest way to play 400G/800G switching demand without single-customer concentration." },
      { date: "Aug 3, 2026", conviction: 69, note: "Backlog growing but gross margin compressed a point on mix. No red flag yet." },
      { date: "Jul 12, 2026", conviction: 62, note: "Initiated: diversifies the book away from the AI-semis cluster, funded mostly by trimming GPU-adjacent names." },
    ],
  },
  {
    ticker: "NBIS",
    trend: "decaying",
    memos: [
      { date: "Aug 20, 2026", conviction: 61, note: "Peak $241 → now $222 (-7.9%). Close to the trailing stop — capacity build costs are eating into the AI-cloud narrative." },
      { date: "Jul 28, 2026", conviction: 68, note: "GPU cluster utilization strong, but the capex guide widened the loss window another two quarters." },
      { date: "Jul 2, 2026", conviction: 75, note: "Initiated: cheapest neocloud on EV/forward-revenue in the screen, sized small given execution risk." },
    ],
  },
  {
    ticker: "CRDO",
    trend: "steady",
    memos: [
      { date: "Aug 22, 2026", conviction: 64, note: "Design-win pipeline intact. Moved to watch after a 3.1% pullback toward the trailing stop, thesis unchanged." },
      { date: "Aug 1, 2026", conviction: 63, note: "Optical DSP share gains confirmed in the latest hyperscaler capex commentary." },
    ],
  },
];

export interface SampleRun {
  date: string;
  status: "succeeded" | "blocked" | "failed";
  proposals: number;
  filled: number;
  dismissed: number;
  open: number;
  note?: string;
}

export const SAMPLE_RUNS: SampleRun[] = [
  { date: "Aug 27, 2026 · 10:02 PM", status: "succeeded", proposals: 2, filled: 1, dismissed: 1, open: 0 },
  { date: "Aug 26, 2026 · 10:00 PM", status: "succeeded", proposals: 0, filled: 0, dismissed: 0, open: 0 },
  { date: "Aug 25, 2026 · 10:01 PM", status: "blocked", proposals: 0, filled: 0, dismissed: 0, open: 0, note: "2 held positions returned no price" },
  { date: "Aug 24, 2026 · 10:03 PM", status: "succeeded", proposals: 3, filled: 1, dismissed: 1, open: 1 },
  { date: "Aug 23, 2026 · 10:00 PM", status: "failed", proposals: 0, filled: 0, dismissed: 0, open: 0, note: "Screener step timed out fetching market data" },
];
