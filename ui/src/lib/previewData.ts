/**
 * Sample data for the Positions / Research / History stubs — none of these
 * screens have a backend yet (only /api/briefing/latest and /api/config
 * exist, see api/routes/). Shaped to match SPEC.md §6's actual table
 * columns (plus a plausible live price/conviction join, which a real
 * Positions page would obviously do even though the raw table doesn't
 * store it), not invented fields out of nowhere. Tickers (ANET, NBIS,
 * CRDO, MP, VRT) are reused from SPEC.md §3's own illustrative examples —
 * real, well-known companies, and every screen tells the same consistent
 * fictional portfolio's story instead of three unrelated ones.
 */

export interface SamplePosition {
  ticker: string;
  qty: number;
  avgCost: number;
  currentPrice: number;
  openedAt: string;
  source: "CSV import" | "Manual entry" | "Marked as filled";
  lastVerifiedAt: string;
  convictionNow: number;
  convictionAtEntry: number;
  peakSinceEntry: number;
  alert?: string;
}

export const SAMPLE_POSITIONS: SamplePosition[] = [
  { ticker: "ANET", qty: 3, avgCost: 138.2, currentPrice: 152.4, openedAt: "Jul 12, 2026", source: "Manual entry", lastVerifiedAt: "Aug 20, 2026", convictionNow: 74, convictionAtEntry: 62, peakSinceEntry: 152.4 },
  { ticker: "NBIS", qty: 4, avgCost: 203.5, currentPrice: 222.0, openedAt: "Jul 2, 2026", source: "CSV import", lastVerifiedAt: "Aug 20, 2026", convictionNow: 61, convictionAtEntry: 75, peakSinceEntry: 241.15, alert: "7.9% off peak — near trailing stop" },
  { ticker: "CRDO", qty: 12, avgCost: 61.4, currentPrice: 72.6, openedAt: "Jun 18, 2026", source: "CSV import", lastVerifiedAt: "Aug 20, 2026", convictionNow: 64, convictionAtEntry: 58, peakSinceEntry: 74.9, alert: "3.1% from trailing stop" },
  { ticker: "MP", qty: 8, avgCost: 44.75, currentPrice: 48.9, openedAt: "May 3, 2026", source: "Manual entry", lastVerifiedAt: "Aug 20, 2026", convictionNow: 59, convictionAtEntry: 59, peakSinceEntry: 52.1 },
  { ticker: "VRT", qty: 5, avgCost: 118.9, currentPrice: 126.5, openedAt: "Apr 22, 2026", source: "Marked as filled", lastVerifiedAt: "Aug 25, 2026", convictionNow: 63, convictionAtEntry: 66, peakSinceEntry: 132.4 },
];

export interface SampleMemo {
  date: string;
  conviction: number;
  thesis: string;
  bearCase: string;
  catalysts: string;
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
      {
        date: "Aug 24, 2026",
        conviction: 74,
        thesis: "Cloud capex guide raised again. Cleanest way to play 400G/800G switching demand without betting on one customer.",
        bearCase: "A hyperscaler capex slowdown or share loss to white-box switches would hit margins fast.",
        catalysts: "Q3 earnings in November, next capex guide, Broadcom's Tomahawk 6 launch timing.",
      },
      {
        date: "Aug 3, 2026",
        conviction: 69,
        thesis: "Backlog is growing, but gross margin slipped a point on mix. Not a red flag yet.",
        bearCase: "Margin compression could be an early sign of Nvidia's Spectrum-X pushing on price.",
        catalysts: "Margin commentary on the next earnings call.",
      },
      {
        date: "Jul 12, 2026",
        conviction: 62,
        thesis: "Initiated to diversify away from the AI-semis cluster, funded by trimming GPU-adjacent names.",
        bearCase: "Thin file — not enough runs yet to judge if this thesis holds up.",
        catalysts: "First full earnings cycle since initiation.",
      },
    ],
  },
  {
    ticker: "NBIS",
    trend: "decaying",
    memos: [
      {
        date: "Aug 20, 2026",
        conviction: 61,
        thesis: "Peak $241 → now $222 (-7.9%). Capacity build costs are eating into the AI-cloud story.",
        bearCase: "If GPU utilization doesn't ramp before the next raise, dilution risk grows.",
        catalysts: "Q3 utilization update, possible capital raise announcement.",
      },
      {
        date: "Jul 28, 2026",
        conviction: 68,
        thesis: "GPU cluster utilization is strong, but the capex guide pushed profitability out two more quarters.",
        bearCase: "A longer path to profitability tests patience in a higher-rate environment.",
        catalysts: "Utilization numbers at the next earnings report.",
      },
      {
        date: "Jul 2, 2026",
        conviction: 75,
        thesis: "Initiated: cheapest neocloud on forward revenue in the screen, sized small for execution risk.",
        bearCase: "The neocloud model is unproven at scale, with real customer concentration risk.",
        catalysts: "First earnings report as a new position.",
      },
    ],
  },
  {
    ticker: "CRDO",
    trend: "steady",
    memos: [
      {
        date: "Aug 22, 2026",
        conviction: 64,
        thesis: "Design-win pipeline intact. Pulled back 3.1% toward the trailing stop — thesis unchanged.",
        bearCase: "A move below the trailing stop forces an exit regardless of how the thesis looks.",
        catalysts: "New optical DSP design wins, hyperscaler capex commentary.",
      },
      {
        date: "Aug 1, 2026",
        conviction: 63,
        thesis: "Optical DSP share gains confirmed in the latest hyperscaler capex commentary.",
        bearCase: "Revenue is concentrated in a handful of hyperscaler customers.",
        catalysts: "Next earnings report, hyperscaler capex guidance.",
      },
    ],
  },
];

export type ProposalStatus = "filled" | "dismissed" | "open";

export interface SampleProposal {
  kind: "proposal";
  date: string;
  ticker: string;
  action: "BUY" | "SELL";
  isTrim?: boolean;
  qty: number;
  fillPrice?: number;
  status: ProposalStatus;
  result?: string;
}

export interface SampleRunEvent {
  kind: "run_event";
  date: string;
  status: "blocked" | "failed" | "quiet";
  note: string;
}

export type TimelineEntry = SampleProposal | SampleRunEvent;

export const SAMPLE_TIMELINE: TimelineEntry[] = [
  { kind: "proposal", date: "Aug 27, 2026", ticker: "ANET", action: "BUY", qty: 3, fillPrice: 138.2, status: "filled", result: "+10.3% since fill" },
  { kind: "proposal", date: "Aug 27, 2026", ticker: "MP", action: "SELL", isTrim: true, qty: 4, status: "dismissed" },
  { kind: "run_event", date: "Aug 26, 2026", status: "quiet", note: "Nothing crossed a trigger — no proposals." },
  { kind: "run_event", date: "Aug 25, 2026", status: "blocked", note: "2 held positions returned no price." },
  { kind: "proposal", date: "Aug 24, 2026", ticker: "NBIS", action: "BUY", qty: 4, fillPrice: 203.5, status: "filled", result: "+9.1% since fill" },
  { kind: "proposal", date: "Aug 24, 2026", ticker: "CRDO", action: "SELL", isTrim: true, qty: 6, status: "open" },
  { kind: "proposal", date: "Aug 24, 2026", ticker: "VRT", action: "SELL", qty: 5, status: "dismissed" },
  { kind: "run_event", date: "Aug 23, 2026", status: "failed", note: "Screener step timed out fetching market data." },
];
