/**
 * Mirrors core/briefing.py's dataclasses + the fields OrderProposal /
 * KillSwitchStatus contribute to a serialized Briefing (see
 * core/briefing_persistence.py — dataclasses.asdict, no reconstruction, so
 * the wire shape is exactly these dataclasses' field names). Keep this file
 * in lockstep with those five backend modules; nothing here is inferred.
 */

export type OrderAction = "BUY" | "SELL";

export interface OrderProposal {
  ticker: string;
  action: OrderAction;
  quantity: number;
  order_type: "LIMIT";
  limit_price: number;
  estimated_cost_usd: number;
  weight_pct: number;
  conviction: number;
  trigger_type: string | null;
  is_trim: boolean;
}

export interface ActionItem {
  order: OrderProposal;
  headline: string;
  thesis_summary: string | null;
  bear_case: string | null;
}

export interface WatchlistItem {
  ticker: string;
  reason: string;
  distance_to_trigger_pct: number | null;
}

export interface OvernightChange {
  ticker: string;
  summary: string;
}

export interface BookEntry {
  ticker: string;
  qty: number;
  value_usd: number;
  weight_pct: number;
  unrealized_pnl_pct: number;
  conviction_now: number | null;
  conviction_at_entry: number | null;
  distance_to_trailing_stop_pct: number | null;
  next_profit_band_pct: number | null;
  has_exit_trigger: boolean;
  no_research_coverage: boolean;
  // Set when conviction_now is a real score reused from an earlier run.
  conviction_run_id?: number | null;
  conviction_age_days?: number | null;
}

export interface UnresearchedHolding {
  ticker: string;
  reason: string;
}

export interface KillSwitchStatus {
  triggered: boolean;
  reasons: string[];
}

export interface PortfolioHealth {
  sleeve_weights_pct: Record<string, number>;
  sleeve_targets_pct: Record<string, number>;
  correlated_cluster_pct: Record<string, number>;
  cash_pct: number;
  drawdown_from_peak_pct: number;
  kill_switch: KillSwitchStatus | null;
}

export interface UnpricedPosition {
  ticker: string;
  error: string;
}

export interface BlockedStatus {
  reason: string;
  unpriced_positions: UnpricedPosition[];
}

export interface Briefing {
  generated_at: string; // ISO 8601
  actions_today: ActionItem[];
  watching: WatchlistItem[];
  overnight_changes: OvernightChange[];
  book: BookEntry[];
  portfolio_health: PortfolioHealth;
  blocked: BlockedStatus | null;
  unresearched_holdings: UnresearchedHolding[];
}

export type RunStatus = "succeeded" | "blocked" | "failed" | string;

export type LatestBriefingResponse =
  | { status: "no_runs_yet" }
  | {
      status: "ok";
      run_id: number;
      run_status: RunStatus;
      generated_at: string | null;
      briefing: Briefing;
    };
