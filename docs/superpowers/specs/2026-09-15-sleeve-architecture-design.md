# Sleeve architecture — design spec

Status: approved 2026-09-15, implementation in progress.

## Problem

Every position currently sits in one undifferentiated book. The risk manager's
exit machinery (trailing stop, profit band, thesis decay, conviction floor)
runs against everything the same way, whether it's a core index ETF or a
speculative small-cap. The user wants four sleeves — CORE, HEDGE_CASH, SWING,
SPECULATIVE — each with its own target/band, its own exit rules, and a
non-drifting assignment made once at proposal time.

`core/briefing.py`'s `PortfolioHealth` already has `sleeve_weights_pct` /
`sleeve_targets_pct` fields, unused since they were added — this work finally
populates them.

## Config

`core/config.py` gains:

```python
class SleeveConfig(BaseModel):
    target_pct: float
    band_low_pct: float
    band_high_pct: float
    tickers: list[str] = []          # closed-list membership; [] means "no explicit list" (SWING, the default sleeve)
    includes_account_cash: bool = False  # HEDGE_CASH only: sleeve weight adds inputs.cash on top of ticker holdings
    slot_count: int | None = None        # SPECULATIVE only: max concurrent positions
    slot_pct: float | None = None        # SPECULATIVE only: fixed % of NAV per slot, not conviction-scaled
    hard_stop_pct: float | None = None   # SPECULATIVE only: exit trigger at this % from avg_cost (e.g. -60)
    reclass_at_pct: float | None = None  # SPECULATIVE only: crossing this NAV weight reclassifies to SWING (Part 4 wires the trigger)

class SleevesConfig(BaseModel):
    default_sleeve: str = "SWING"
    breach_sustain_days: int = 10
    breach_margin_pct: float = 5.0
    definitions: dict[str, SleeveConfig] = {
        "CORE":        SleeveConfig(target_pct=50, band_low_pct=40, band_high_pct=65, tickers=["VTI", "VGT"]),
        "HEDGE_CASH":  SleeveConfig(target_pct=13, band_low_pct=8,  band_high_pct=25, tickers=["IAU"], includes_account_cash=True),
        "SWING":       SleeveConfig(target_pct=30, band_low_pct=15, band_high_pct=40, tickers=[]),
        "SPECULATIVE": SleeveConfig(target_pct=7,  band_low_pct=0,  band_high_pct=12, tickers=["RKLB", "SOFI"],
                                     slot_count=5, slot_pct=2.5, hard_stop_pct=-60, reclass_at_pct=15),
    }

class SpeculativeLookConfig(BaseModel):
    """Thresholds for the informational 'this smells speculative' warning on
    a new BUY that defaulted to SWING. Never blocks, never reclassifies —
    purely advisory, per explicit user request. market_cap_below_usd is a
    conservative guess, not measured against RKLB/SOFI's actual entry caps —
    revisit once there's evidence of what predicts that cohort."""
    market_cap_below_usd: float = 10_000_000_000
```

`Config` gains `sleeves: SleevesConfig` and `speculative_look: SpeculativeLookConfig`.

## New module: `core/sleeves.py`

Pure functions, no I/O, no ORM coupling — mirrors `risk_rules.py`'s style.

- `resolve_sleeve(ticker: str, config: SleevesConfig) -> str` — checks each
  sleeve's `tickers` list (CORE, HEDGE_CASH, SPECULATIVE, in that order),
  falls back to `default_sleeve`.
- `SleeveDrift` dataclass (`ticker`, `stored_sleeve`, `resolved_sleeve`).
- `find_sleeve_drift(holdings: list[tuple[str, str]], config: SleevesConfig) -> list[SleeveDrift]`
  — pure comparison, no DB access; caller passes `[(ticker, position.sleeve), ...]`.
- `sleeve_room(current_pct: float, sleeve_config: SleeveConfig) -> float` —
  `max(0, band_high_pct - current_pct)`, same shape as the existing
  sector/cluster room calculation in `size_new_position`.
- `SleeveBreachStatus` dataclass (`direction: Literal["OVER","UNDER"] | None`, `streak_days: int`).
- `update_breach_streak(previous: SleeveBreachStatus, weight_pct: float, sleeve_config: SleeveConfig, margin_pct: float) -> SleeveBreachStatus`
  — breach magnitude must exceed `margin_pct` beyond the nearest band edge to
  count; same direction continuing increments the streak, anything else
  resets to a fresh 1-day streak (or 0 if no breach).
- `speculative_look_reasons(market_cap_usd: float | None, free_cash_flow: float | None, trailing_pe: float | None, config: SpeculativeLookConfig) -> list[str]`
  — returns human-readable reasons (empty list if none apply): market cap
  below threshold, negative FCF, no earnings (`trailing_pe is None`, which
  `live_gateway.py`'s `_trailing_pe` already only produces when EPS is
  missing or non-positive).

## Schema changes

`core/models.py`:
- `Position.sleeve: Mapped[str]` (non-nullable). No migration framework
  exists (`core/db.py`'s `create_all` only creates missing tables) — hand-run
  `ALTER TABLE positions ADD COLUMN sleeve` + a one-time backfill UPDATE
  against `data/z_money.db`, using the exact CORE/HEDGE_CASH/SPECULATIVE
  ticker lists above (everything else backfills to SWING).
- New `SleeveBreachState` table: `sleeve` (PK), `direction`, `streak_days`,
  `last_run_id`. `create_all` creates this one automatically (new table).
- `Proposal.speculative_warning_json: Mapped[str | None]` (nullable Text) —
  same hand-run `ALTER TABLE proposals ADD COLUMN` treatment as `sleeve`
  above (existing rows backfill to `NULL`, which is the correct "no warning"
  state for every historical proposal).

## Assignment, never drift

`core/portfolio.py`: `PortfolioService.__init__` gains `sleeves: SleevesConfig`.
`resolve_sleeve` is called at the three `Position(...)` construction sites
(`add_manual_position`, `mark_filled`'s new-BUY branch, `reconcile`'s
new-broker-row branch). A new `reclassify_sleeve(position_id, new_sleeve)`
method is the *only* other writer of `Position.sleeve` — unused by Part 2,
reserved for Part 4's SPECULATIVE→SWING-at-15%-NAV rule.

`scripts/run_live_briefing.py` and `api/server.py`'s startup both call
`find_sleeve_drift` against the current book and `logger.warning` any
mismatches (ticker, stored sleeve, what `resolve_sleeve` would return today).
No auto-correction.

## Exit-machinery gating (`core/risk_rules.py`)

`evaluate_held_position` gains a `sleeve: str` parameter:

- `SWING`: unchanged — TRAILING_STOP, PROFIT_BAND, THESIS_DECAY,
  CONVICTION_FLOOR all still evaluated, in existing priority order.
- `CORE` / `HEDGE_CASH`: none of the four are evaluated. These sleeves only
  ever exit via Part 4's concentration-based runner-rule trim (out of scope
  here).
- `SPECULATIVE`: none of the four are evaluated. A new `hard_stop_breached(current_price, avg_cost, hard_stop_pct) -> tuple[bool, dict]`
  pure function replaces them, added as a new `ExitTriggerType` literal
  `"HARD_STOP"`, checked first in priority order (it's an absolute floor,
  not a judgment call). Reclassification at 15% NAV is Part 4's job.

## Band-edge BUY gating (`core/orchestrator.py`, `core/risk_rules.py`)

A `current_sleeve_pct` running dict is computed alongside the existing
sector/cluster dicts in the NAV pass (HEDGE_CASH's total adds `inputs.cash`
per `includes_account_cash`). `size_new_position` gains a `sleeve_room`
parameter, applied with the same "can only shrink, never grow" semantics as
`sector_room`/`cluster_room`. A new `size_speculative_position` function
handles SPECULATIVE's slot-based sizing (`slot_pct` of NAV per slot, capped
at `slot_count` concurrent SPECULATIVE positions) instead of conviction
scaling, with the same `sleeve_room` and cash-available caps applied after.

"Never averaged down": a guard function `averaging_down_blocked(current_price, avg_cost) -> bool`
in `core/sleeves.py`, wired in wherever a SPECULATIVE BUY targets an
already-held ticker. Noted limitation: no code path in this app currently
proposes a BUY into an already-held ticker at all (`orchestrator.py`'s
new-candidate loop explicitly skips anything in `held_set`), so this guard
has no caller today — it exists so the rule is enforced the moment such a
path is added, not before.

## Sustained-breach advisory

Once per run, per sleeve: compute weight, call `update_breach_streak` against
the persisted `SleeveBreachState` row, write the result back. At
`streak_days >= breach_sustain_days`, emit `RiskEvent(type="REBALANCE_ADVISORY")`
and add an entry to a new `PortfolioHealth.sleeve_band_breaches: list[SleeveBreachAdvisory]`
(dataclass: `sleeve`, `direction`, `weight_pct`, `streak_days`). Advisory
only — no order is generated, per explicit user answer.

## Speculative-look warning

In the new-candidate BUY loop, after `size_new_position` approves a BUY for a
ticker whose resolved sleeve is SWING (the default), call
`speculative_look_reasons` against that candidate's screener fundamentals.
If non-empty, attach the reasons to the `ActionItem` (new field
`speculative_warning: list[str]`) and the persisted `Proposal` (folded into
`risk_checks_json` isn't right since that's exit-trigger-shaped — add a new
`Proposal.speculative_warning_json` column, nullable). Warning only; the BUY
still proceeds as SWING.

## Out of scope here (explicitly deferred)

- Part 4's runner rule (30%-NAV trim, SPECULATIVE→SWING reclass at 15%) —
  this spec only builds the `reclassify_sleeve` method and `hard_stop`
  trigger it will need.
- UI changes (Part 5) — sleeve becomes available on the data model; no
  screen work here.
