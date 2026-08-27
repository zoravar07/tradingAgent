"""Comment-preserving config.yaml read/write for the Settings screen (§10
step 10). `core/config.py`'s `load_config`/`Config` stay the read path used
everywhere else (PyYAML, fast, no round-trip guarantees needed there) — this
module exists only because the Settings screen writes the file back, and
config.yaml carries hand-written comments documenting every deviation from
SPEC.md that this whole project has accumulated (currency-trap notes,
"user-requested, not in the spec" markers, etc.). Plain
`yaml.safe_load` + `yaml.safe_dump` would silently discard all of that on
the first save — so writes go through `ruamel.yaml`'s round-trip mode
instead, which preserves comments/ordering/formatting for every key it
isn't asked to change.

Only a curated subset of Config's fields is editable here (see
EDITABLE_FIELDS) — the operationally-meaningful risk/screening/budget
knobs a user would actually reach for from a settings screen. Deliberately
excluded: `universe` (watchlist/cluster_overrides/etf_tickers are
hand-curated lists, not generic knobs — see config.yaml's own comments on
why), `conviction_weights` (11-factor tuned dict, §8.3), and the unmodeled
`options`/`sleeves`/`sources` sections (not wired into any logic yet, per
core/config.py's docstring). All of those still round-trip untouched on
every write; "View current" in the UI shows the full file, editable or
not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from core.config import BudgetConfig, PortfolioConfig, RiskConfig, ScheduleConfig, Stage1Config

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=2, offset=0)

# (dotted path in the yaml, path as a tuple of keys) — the single source of
# truth for which fields the Settings screen can edit and where they live.
EDITABLE_FIELDS: list[tuple[str, ...]] = [
    ("portfolio", "import_reminder_days"),
    ("portfolio", "allow_fractional"),
    ("risk", "max_position_pct"),
    ("risk", "max_sector_pct"),
    ("risk", "max_correlated_cluster_pct"),
    ("risk", "max_daily_proposals"),
    ("risk", "max_daily_loss_pct"),
    ("risk", "max_drawdown_pct"),
    ("risk", "min_order_value_usd"),
    ("risk", "min_hold_conviction"),
    ("risk", "max_unpriced_held_positions"),
    ("screener", "stage1", "min_avg_daily_volume_usd"),
    ("screener", "stage1", "min_market_cap_usd"),
    ("screener", "stage1", "max_survivors"),
    ("screener", "stage1", "min_revenue_growth_pct"),
    ("screener", "stage1", "valuation_pe_cheap_max"),
    ("screener", "stage1", "valuation_pe_expensive_min"),
    ("screener", "stage1", "earnings_proximity_days"),
    ("budget", "monthly_api_cap_usd"),
    ("schedule", "nightly_run"),
]


def read_raw(path: str | Path) -> Any:
    """Round-trip load — returns a ruamel CommentedMap, not a plain dict."""
    with open(path) as f:
        return _yaml.load(f)


def write_raw(path: str | Path, raw: Any) -> None:
    with open(path, "w") as f:
        _yaml.dump(raw, f)


def dump_to_string(raw: Any) -> str:
    from io import StringIO

    buf = StringIO()
    _yaml.dump(raw, buf)
    return buf.getvalue()


def _get_in(d: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        d = d[key]
    return d


def _set_in(d: Any, path: tuple[str, ...], value: Any) -> None:
    for key in path[:-1]:
        if key not in d:
            d[key] = {}
        d = d[key]
    d[path[-1]] = value


def editable_snapshot(raw: Any) -> dict[str, Any]:
    """The current value of every editable field, nested by section — what
    the Settings form pre-fills with. Missing keys (a field never set in
    config.yaml) fall back to the Pydantic default rather than erroring,
    since Config's own loader treats an absent key the same way."""
    defaults = default_values()
    out: dict[str, Any] = {}
    for path in EDITABLE_FIELDS:
        try:
            value = _get_in(raw, path)
        except (KeyError, TypeError):
            value = _get_in(defaults, path)
        _set_in(out, path, value)
    return out


def default_values() -> dict[str, Any]:
    """Pydantic model defaults for exactly the editable fields, nested to
    match config.yaml's shape. Single source of truth: reads the real
    section models' own defaults rather than hardcoding numbers a second
    time somewhere else."""
    portfolio = PortfolioConfig()
    risk = RiskConfig()
    stage1 = Stage1Config()
    budget = BudgetConfig()
    schedule = ScheduleConfig()
    return {
        "portfolio": {
            "import_reminder_days": portfolio.import_reminder_days,
            "allow_fractional": portfolio.allow_fractional,
        },
        "risk": {
            "max_position_pct": risk.max_position_pct,
            "max_sector_pct": risk.max_sector_pct,
            "max_correlated_cluster_pct": risk.max_correlated_cluster_pct,
            "max_daily_proposals": risk.max_daily_proposals,
            "max_daily_loss_pct": risk.max_daily_loss_pct,
            "max_drawdown_pct": risk.max_drawdown_pct,
            "min_order_value_usd": risk.min_order_value_usd,
            "min_hold_conviction": risk.min_hold_conviction,
            "max_unpriced_held_positions": risk.max_unpriced_held_positions,
        },
        "screener": {
            "stage1": {
                "min_avg_daily_volume_usd": stage1.min_avg_daily_volume_usd,
                "min_market_cap_usd": stage1.min_market_cap_usd,
                "max_survivors": stage1.max_survivors,
                "min_revenue_growth_pct": stage1.min_revenue_growth_pct,
                "valuation_pe_cheap_max": stage1.valuation_pe_cheap_max,
                "valuation_pe_expensive_min": stage1.valuation_pe_expensive_min,
                "earnings_proximity_days": stage1.earnings_proximity_days,
            },
        },
        "budget": {"monthly_api_cap_usd": budget.monthly_api_cap_usd},
        "schedule": {"nightly_run": schedule.nightly_run},
    }


def apply_updates(raw: Any, updates: dict[str, Any]) -> None:
    """Mutates `raw` in place, setting only the editable fields present (as
    nested dicts) in `updates`. Every other key — including comments
    attached to keys this touches — is left untouched by ruamel."""
    for path in EDITABLE_FIELDS:
        try:
            value = _get_in(updates, path)
        except (KeyError, TypeError):
            continue
        _set_in(raw, path, value)
