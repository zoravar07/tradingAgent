/**
 * Mirrors api/routes/dashboard.py. Every field is returned by that handler;
 * a tile the backend can't compute honestly is simply absent from `tiles`.
 */
import type { OrderProposal } from "./briefing";

export interface TileSeriesPoint {
  run_id: number;
  at: string; // ISO 8601
  value: number;
}

export interface Tile {
  key: string;
  label: string;
  value: number;
  unit?: string;
  hint?: string;
  series: TileSeriesPoint[];
  cap?: number | null;
  fmp_calls_today?: number;
}

export type SetupAction = "BUY" | "SELL" | "TRIM" | "CANDIDATE";

export interface Setup {
  ticker: string;
  name: string | null;
  action: SetupAction;
  conviction: number | null;
  price: number | null;
  change_pct: number | null;
  is_held: boolean;
  weight_pct: number | null;
  order: OrderProposal | null;
  reason: string | null;
}

export interface TradePlan {
  entry_price: number | null;
  entry_basis: string | null;
  stop_price: number | null;
  target_price: number | null;
  target_pct: number | null;
  quantity: number | null;
  est_cost_usd: number | null;
  weight_pct: number | null;
  conviction: number | null;
  atr_14: number | null;
  note: string | null;
}

export interface Insight {
  technical: string | null;
  fundamental: string | null;
  news: string | null;
  risk: string | null;
}

export interface PnlWindow {
  usd: number;
  pct: number;
  since: string; // ISO 8601 of the comparison reading
}

export interface Pnl {
  series: { at: string; nav_usd: number }[];
  current_nav_usd: number | null;
  daily: PnlWindow | null;
  weekly: PnlWindow | null;
  monthly: PnlWindow | null;
}

export type HoldingAction = "BUY" | "SELL" | "TRIM" | "HOLD";

export interface Holding {
  ticker: string;
  name: string | null;
  action: HoldingAction;
  conviction: number | null;
  price: number | null;
  change_pct: number | null;
  weight_pct: number | null;
  qty: number;
  avg_cost: number;
  unrealized_pnl_pct: number | null;
  has_exit_trigger: boolean;
}

export type DashboardResponse =
  | { status: "no_runs_yet" }
  | {
      status: "ok";
      run: { run_id: number; status: string; started_at: string; finished_at: string | null };
      tiles: Tile[];
      pnl: Pnl;
      setups: Setup[];
      holdings: Holding[];
      plans: Record<string, TradePlan>;
      insights: Record<string, Insight>;
    };

export type PriceRange = "1W" | "1M" | "3M" | "1Y";

export interface PriceBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PricesResponse {
  ticker: string;
  range: PriceRange;
  as_of: string | null;
  available_ranges: PriceRange[];
  bars: PriceBar[];
}
