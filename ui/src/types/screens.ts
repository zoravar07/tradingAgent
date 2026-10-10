/**
 * Mirrors api/routes/screens.py and api/routes/journal.py. Every field here
 * is returned by one of those handlers — nothing is inferred, and nothing is
 * optional on the wire that isn't `| null` here.
 */

export interface PositionRow {
  ticker: string;
  qty: number;
  avg_cost: number;
  opened_at: string;
  source: string;
  last_verified_at: string | null;
  conviction_at_entry: number | null;
  peak_price_since_activation: number | null;
  // From the latest briefing's book — null when the holding wasn't in it.
  value_usd: number | null;
  weight_pct: number | null;
  unrealized_pnl_pct: number | null;
  conviction_now: number | null;
  last_price: number | null;
  distance_to_trailing_stop_pct: number | null;
  next_profit_band_pct: number | null;
  has_exit_trigger: boolean;
  no_research_coverage: boolean;
}

export interface PositionsResponse {
  positions: PositionRow[];
  cash_pct: number | null;
  priced_at: string | null;
}

export interface OrderRow {
  id: number;
  run_id: number;
  ticker: string;
  action: "BUY" | "SELL";
  quantity: number;
  order_type: string;
  limit_price: number;
  est_cost: number;
  conviction: number;
  rationale: string;
  trigger_type: string | null;
  status: string;
  created_at: string;
  filled_at: string | null;
  fill_price: number | null;
}

export interface RunRow {
  run_id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  proposal_count: number;
  risk_events: { type: string; count: number }[];
}

export interface OrdersResponse {
  orders: OrderRow[];
  runs: RunRow[];
}

export interface Catalyst {
  description: string;
  expected_date: string | null;
}

export interface ConvictionDerivation {
  base_score: number;
  penalty: number;
  final_score: number;
  contributions: Record<string, number>;
  missing_factors: string[];
}

export interface Memo {
  run_id: number;
  dated_at: string | null;
  conviction: number | null;
  subscores: Record<string, number>;
  derivation: ConvictionDerivation | null;
  consensus_view: string;
  variant_view: string;
  thesis_summary: string;
  bear_case: string | null;
  estimated_downside_pct: number | null;
  catalysts: Catalyst[];
  risks: string[];
  unavailable_factors: string[];
  model: string;
  input_tokens: number | null;
  output_tokens: number | null;
}

export type Trend = "strengthening" | "decaying" | "steady" | "new";

export interface InsightTicker {
  ticker: string;
  trend: Trend;
  conviction_now: number | null;
  conviction_delta: number | null;
  memos: Memo[];
}

export interface InsightsResponse {
  tickers: InsightTicker[];
}

export interface NavPoint {
  run_id: number | null;
  recorded_at: string;
  nav_usd: number;
  peak_nav_usd: number;
  drawdown_pct: number;
  daily_loss_pct: number;
}

export interface PerformanceResponse {
  series: NavPoint[];
  /** "ibkr" once the broker's daily value is synced, else "runs" (the pipeline's own estimate). */
  source: "ibkr" | "runs";
  point_count: number;
  has_history: boolean;
  current_nav_usd: number | null;
  peak_nav_usd: number | null;
  drawdown_pct: number | null;
  change_since_first_pct: number | null;
}

export interface JournalEntry {
  id: number;
  date: string;
  content: string;
  linked_ticker: string | null;
}

export interface JournalResponse {
  entries: JournalEntry[];
}
