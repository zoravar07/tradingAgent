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
from pydantic import BaseModel, ConfigDict, Field


class PortfolioConfig(BaseModel):
    import_reminder_days: int = 7
    # Default is conservative (whole shares only) for a fresh config; governs
    # manual entry / mark-filled recording only, not Order Builder's output
    # (always whole-share by construction, see agents/order_builder.py) —
    # override to True in config.yaml for an account that trades fractional
    # shares, as this codebase's own config.yaml does.
    allow_fractional: bool = False


class WeeklyWideScanConfig(BaseModel):
    """Off by default — needs a paid FMP tier to be worth turning on (a
    full-pool scan on the wide-scan day still costs one call per name)."""

    enabled: bool = False
    day_of_week: int = Field(6, ge=0, le=6)  # 0=Monday .. 6=Sunday (Python's datetime.weekday())


class UniverseConfig(BaseModel):
    include_holdings_always: bool = True
    watchlist: list[str] = []
    rotating_pool_source: str = "SP500"
    rotating_scan_size: int = 30
    weekly_wide_scan: WeeklyWideScanConfig = WeeklyWideScanConfig()
    # §9's note names these 10 tickers as "your AI/semis cluster" explicitly —
    # copied here as the seed override map, not invented.
    cluster_overrides: dict[str, str] = {
        "AMD": "ai_semis", "NVDA": "ai_semis", "MRVL": "ai_semis", "CRDO": "ai_semis",
        "NBIS": "ai_semis", "VRT": "ai_semis", "CLS": "ai_semis", "CEG": "ai_semis",
        "MP": "ai_semis", "PLTR": "ai_semis",
    }
    # User-requested, not in the spec: ETFs have no income statement to be
    # judged on — explicit list, not inferred (same reasoning as
    # cluster_overrides above), so screener.py can exempt them from the
    # fundamental-floor gate instead of failing them for a structural
    # non-issue. Seeded with this user's own core_longterm sleeve (§9).
    etf_tickers: list[str] = ["VTI", "VGT", "IAU"]


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
    # User-requested, not in the spec: every other exit trigger needs
    # either price movement (trailing stop, profit band) or a recorded
    # entry conviction to compare against (thesis decay) — a position
    # that's simply bad, with no baseline and no favorable price action,
    # never triggers anything under those three alone. This is an absolute
    # floor: conviction_now below this always proposes an exit for a held
    # position, regardless of P&L or whether an entry baseline exists.
    min_hold_conviction: float = 40.0
    # User-requested hard gate, not in the spec: NAV is only as good as
    # every held position being priced. Zero tolerance by default — if more
    # than this many held positions can't be priced, the whole run halts
    # with zero proposals rather than publish a briefing built on a NAV
    # that's silently missing part of the book. See core/orchestrator.py's
    # module docstring.
    max_unpriced_held_positions: int = 0


class ResearchConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_candidates_per_run: int = 15


class OrderBuilderConfig(BaseModel):
    """§5.4 names Order Builder's job ("limit price from recent price action
    and spread") but not a formula, and isn't itself a numbered §10 step —
    it's built alongside step 8 because the briefing (§3) can't render an
    order line without one. Defaults chosen here, not spec'd."""

    limit_buffer_pct: float = 0.5  # BUY: current_price * (1 + this); SELL: * (1 - this)
    profit_trim_fraction: float = 0.5  # fraction of the position sold when PROFIT_BAND triggers


class ScheduleConfig(BaseModel):
    nightly_run: str = "0 22 * * 0-4"


class BudgetConfig(BaseModel):
    monthly_api_cap_usd: float = 40


class Config(BaseModel):
    # extra="allow" so unmodeled sections (sources, sleeves, ...) round-trip
    # instead of being rejected — they just aren't validated or typed yet.
    model_config = ConfigDict(extra="allow")

    version: int = 1
    portfolio: PortfolioConfig = PortfolioConfig()
    universe: UniverseConfig = UniverseConfig()
    screener: ScreenerConfig = ScreenerConfig()
    risk: RiskConfig = RiskConfig()
    conviction_scaling: ConvictionScalingConfig = ConvictionScalingConfig()
    conviction_weights: dict[str, float] = {}
    research: ResearchConfig = ResearchConfig()
    order_builder: OrderBuilderConfig = OrderBuilderConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    budget: BudgetConfig = BudgetConfig()


def load_config(path: str | Path) -> Config:
    """Read and validate config.yaml. Raises if the file is missing or malformed."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(raw)
