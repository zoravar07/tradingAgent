/** Mirrors api/routes/config.py's request/response shapes. */

export interface PortfolioFields {
  import_reminder_days: number;
  allow_fractional: boolean;
}

export interface RiskFields {
  max_position_pct: number;
  max_sector_pct: number;
  max_correlated_cluster_pct: number;
  max_daily_proposals: number;
  max_daily_loss_pct: number;
  max_drawdown_pct: number;
  min_order_value_usd: number;
  min_hold_conviction: number;
  max_unpriced_held_positions: number;
}

export interface Stage1Fields {
  min_avg_daily_volume_usd: number;
  min_market_cap_usd: number;
  max_survivors: number;
  min_revenue_growth_pct: number;
  valuation_pe_cheap_max: number;
  valuation_pe_expensive_min: number;
  earnings_proximity_days: number;
}

export interface ScreenerFields {
  stage1: Stage1Fields;
}

export interface BudgetFields {
  monthly_api_cap_usd: number;
}

export interface ScheduleFields {
  nightly_run: string;
}

export interface EditableConfig {
  portfolio: PortfolioFields;
  risk: RiskFields;
  screener: ScreenerFields;
  budget: BudgetFields;
  schedule: ScheduleFields;
}

export interface ConfigResponse {
  editable: EditableConfig;
  defaults: EditableConfig;
  yaml_text: string;
}

/** One entry from a FastAPI/Pydantic 422 `detail` array. */
export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}
