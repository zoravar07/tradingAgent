"""Config loading — minimal slice needed by the portfolio module (§9 in SPEC.md).

This is NOT the full config system described in build-order step 1 / §8.1
(hot-reload, Pydantic validation of every section, version snapshots on write).
It only models what portfolio.py reads today. Extend as later build-order
steps (screener, scoring, risk, research) land — add a section model and
wire it into `Config` rather than reaching into the raw yaml dict.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class PortfolioConfig(BaseModel):
    import_reminder_days: int = 7
    allow_fractional: bool = False


class Stage1Config(BaseModel):
    min_avg_daily_volume_usd: float = 20_000_000
    min_market_cap_usd: float = 2_000_000_000
    max_survivors: int = 40
    min_revenue_growth_pct: float = 5.0
    valuation_pe_cheap_max: float = 15.0
    valuation_pe_expensive_min: float = 30.0
    earnings_proximity_days: int = 5


class Stage2Config(BaseModel):
    model: str = "claude-haiku-4-5"
    lookback_days: int = 7
    max_survivors: int = 15


class ScreenerConfig(BaseModel):
    stage1: Stage1Config = Stage1Config()
    stage2: Stage2Config = Stage2Config()


class LerpRange(BaseModel):
    """A value that scales linearly with conviction score, 0-100 -> at_0..at_100."""

    at_0: float
    at_100: float


class ConvictionScalingConfig(BaseModel):
    activation_threshold_pct: LerpRange = LerpRange(at_0=8, at_100=35)
    trailing_stop_atr_multiple: LerpRange = LerpRange(at_0=1.5, at_100=4.5)
    profit_taking_start_pct: LerpRange = LerpRange(at_0=15, at_100=60)


class RiskConfig(BaseModel):
    max_position_pct: float = 12
    max_sector_pct: float = 40
    max_correlated_cluster_pct: float = 50
    max_daily_proposals: int = 5
    max_daily_loss_pct: float = 3
    max_drawdown_pct: float = 12
    min_order_value_usd: float = 150
    # Below: §5.3 names these mechanisms ("position sizing from conviction
    # and volatility", "thesis decay since entry") but doesn't give exact
    # formulas/thresholds. Defaults chosen here, not spec'd — see
    # risk_rules.py docstring for the reasoning.
    reference_atr_pct_of_price: float = 3.0
    min_volatility_size_multiplier: float = 0.25
    thesis_decay_trigger_pts: float = 15.0


class ResearchConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_candidates_per_run: int = 15


class BudgetConfig(BaseModel):
    monthly_api_cap_usd: float = 40


class Config(BaseModel):
    # extra="allow" so unmodeled sections (sources, sleeves, ...) round-trip
    # instead of being rejected — they just aren't validated or typed yet.
    model_config = ConfigDict(extra="allow")

    version: int = 1
    portfolio: PortfolioConfig = PortfolioConfig()
    screener: ScreenerConfig = ScreenerConfig()
    risk: RiskConfig = RiskConfig()
    conviction_scaling: ConvictionScalingConfig = ConvictionScalingConfig()
    conviction_weights: dict[str, float] = {}
    research: ResearchConfig = ResearchConfig()
    budget: BudgetConfig = BudgetConfig()


def load_config(path: str | Path) -> Config:
    """Read and validate config.yaml. Raises if the file is missing or malformed."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(raw)
