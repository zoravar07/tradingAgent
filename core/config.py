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
    # "SP500": Wikipedia's index list (sources/index_constituents.py).
    # "US_ALL": every NASDAQ/NYSE/AMEX/Arca/Cboe common stock from NASDAQ
    # Trader's symbol directory, pre-gated on Stage 1's liquidity and
    # market-cap floors from yfinance screener data before any per-name
    # fetch (sources/us_listing.py) — ~5,000 listed, ~1,900 pass.
    rotating_pool_source: str = "SP500"
    # 0 = scan the whole pool every day. Stage 1 runs on yfinance only (no FMP
    # calls), so a full-pool daily scan costs nothing against the FMP cap —
    # see sources/live_gateway.py. A positive value restores the rotating
    # slice (that many pool names per day).
    rotating_scan_size: int = 0
    # Names outside the index you want screened every day regardless of
    # rotation — e.g. small caps FMP/Wikipedia will never list.
    extra_tickers: list[str] = []
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
    max_survivors: int = 15
    # Candidates per structured ranking call. Stage 2 is one Haiku call per
    # chunk over cached Stage 1 numbers — no web search (agents/screener.py).
    batch_size: int = 40


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
    # Hard cap on NEW (non-held) names that get a memo per run.
    max_candidates_per_run: int = 15
    # Grounded news: one web-search text call per researched name feeds the
    # memo and the briefing's "Overnight changes". Never falls back to model
    # memory when off — the section is simply empty. Digests are a
    # fact-listing task, so they run on the cheaper model by default; each
    # search is $0.01 on top of tokens (core/llm.py).
    web_search_enabled: bool = True
    web_search_max_uses: int = 1
    digest_model: str = "claude-haiku-4-5"
    news_lookback_days: int = 7
    # A digest is reused within this window instead of re-searching the
    # same name every night.
    news_cache_hours: int = 48
    # Held positions are re-researched on a rolling cadence: each run
    # refreshes the ceil(held / this) names with the oldest memo, so every
    # holding gets a fresh memo about this often. Between refreshes the
    # last real conviction score is reused and flagged with its age —
    # never a made-up number.
    holdings_refresh_days: int = 7


class OrderBuilderConfig(BaseModel):
    """§5.4 names Order Builder's job ("limit price from recent price action
    and spread") but not a formula, and isn't itself a numbered §10 step —
    it's built alongside step 8 because the briefing (§3) can't render an
    order line without one. Defaults chosen here, not spec'd."""

    limit_buffer_pct: float = 0.5  # BUY: current_price * (1 + this); SELL: * (1 - this)
    profit_trim_fraction: float = 0.5  # fraction of the position sold when PROFIT_BAND triggers


class ScheduleConfig(BaseModel):
    nightly_run: str = "0 22 * * 0-4"


class BriefingConfig(BaseModel):
    # Cap on the "Watching" section. At a ~1,800-name universe Stage 1
    # produces ~80 near-misses; the closest to firing (smallest distance to
    # trigger) are kept, the rest are dropped from the briefing and the
    # watchlist_items table alike.
    watching_max_items: int = 12


class BudgetConfig(BaseModel):
    monthly_api_cap_usd: float = 40
    # Pre-flight guard (scripts/run_live_briefing.py): a run whose projected
    # LLM cost exceeds this refuses to start.
    max_run_cost_usd: float = 0.75


class SleeveConfig(BaseModel):
    """One sleeve's target/band and, for the three closed-list sleeves, its
    membership and special sizing/exit rules. `tickers=[]` (SWING) means
    "no explicit list" — resolve_sleeve() falls back to default_sleeve for
    anything not claimed by CORE/HEDGE_CASH/SPECULATIVE."""

    target_pct: float
    band_low_pct: float
    band_high_pct: float
    tickers: list[str] = []
    # HEDGE_CASH only: sleeve weight adds inputs.cash on top of ticker holdings.
    includes_account_cash: bool = False
    # SPECULATIVE only: sized by slots, not conviction — max concurrent
    # positions and a fixed % of NAV per slot.
    slot_count: int | None = None
    slot_pct: float | None = None
    # SPECULATIVE only: exits at this % from avg_cost (e.g. -60), no trailing stop.
    hard_stop_pct: float | None = None
    # SPECULATIVE only: crossing this NAV weight reclassifies the position to
    # SWING (Part 4 wires the trigger — this field just carries the number).
    reclass_at_pct: float | None = None
    # SPECULATIVE only: a position whose weight exceeds slot_pct times this
    # multiple gets flagged OVERSIZED_SPECULATIVE (advisory, never a forced
    # trim) — it carries SPECULATIVE's exit rules (hard stop only) but
    # wasn't sized under the 2.5%-slot discipline (e.g. a pre-existing
    # position assigned to this sleeve rather than sized into it). 2.0 is a
    # guess, not measured — revisit once there's a real distribution of
    # SPECULATIVE position sizes to look at.
    oversized_slot_multiple: float | None = None


class SleevesConfig(BaseModel):
    default_sleeve: str = "SWING"
    breach_sustain_days: int = 10
    breach_margin_pct: float = 5.0
    definitions: dict[str, SleeveConfig] = {
        "CORE": SleeveConfig(target_pct=50, band_low_pct=40, band_high_pct=65, tickers=["VTI", "VGT"]),
        "HEDGE_CASH": SleeveConfig(
            target_pct=13, band_low_pct=8, band_high_pct=25, tickers=["IAU"], includes_account_cash=True
        ),
        "SWING": SleeveConfig(target_pct=30, band_low_pct=15, band_high_pct=40, tickers=[]),
        "SPECULATIVE": SleeveConfig(
            target_pct=7, band_low_pct=0, band_high_pct=12, tickers=["RKLB", "SOFI"],
            slot_count=5, slot_pct=2.5, hard_stop_pct=-60, reclass_at_pct=15, oversized_slot_multiple=2.0,
        ),
    }


class SpeculativeLookConfig(BaseModel):
    """Thresholds for the informational 'this smells speculative' warning on
    a new BUY that defaulted to SWING (core/sleeves.py's
    speculative_look_reasons). Never blocks, never reclassifies — purely
    advisory, per explicit user request. market_cap_below_usd is a
    conservative guess, not measured against RKLB/SOFI's actual entry caps —
    revisit once there's evidence of what predicts that cohort, same
    reasoning as risk_rules.py's thesis_decay_trigger_pts."""

    market_cap_below_usd: float = 10_000_000_000


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
    briefing: BriefingConfig = BriefingConfig()
    sleeves: SleevesConfig = SleevesConfig()
    speculative_look: SpeculativeLookConfig = SpeculativeLookConfig()


def load_config(path: str | Path) -> Config:
    """Read and validate config.yaml. Raises if the file is missing or malformed."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(raw)
