# Sleeve Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every position a non-drifting sleeve (CORE/HEDGE_CASH/SWING/SPECULATIVE), gate the risk manager's exit machinery and new-BUY sizing by sleeve, and surface sustained band breaches as an advisory — no forced trades.

**Architecture:** A new pure module `core/sleeves.py` holds sleeve resolution, drift detection, band-room math, breach-streak tracking, and the speculative-look heuristic — all pure functions, no I/O, matching `core/risk_rules.py`'s style. `core/models.py`/`core/portfolio.py` store and assign the sleeve once, at position-creation time. `core/risk_rules.py` and `core/orchestrator.py` wire sleeve into exit evaluation and sizing.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (declarative, no migration framework — hand-run `ALTER TABLE`), Pydantic v2 config models, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-sleeve-architecture-design.md`

## Global Constraints

- No migration framework exists (`core/db.py`'s `create_all` only creates missing tables). New columns on existing tables (`positions.sleeve`, `proposals.speculative_warning_json`) require a hand-run `ALTER TABLE` + backfill against `data/z_money.db`; new tables (`SleeveBreachState`) are handled by `create_all` automatically.
- Every new pure function goes in `core/sleeves.py` unless it's a held-position exit trigger (those stay in `core/risk_rules.py`, next to `trailing_stop_breached`/`profit_band_crossed`).
- Sleeve ticker lists: CORE=`[VTI, VGT]`, HEDGE_CASH=`[IAU]` (+account cash), SPECULATIVE=`[RKLB, SOFI]`, everything else defaults to SWING. Targets/bands: CORE 50% (40–65), HEDGE_CASH 13% (8–25), SWING 30% (15–40), SPECULATIVE 7% (0–12).
- `breach_sustain_days=10`, `breach_margin_pct=5.0` — a REBALANCE advisory only, never a forced order.
- SPECULATIVE: 5 slots × 2.5% NAV each, hard stop at −60% from `avg_cost`, reclassifies to SWING at 15% NAV (Part 4 wires the trigger — this plan only adds the `reclassify_sleeve` method it will call).
- Run the full test suite (`.venv/bin/python -m pytest tests/`) after every task; it must stay green.

---

### Task 1: Config models for sleeves

**Files:**
- Modify: `core/config.py` (add after `BudgetConfig`, before `Config`)
- Test: `tests/test_config.py` (create if it doesn't exist — check first)

**Interfaces:**
- Produces: `SleeveConfig`, `SleevesConfig`, `SpeculativeLookConfig` classes; `Config.sleeves: SleevesConfig`, `Config.speculative_look: SpeculativeLookConfig`.

- [ ] **Step 1: Check for an existing config test file**

Run: `ls tests/test_config.py 2>/dev/null || echo "none"`

If it exists, read it first to match its style before adding to it.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_config.py` (create the file with this content if it didn't exist):

```python
from core.config import Config, SleeveConfig, SleevesConfig, SpeculativeLookConfig


class TestSleevesConfig:
    def test_defaults_seed_the_four_sleeves(self):
        sleeves = SleevesConfig()
        assert set(sleeves.definitions.keys()) == {"CORE", "HEDGE_CASH", "SWING", "SPECULATIVE"}
        assert sleeves.definitions["CORE"].tickers == ["VTI", "VGT"]
        assert sleeves.definitions["HEDGE_CASH"].tickers == ["IAU"]
        assert sleeves.definitions["HEDGE_CASH"].includes_account_cash is True
        assert sleeves.definitions["SWING"].tickers == []
        assert sleeves.definitions["SPECULATIVE"].tickers == ["RKLB", "SOFI"]
        assert sleeves.definitions["SPECULATIVE"].slot_count == 5
        assert sleeves.definitions["SPECULATIVE"].slot_pct == 2.5
        assert sleeves.definitions["SPECULATIVE"].hard_stop_pct == -60
        assert sleeves.definitions["SPECULATIVE"].reclass_at_pct == 15
        assert sleeves.default_sleeve == "SWING"
        assert sleeves.breach_sustain_days == 10
        assert sleeves.breach_margin_pct == 5.0

    def test_bands_match_target(self):
        sleeves = SleevesConfig()
        core = sleeves.definitions["CORE"]
        assert (core.target_pct, core.band_low_pct, core.band_high_pct) == (50, 40, 65)
        hedge = sleeves.definitions["HEDGE_CASH"]
        assert (hedge.target_pct, hedge.band_low_pct, hedge.band_high_pct) == (13, 8, 25)
        swing = sleeves.definitions["SWING"]
        assert (swing.target_pct, swing.band_low_pct, swing.band_high_pct) == (30, 15, 40)
        spec = sleeves.definitions["SPECULATIVE"]
        assert (spec.target_pct, spec.band_low_pct, spec.band_high_pct) == (7, 0, 12)


class TestSpeculativeLookConfig:
    def test_default_market_cap_threshold(self):
        assert SpeculativeLookConfig().market_cap_below_usd == 10_000_000_000


class TestConfigIncludesSleeves:
    def test_config_default_has_sleeves_and_speculative_look(self):
        config = Config()
        assert isinstance(config.sleeves, SleevesConfig)
        assert isinstance(config.speculative_look, SpeculativeLookConfig)
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'SleeveConfig'`

- [ ] **Step 4: Implement the config models**

In `core/config.py`, add this block after `class BudgetConfig(BaseModel): ...` and before `class Config(BaseModel):`:

```python
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
            slot_count=5, slot_pct=2.5, hard_stop_pct=-60, reclass_at_pct=15,
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
```

Then in `class Config(BaseModel):`, add two fields after `briefing: BriefingConfig = BriefingConfig()`:

```python
    sleeves: SleevesConfig = SleevesConfig()
    speculative_look: SpeculativeLookConfig = SpeculativeLookConfig()
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 6: Add the sleeves section to config.yaml**

Read `config.yaml`'s `conviction_scaling:` block first to match indentation style, then add near it (after the `risk:` section is fine):

```yaml
sleeves:
  default_sleeve: SWING
  breach_sustain_days: 10
  breach_margin_pct: 5.0
  definitions:
    CORE:        { target_pct: 50, band_low_pct: 40, band_high_pct: 65, tickers: [VTI, VGT] }
    HEDGE_CASH:  { target_pct: 13, band_low_pct: 8,  band_high_pct: 25, tickers: [IAU], includes_account_cash: true }
    SWING:       { target_pct: 30, band_low_pct: 15, band_high_pct: 40, tickers: [] }
    SPECULATIVE: { target_pct: 7,  band_low_pct: 0,  band_high_pct: 12, tickers: [RKLB, SOFI], slot_count: 5, slot_pct: 2.5, hard_stop_pct: -60, reclass_at_pct: 15 }

speculative_look:
  market_cap_below_usd: 10000000000
```

Run `.venv/bin/python -c "from core.config import load_config; print(load_config('config.yaml').sleeves.definitions.keys())"` and confirm it prints all four sleeve names with no error.

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: all pass, no regressions.

```bash
git add core/config.py config.yaml tests/test_config.py
git commit -m "$(cat <<'EOF'
Add sleeve and speculative-look config models

Seeds the four sleeves (CORE/HEDGE_CASH/SWING/SPECULATIVE) with the
targets, bands, and per-sleeve rules from the approved design spec.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `core/sleeves.py` — pure sleeve logic

**Files:**
- Create: `core/sleeves.py`
- Test: `tests/test_sleeves.py`

**Interfaces:**
- Consumes: `SleeveConfig`, `SleevesConfig`, `SpeculativeLookConfig` from Task 1.
- Produces: `resolve_sleeve(ticker, config) -> str`; `SleeveDrift` dataclass; `find_sleeve_drift(holdings, config) -> list[SleeveDrift]`; `sleeve_room(current_pct, sleeve_config) -> float`; `SleeveBreachStatus` dataclass; `update_breach_streak(previous, weight_pct, sleeve_config, margin_pct) -> SleeveBreachStatus`; `speculative_look_reasons(market_cap_usd, free_cash_flow, trailing_pe, config) -> list[str]`; `averaging_down_blocked(current_price, avg_cost) -> bool`. All consumed by later tasks.

- [ ] **Step 1: Write failing tests for `resolve_sleeve`**

Create `tests/test_sleeves.py`:

```python
from core.config import SleeveConfig, SleevesConfig, SpeculativeLookConfig
from core.sleeves import (
    SleeveBreachStatus,
    SleeveDrift,
    averaging_down_blocked,
    find_sleeve_drift,
    resolve_sleeve,
    sleeve_room,
    speculative_look_reasons,
    update_breach_streak,
)

SLEEVES = SleevesConfig()


class TestResolveSleeve:
    def test_core_ticker_resolves_to_core(self):
        assert resolve_sleeve("VTI", SLEEVES) == "CORE"
        assert resolve_sleeve("VGT", SLEEVES) == "CORE"

    def test_hedge_cash_ticker_resolves(self):
        assert resolve_sleeve("IAU", SLEEVES) == "HEDGE_CASH"

    def test_speculative_ticker_resolves(self):
        assert resolve_sleeve("RKLB", SLEEVES) == "SPECULATIVE"
        assert resolve_sleeve("SOFI", SLEEVES) == "SPECULATIVE"

    def test_unlisted_ticker_defaults_to_swing(self):
        assert resolve_sleeve("NVDA", SLEEVES) == "SWING"
        assert resolve_sleeve("SOME_NEW_NAME", SLEEVES) == "SWING"

    def test_case_insensitive(self):
        assert resolve_sleeve("vti", SLEEVES) == "CORE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.sleeves'`

- [ ] **Step 3: Implement `resolve_sleeve` (minimal)**

Create `core/sleeves.py`:

```python
"""Sleeve bookkeeping — pure functions, no I/O, no ORM coupling. Mirrors
core/risk_rules.py's style: everything here is a deterministic calculation
over plain values, called by core/portfolio.py (assignment), core/risk_rules.py
(exit gating), and core/orchestrator.py (wiring, persistence).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.config import SleeveConfig, SleevesConfig, SpeculativeLookConfig


def resolve_sleeve(ticker: str, config: SleevesConfig) -> str:
    """CORE/HEDGE_CASH/SPECULATIVE are closed ticker lists (config-driven,
    same pattern as UniverseConfig.cluster_overrides); anything else falls
    back to default_sleeve (SWING) — every organically-screened new BUY
    lands there unless explicitly added to one of the closed lists."""
    ticker = ticker.upper()
    for name, sleeve in config.definitions.items():
        if sleeve.tickers and ticker in {t.upper() for t in sleeve.tickers}:
            return name
    return config.default_sleeve
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestResolveSleeve -v`
Expected: PASS (5 tests). The rest of the file's imports (`SleeveBreachStatus`, etc.) will still fail — that's expected until later steps.

- [ ] **Step 5: Write failing tests for `find_sleeve_drift`**

Add to `tests/test_sleeves.py`:

```python
class TestFindSleeveDrift:
    def test_no_drift_when_stored_matches_resolved(self):
        holdings = [("VTI", "CORE"), ("NVDA", "SWING"), ("IAU", "HEDGE_CASH")]
        assert find_sleeve_drift(holdings, SLEEVES) == []

    def test_flags_mismatch(self):
        holdings = [("VTI", "SWING")]  # someone edited config after VTI was already tagged CORE
        drift = find_sleeve_drift(holdings, SLEEVES)
        assert drift == [SleeveDrift(ticker="VTI", stored_sleeve="SWING", resolved_sleeve="CORE")]

    def test_multiple_mismatches_all_reported(self):
        holdings = [("VTI", "SWING"), ("RKLB", "SWING"), ("NVDA", "SWING")]
        drift = find_sleeve_drift(holdings, SLEEVES)
        assert {d.ticker for d in drift} == {"VTI", "RKLB"}
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestFindSleeveDrift -v`
Expected: FAIL — `ImportError: cannot import name 'SleeveDrift'`

- [ ] **Step 7: Implement `SleeveDrift` / `find_sleeve_drift`**

Add to `core/sleeves.py`:

```python
@dataclass(frozen=True)
class SleeveDrift:
    ticker: str
    stored_sleeve: str
    resolved_sleeve: str


def find_sleeve_drift(holdings: list[tuple[str, str]], config: SleevesConfig) -> list[SleeveDrift]:
    """Startup reconciliation check: sleeve is assigned once at position-open
    time and never auto-corrected, so editing config.yaml's ticker lists
    afterward can silently orphan a position's stored sleeve. This never
    fixes anything — it only surfaces the mismatch (ticker, run_live_briefing.py
    and api/server.py log it as a warning) so the user decides."""
    drift = []
    for ticker, stored in holdings:
        resolved = resolve_sleeve(ticker, config)
        if resolved != stored:
            drift.append(SleeveDrift(ticker=ticker, stored_sleeve=stored, resolved_sleeve=resolved))
    return drift
```

- [ ] **Step 8: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestFindSleeveDrift -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Write failing tests for `sleeve_room`**

Add to `tests/test_sleeves.py`:

```python
class TestSleeveRoom:
    def test_room_when_under_band(self):
        swing = SLEEVES.definitions["SWING"]  # band_high_pct=40
        assert sleeve_room(20.0, swing) == 20.0

    def test_zero_room_when_at_band_high(self):
        swing = SLEEVES.definitions["SWING"]
        assert sleeve_room(40.0, swing) == 0.0

    def test_zero_room_never_negative_when_over_band(self):
        swing = SLEEVES.definitions["SWING"]
        assert sleeve_room(55.0, swing) == 0.0
```

- [ ] **Step 10: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestSleeveRoom -v`
Expected: FAIL — `ImportError: cannot import name 'sleeve_room'`

- [ ] **Step 11: Implement `sleeve_room`**

Add to `core/sleeves.py`:

```python
def sleeve_room(current_pct: float, sleeve_config: SleeveConfig) -> float:
    """Same shape as size_new_position's sector_room/cluster_room: how much
    more this sleeve can absorb before hitting its upper band. Over the
    band -> zero room -> size_new_position's min_order_value_usd floor
    rejects the BUY entirely, which is "blocks new BUYs into that sleeve,"
    not a separate hard gate."""
    return max(0.0, sleeve_config.band_high_pct - current_pct)
```

- [ ] **Step 12: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestSleeveRoom -v`
Expected: PASS (3 tests)

- [ ] **Step 13: Write failing tests for `update_breach_streak`**

Add to `tests/test_sleeves.py`:

```python
class TestUpdateBreachStreak:
    def setup_method(self):
        self.swing = SLEEVES.definitions["SWING"]  # band 15-40, target 30

    def test_within_band_resets_to_zero(self):
        previous = SleeveBreachStatus(direction="OVER", streak_days=6)
        result = update_breach_streak(previous, weight_pct=30.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction=None, streak_days=0)

    def test_breach_within_margin_does_not_count(self):
        # band_high=40, +5 margin -> only >45 counts; 43 is over-band but not by enough
        previous = SleeveBreachStatus(direction=None, streak_days=0)
        result = update_breach_streak(previous, weight_pct=43.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction=None, streak_days=0)

    def test_first_day_over_margin_starts_streak_at_one(self):
        previous = SleeveBreachStatus(direction=None, streak_days=0)
        result = update_breach_streak(previous, weight_pct=46.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="OVER", streak_days=1)

    def test_same_direction_continues_streak(self):
        previous = SleeveBreachStatus(direction="OVER", streak_days=9)
        result = update_breach_streak(previous, weight_pct=47.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="OVER", streak_days=10)

    def test_under_band_by_more_than_margin_streaks_under(self):
        # band_low=15, -5 margin -> only <10 counts
        previous = SleeveBreachStatus(direction=None, streak_days=0)
        result = update_breach_streak(previous, weight_pct=8.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="UNDER", streak_days=1)

    def test_direction_flip_resets_streak_to_one(self):
        previous = SleeveBreachStatus(direction="OVER", streak_days=9)
        result = update_breach_streak(previous, weight_pct=8.0, sleeve_config=self.swing, margin_pct=5.0)
        assert result == SleeveBreachStatus(direction="UNDER", streak_days=1)
```

- [ ] **Step 14: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestUpdateBreachStreak -v`
Expected: FAIL — `ImportError: cannot import name 'SleeveBreachStatus'`

- [ ] **Step 15: Implement `SleeveBreachStatus` / `update_breach_streak`**

Add to `core/sleeves.py`:

```python
BreachDirection = Literal["OVER", "UNDER"]


@dataclass(frozen=True)
class SleeveBreachStatus:
    direction: BreachDirection | None
    streak_days: int


def update_breach_streak(
    previous: SleeveBreachStatus, weight_pct: float, sleeve_config: SleeveConfig, margin_pct: float
) -> SleeveBreachStatus:
    """A breach only counts once it's more than margin_pct beyond the
    nearest band edge (Part 2: "a breach of more than 5 percentage points").
    The streak continues only if today's direction matches yesterday's;
    anything else (cleared, or flipped to the opposite edge) restarts it."""
    if weight_pct > sleeve_config.band_high_pct + margin_pct:
        direction: BreachDirection | None = "OVER"
    elif weight_pct < sleeve_config.band_low_pct - margin_pct:
        direction = "UNDER"
    else:
        direction = None

    if direction is None:
        return SleeveBreachStatus(direction=None, streak_days=0)
    if previous.direction == direction:
        return SleeveBreachStatus(direction=direction, streak_days=previous.streak_days + 1)
    return SleeveBreachStatus(direction=direction, streak_days=1)
```

- [ ] **Step 16: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestUpdateBreachStreak -v`
Expected: PASS (6 tests)

- [ ] **Step 17: Write failing tests for `speculative_look_reasons`**

Add to `tests/test_sleeves.py`:

```python
LOOK = SpeculativeLookConfig()  # market_cap_below_usd=10_000_000_000


class TestSpeculativeLookReasons:
    def test_no_reasons_for_a_clean_large_cap(self):
        reasons = speculative_look_reasons(
            market_cap_usd=500_000_000_000, free_cash_flow=5_000_000_000, trailing_pe=25.0, config=LOOK
        )
        assert reasons == []

    def test_flags_small_market_cap(self):
        reasons = speculative_look_reasons(
            market_cap_usd=2_000_000_000, free_cash_flow=100_000_000, trailing_pe=20.0, config=LOOK
        )
        assert any("market cap" in r for r in reasons)

    def test_flags_negative_free_cash_flow(self):
        reasons = speculative_look_reasons(
            market_cap_usd=50_000_000_000, free_cash_flow=-10_000_000, trailing_pe=20.0, config=LOOK
        )
        assert any("free cash flow" in r for r in reasons)

    def test_flags_no_earnings(self):
        reasons = speculative_look_reasons(
            market_cap_usd=50_000_000_000, free_cash_flow=100_000_000, trailing_pe=None, config=LOOK
        )
        assert any("earnings" in r for r in reasons)

    def test_multiple_reasons_all_reported(self):
        reasons = speculative_look_reasons(
            market_cap_usd=1_000_000_000, free_cash_flow=-1.0, trailing_pe=None, config=LOOK
        )
        assert len(reasons) == 3

    def test_missing_market_cap_is_not_treated_as_small(self):
        # None means unknown, not "below threshold" — don't manufacture a signal from missing data
        reasons = speculative_look_reasons(
            market_cap_usd=None, free_cash_flow=100_000_000, trailing_pe=20.0, config=LOOK
        )
        assert reasons == []
```

- [ ] **Step 18: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestSpeculativeLookReasons -v`
Expected: FAIL — `ImportError: cannot import name 'speculative_look_reasons'`

- [ ] **Step 19: Implement `speculative_look_reasons`**

Add to `core/sleeves.py`:

```python
def speculative_look_reasons(
    market_cap_usd: float | None,
    free_cash_flow: float | None,
    trailing_pe: float | None,
    config: SpeculativeLookConfig,
) -> list[str]:
    """Informational only — never blocks a BUY, never reclassifies it.
    Surfaced on a new BUY that defaulted to SWING so the user can manually
    reclassify to SPECULATIVE before placing the order, per explicit
    request. Missing data (None) is never treated as a positive signal —
    same "exclude, don't impute" philosophy as scoring.py's null handling."""
    reasons: list[str] = []
    if market_cap_usd is not None and market_cap_usd < config.market_cap_below_usd:
        reasons.append(f"market cap ${market_cap_usd:,.0f} is below the ${config.market_cap_below_usd:,.0f} speculative-look threshold")
    if free_cash_flow is not None and free_cash_flow < 0:
        reasons.append("negative free cash flow")
    if trailing_pe is None:
        reasons.append("no earnings (no positive trailing P/E)")
    return reasons
```

- [ ] **Step 20: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestSpeculativeLookReasons -v`
Expected: PASS (6 tests)

- [ ] **Step 21: Write failing tests for `averaging_down_blocked`**

Add to `tests/test_sleeves.py`:

```python
class TestAveragingDownBlocked:
    def test_blocks_when_price_below_avg_cost(self):
        assert averaging_down_blocked(current_price=10.0, avg_cost=15.0) is True

    def test_allows_when_price_above_avg_cost(self):
        assert averaging_down_blocked(current_price=20.0, avg_cost=15.0) is False

    def test_allows_at_exactly_avg_cost(self):
        assert averaging_down_blocked(current_price=15.0, avg_cost=15.0) is False
```

- [ ] **Step 22: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py::TestAveragingDownBlocked -v`
Expected: FAIL — `ImportError: cannot import name 'averaging_down_blocked'`

- [ ] **Step 23: Implement `averaging_down_blocked`**

Add to `core/sleeves.py`:

```python
def averaging_down_blocked(current_price: float, avg_cost: float) -> bool:
    """SPECULATIVE: "never averaged down" — a BUY that would add to an
    already-held SPECULATIVE position at a price below its cost basis is
    blocked outright. No caller wires this in yet: core/orchestrator.py's
    new-candidate loop already skips every ticker in held_set before sizing
    runs (see its `if ticker in held_set: continue`), so there is currently
    no code path that proposes topping up an existing position at all. This
    function exists so the rule is enforced the moment such a path is
    added, not before."""
    return current_price < avg_cost
```

- [ ] **Step 24: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sleeves.py -v`
Expected: all PASS (23 tests total in this file)

- [ ] **Step 25: Run the full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: all pass.

```bash
git add core/sleeves.py tests/test_sleeves.py
git commit -m "$(cat <<'EOF'
Add core/sleeves.py: sleeve resolution, drift, room, breach-streak, speculative-look

Pure functions covering sleeve assignment, the startup drift check,
band-edge room math for new-BUY sizing, sustained-breach streak
tracking, the informational speculative-look warning, and the
never-averaged-down guard for SPECULATIVE.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Schema changes and data migration

**Files:**
- Modify: `core/models.py`
- Test: existing `tests/conftest.py` fixtures exercise this implicitly; add explicit assertions to a new `tests/test_models.py`

**Interfaces:**
- Produces: `Position.sleeve: str` column; `SleeveBreachState` model (`sleeve` PK, `direction`, `streak_days`, `last_run_id`); `Proposal.speculative_warning_json: str | None` column.

- [ ] **Step 1: Write a failing test**

Create `tests/test_models.py`:

```python
import datetime as dt

from core.db import init_db, make_engine, make_session_factory
from core.models import Position, Proposal, Run, SleeveBreachState


def test_position_has_sleeve_column():
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    position = Position(
        ticker="NVDA", qty=1, avg_cost=100.0, opened_at=dt.datetime(2026, 1, 1),
        source="manual", sleeve="SWING",
    )
    session.add(position)
    session.flush()
    assert session.get(Position, position.id).sleeve == "SWING"


def test_sleeve_breach_state_round_trips():
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    session.add(Run(id=1, started_at=dt.datetime(2026, 1, 1), status="succeeded", config_snapshot_json="{}"))
    session.flush()
    state = SleeveBreachState(sleeve="SWING", direction="OVER", streak_days=3, last_run_id=1)
    session.add(state)
    session.flush()
    fetched = session.get(SleeveBreachState, "SWING")
    assert (fetched.direction, fetched.streak_days, fetched.last_run_id) == ("OVER", 3, 1)


def test_proposal_speculative_warning_json_defaults_to_none():
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    session.add(Run(id=1, started_at=dt.datetime(2026, 1, 1), status="succeeded", config_snapshot_json="{}"))
    session.flush()
    proposal = Proposal(
        run_id=1, ticker="NVDA", action="BUY", quantity=1, order_type="LIMIT", limit_price=100.0,
        est_cost=100.0, conviction=60.0, rationale="", risk_checks_json="[]", status="proposed",
        created_at=dt.datetime(2026, 1, 1),
    )
    session.add(proposal)
    session.flush()
    assert session.get(Proposal, proposal.id).speculative_warning_json is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL — `TypeError: 'sleeve' is an invalid keyword argument for Position` (and `ImportError` for `SleeveBreachState`).

- [ ] **Step 3: Implement the schema changes**

In `core/models.py`, add to `class Position`, right after `peak_price_since_activation`:

```python
    # Assigned once at position-open time (core/portfolio.py's three
    # Position(...) construction sites) via core.sleeves.resolve_sleeve.
    # Never drifts afterward except through PortfolioService.reclassify_sleeve
    # (Part 4's SPECULATIVE-crosses-15%-NAV rule) — editing config.yaml's
    # ticker lists after the fact does NOT retroactively move a stored
    # position; core.sleeves.find_sleeve_drift is the startup check that
    # surfaces (never auto-fixes) that mismatch.
    sleeve: Mapped[str] = mapped_column(String, nullable=False, default="SWING")
```

Add to `class Proposal`, right after `fill_price`:

```python
    # Informational only (core.sleeves.speculative_look_reasons) — set when
    # a new BUY defaulted to SWING but has characteristics (small market
    # cap, negative FCF, no earnings) that look SPECULATIVE. Never blocks
    # the BUY. NULL for every proposal type except a fresh SWING new-BUY,
    # and for every proposal recorded before this column existed.
    speculative_warning_json: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Add a new model after `class RiskEvent(Base): ...`:

```python
class SleeveBreachState(Base):
    """One row per sleeve, updated once per run — core.sleeves.update_breach_streak's
    persisted state. `direction`/`streak_days` mirror SleeveBreachStatus;
    `last_run_id` is audit trail, not used by the streak logic itself."""

    __tablename__ = "sleeve_breach_state"

    sleeve: Mapped[str] = mapped_column(String, primary_key=True)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)  # 'OVER' | 'UNDER' | NULL
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite — expect failures from the now-required `sleeve` field**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -60`

Expected: some failures in `tests/test_portfolio.py`, `tests/test_orchestrator.py`, `tests/test_ibkr_flex.py` wherever a `Position(...)` is constructed directly in test setup without a `sleeve` kwarg — SQLAlchemy will raise `IntegrityError: NOT NULL constraint failed` or similar, OR pass silently with the model-level `default="SWING"` kicking in (SQLAlchemy Python-side defaults apply on flush even without an explicit kwarg, so most existing tests should keep passing unchanged). Read the actual failures before assuming which; do not skip this step.

If any test directly instantiates `Position(...)` and asserts on `.sleeve` implicitly (unlikely, since the field is brand new), fix it there. Otherwise this step is a checkpoint, not expected to require edits — the Python-side `default="SWING"` on the mapped column covers every existing direct-construction test.

- [ ] **Step 6: Migrate the real database**

This is a one-time, hand-run migration against the live `data/z_money.db` — there is no migration framework (see Global Constraints). Run each statement individually and read the output before proceeding to the next:

```bash
cd /Users/zoravarsingh/zmoney
sqlite3 data/z_money.db "ALTER TABLE positions ADD COLUMN sleeve TEXT NOT NULL DEFAULT 'SWING';"
sqlite3 data/z_money.db "
UPDATE positions SET sleeve = 'CORE' WHERE ticker IN ('VTI', 'VGT');
UPDATE positions SET sleeve = 'HEDGE_CASH' WHERE ticker IN ('IAU');
UPDATE positions SET sleeve = 'SPECULATIVE' WHERE ticker IN ('RKLB', 'SOFI');
"
sqlite3 data/z_money.db ".headers on" ".mode column" "SELECT ticker, sleeve FROM positions ORDER BY ticker;"
```

Verify the output shows: VTI/VGT=CORE, IAU=HEDGE_CASH, RKLB/SOFI=SPECULATIVE, and every other ticker (AMD, CEG, CLS, CRDO, MP, MRVL, MSFT, NBIS, NVDA, PLTR, VRT) = SWING (the column default already gave them this — the UPDATE statements above only need to touch the three non-default sleeves).

```bash
sqlite3 data/z_money.db "ALTER TABLE proposals ADD COLUMN speculative_warning_json TEXT;"
sqlite3 data/z_money.db "SELECT COUNT(*) FROM proposals WHERE speculative_warning_json IS NOT NULL;"
```

Expected: `0` (every existing proposal backfills to NULL, which is the correct "no warning was computed for this historical row" state).

- [ ] **Step 7: Commit**

```bash
git add core/models.py tests/test_models.py
git commit -m "$(cat <<'EOF'
Add sleeve/breach-state schema: Position.sleeve, SleeveBreachState, Proposal.speculative_warning_json

New columns hand-migrated against data/z_money.db (no migration
framework exists yet) — positions backfilled from the sleeve ticker
lists in the approved design spec, proposals backfilled to NULL.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `core/portfolio.py` — assign sleeve at creation, never drift

**Files:**
- Modify: `core/portfolio.py`
- Modify: `tests/conftest.py` (only if the `portfolio` fixture needs a `sleeves` override — check first; default should just work)
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `resolve_sleeve` from `core/sleeves.py` (Task 2); `SleevesConfig` from `core/config.py` (Task 1).
- Produces: `PortfolioService(session, config=..., sleeves=...)`; `PortfolioService.reclassify_sleeve(position_id, new_sleeve) -> Position`.

- [ ] **Step 1: Read the existing test file's structure**

Run: `grep -n "^class Test" tests/test_portfolio.py` to see existing test class names before adding new ones in the matching style.

- [ ] **Step 2: Write failing tests**

Add to `tests/test_portfolio.py`:

```python
class TestSleeveAssignment:
    def test_manual_position_gets_resolved_sleeve(self, session, portfolio):
        position = portfolio.add_manual_position("VTI", qty=1, avg_cost=300.0)
        assert position.sleeve == "CORE"

    def test_manual_position_defaults_to_swing(self, session, portfolio):
        position = portfolio.add_manual_position("NVDA", qty=1, avg_cost=100.0)
        assert position.sleeve == "SWING"

    def test_mark_filled_new_buy_gets_resolved_sleeve(self, session, portfolio):
        position = portfolio.mark_filled("RKLB", "BUY", qty=10, fill_price=20.0)
        assert position.sleeve == "SPECULATIVE"

    def test_reconcile_new_row_gets_resolved_sleeve(self, session, portfolio):
        from core.portfolio import ImportedPosition
        result = portfolio.reconcile([ImportedPosition(ticker="IAU", qty=5, avg_cost=80.0)])
        position = portfolio.get_position("IAU")
        assert position.sleeve == "HEDGE_CASH"

    def test_sleeve_does_not_change_on_top_up(self, session, portfolio):
        position = portfolio.mark_filled("NVDA", "BUY", qty=5, fill_price=100.0)
        assert position.sleeve == "SWING"
        position = portfolio.mark_filled("NVDA", "BUY", qty=5, fill_price=110.0)
        assert position.sleeve == "SWING"

    def test_reclassify_sleeve_updates_stored_value(self, session, portfolio):
        position = portfolio.add_manual_position("RKLB", qty=1, avg_cost=20.0)
        assert position.sleeve == "SPECULATIVE"
        updated = portfolio.reclassify_sleeve(position.id, "SWING")
        assert updated.sleeve == "SWING"
        assert portfolio.get_position("RKLB").sleeve == "SWING"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_portfolio.py::TestSleeveAssignment -v`
Expected: FAIL — every test gets `AssertionError: 'SWING' != 'CORE'` etc. (the Python-side column default fires, but nothing calls `resolve_sleeve` yet), and `test_reclassify_sleeve_updates_stored_value` fails with `AttributeError: 'PortfolioService' object has no attribute 'reclassify_sleeve'`.

- [ ] **Step 4: Implement the wiring**

In `core/portfolio.py`, update the imports:

```python
from core.config import PortfolioConfig, SleevesConfig
from core.models import Position, PositionImport, SleeveBreachState  # SleeveBreachState only if referenced elsewhere; otherwise leave as-is
from core.sleeves import resolve_sleeve
```

(Only add the `SleeveBreachState` import if you end up needing it here — Task 4 does not touch that table, so leave the import as `from core.models import Position, PositionImport` unchanged.)

Update the constructor:

```python
class PortfolioService:
    def __init__(self, session: Session, config: PortfolioConfig | None = None, sleeves: SleevesConfig | None = None):
        self.session = session
        self.config = config or PortfolioConfig()
        self.sleeves = sleeves or SleevesConfig()
```

In `add_manual_position`, change the `Position(...)` construction to include:

```python
        position = Position(
            ticker=ticker,
            qty=qty,
            avg_cost=avg_cost,
            opened_at=now,
            source="manual",
            last_verified_at=now,
            conviction_at_entry=conviction_at_entry,
            peak_price_since_activation=None,
            sleeve=resolve_sleeve(ticker, self.sleeves),
        )
```

In `mark_filled`'s BUY branch (the `if position is None:` block that creates a new `Position`), add the same `sleeve=resolve_sleeve(ticker, self.sleeves)` kwarg. The `else` branch (topping up an existing position) is untouched — it never re-assigns `sleeve`, which is exactly "does not drift."

In `reconcile`'s new-row branch (`if existing is None:`), add the same `sleeve=resolve_sleeve(ticker, self.sleeves)` kwarg.

Add a new method, near `edit_manual_position`:

```python
    def reclassify_sleeve(self, position_id: int, new_sleeve: str) -> Position:
        """The only writer of Position.sleeve besides initial assignment.
        Unused by anything in this codebase yet — reserved for Part 4's
        SPECULATIVE-crosses-15%-NAV-weight reclassification rule. Deliberately
        separate from edit_manual_position: reclassification is a distinct,
        rare, rule-triggered event, not a general field edit."""
        position = self.session.get(Position, position_id)
        if position is None:
            raise PortfolioError(f"no position with id {position_id}")
        position.sleeve = new_sleeve
        self.session.flush()
        return position
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: all PASS, including the new `TestSleeveAssignment` class and every pre-existing test in the file.

- [ ] **Step 6: Update `scripts/run_live_briefing.py`'s `PortfolioService` construction**

In `scripts/run_live_briefing.py`, change:

```python
    portfolio = PortfolioService(session, config=config.portfolio)
```

to:

```python
    portfolio = PortfolioService(session, config=config.portfolio, sleeves=config.sleeves)
```

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: all pass.

```bash
git add core/portfolio.py scripts/run_live_briefing.py tests/test_portfolio.py
git commit -m "$(cat <<'EOF'
Assign sleeve at position-creation time, never drift afterward

resolve_sleeve() runs at all three Position(...) construction sites
(manual entry, mark-filled new BUY, broker-sync reconciliation).
Topping up an existing position never touches its sleeve.
reclassify_sleeve() is the one explicit exception, reserved for
Part 4's SPECULATIVE-at-15%-NAV rule.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `core/risk_rules.py` — sleeve-gated exits and the hard stop

**Files:**
- Modify: `core/risk_rules.py`
- Test: `tests/test_risk_rules.py`

**Interfaces:**
- Consumes: nothing new from other tasks (pure function, sleeve/hard_stop_pct passed as plain values).
- Produces: `hard_stop_breached(current_price, avg_cost, hard_stop_pct) -> tuple[bool, dict]`; `ExitTriggerType` gains `"HARD_STOP"`; `evaluate_held_position(..., sleeve: str = "SWING", hard_stop_pct: float | None = None)`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_risk_rules.py`:

```python
class TestHardStopBreached:
    def test_breaches_at_or_below_threshold(self):
        breached, detail = hard_stop_breached(current_price=40.0, avg_cost=100.0, hard_stop_pct=-60)
        assert breached is True
        assert detail["gain_pct"] == pytest.approx(-60.0)

    def test_does_not_breach_above_threshold(self):
        breached, _ = hard_stop_breached(current_price=45.0, avg_cost=100.0, hard_stop_pct=-60)
        assert breached is False

    def test_no_cost_basis_never_breaches(self):
        breached, detail = hard_stop_breached(current_price=40.0, avg_cost=0.0, hard_stop_pct=-60)
        assert breached is False
        assert detail["reason"] == "no cost basis"


class TestEvaluateHeldPositionSleeveGating:
    def test_core_position_never_triggers_signal_based_exits(self):
        # Numbers that would trivially trigger TRAILING_STOP, PROFIT_BAND,
        # THESIS_DECAY, and CONVICTION_FLOOR all at once for a SWING position.
        evaluation = evaluate_held_position(
            ticker="VTI", current_price=50.0, avg_cost=100.0, peak_price=200.0, atr_14=1.0,
            conviction_now=10.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
            sleeve="CORE",
        )
        assert evaluation.triggers == []

    def test_hedge_cash_position_never_triggers_signal_based_exits(self):
        evaluation = evaluate_held_position(
            ticker="IAU", current_price=50.0, avg_cost=100.0, peak_price=200.0, atr_14=1.0,
            conviction_now=10.0, conviction_at_entry=90.0, scaling=SCALING, config=RISK,
            sleeve="HEDGE_CASH",
        )
        assert evaluation.triggers == []

    def test_swing_position_keeps_existing_behavior_by_default(self):
        # sleeve defaults to "SWING" — every pre-existing call site/test in
        # this file keeps working unchanged.
        evaluation = evaluate_held_position(
            ticker="AMD", current_price=105, avg_cost=100, peak_price=108, atr_14=2.0,
            conviction_now=70, conviction_at_entry=70, scaling=SCALING, config=RISK,
        )
        assert evaluation.has_exit_signal is False

    def test_speculative_position_ignores_conviction_floor_and_uses_hard_stop(self):
        # conviction_now=0 would trivially trigger CONVICTION_FLOOR on SWING;
        # SPECULATIVE must ignore it and only check the hard stop.
        evaluation = evaluate_held_position(
            ticker="RKLB", current_price=100.0, avg_cost=100.0, peak_price=150.0, atr_14=1.0,
            conviction_now=0.0, conviction_at_entry=50.0, scaling=SCALING, config=RISK,
            sleeve="SPECULATIVE", hard_stop_pct=-60,
        )
        assert evaluation.triggers == []

    def test_speculative_position_hard_stop_fires(self):
        evaluation = evaluate_held_position(
            ticker="RKLB", current_price=39.0, avg_cost=100.0, peak_price=150.0, atr_14=1.0,
            conviction_now=50.0, conviction_at_entry=50.0, scaling=SCALING, config=RISK,
            sleeve="SPECULATIVE", hard_stop_pct=-60,
        )
        assert evaluation.has_exit_signal is True
        assert evaluation.primary_trigger.type == "HARD_STOP"
```

Add the two new imports needed at the top of the test file if not already present: `hard_stop_breached` alongside the existing `from core.risk_rules import (...)` block (add it to that import list).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_risk_rules.py::TestHardStopBreached tests/test_risk_rules.py::TestEvaluateHeldPositionSleeveGating -v`
Expected: FAIL — `ImportError: cannot import name 'hard_stop_breached'`, then (once fixed) `TypeError: evaluate_held_position() got an unexpected keyword argument 'sleeve'`.

- [ ] **Step 3: Implement**

In `core/risk_rules.py`, change:

```python
ExitTriggerType = Literal["TRAILING_STOP", "PROFIT_BAND", "THESIS_DECAY"]
```

to:

```python
ExitTriggerType = Literal["TRAILING_STOP", "PROFIT_BAND", "THESIS_DECAY", "HARD_STOP"]
```

Add a new function right after `profit_band_crossed`:

```python
def hard_stop_breached(current_price: float, avg_cost: float, hard_stop_pct: float) -> tuple[bool, dict]:
    """SPECULATIVE's only exit besides the 15%-NAV reclass (Part 4): an
    absolute floor at hard_stop_pct from avg_cost (e.g. -60), unlike
    TRAILING_STOP/PROFIT_BAND/THESIS_DECAY/CONVICTION_FLOOR, none of which
    apply to this sleeve."""
    if not avg_cost:
        return False, {"reason": "no cost basis"}
    gain_pct = (current_price - avg_cost) / avg_cost * 100.0
    return gain_pct <= hard_stop_pct, {"gain_pct": gain_pct, "hard_stop_pct": hard_stop_pct}
```

Replace the whole `evaluate_held_position` function with:

```python
def evaluate_held_position(
    ticker: str,
    current_price: float,
    avg_cost: float,
    peak_price: float | None,
    atr_14: float | None,
    conviction_now: float,
    conviction_at_entry: float | None,
    scaling: ConvictionScalingConfig,
    config: RiskConfig,
    conviction_is_fresh: bool = True,
    sleeve: str = "SWING",
    hard_stop_pct: float | None = None,
) -> HeldPositionEvaluation:
    """`conviction_is_fresh=False` means `conviction_now` is a fallback, not
    a real score computed this run (see core/orchestrator.py) — thesis-decay
    is already guarded by `conviction_at_entry` being passed as None in that
    case, but the conviction floor has no such guard of its own, since it
    only looks at conviction_now. Suppressing it here keeps both triggers
    off a fabricated number, not just the one whose guard happened to cover it.

    `sleeve` gates which exit machinery applies at all (user-requested
    sleeve architecture): CORE and HEDGE_CASH get no signal-based exits
    whatsoever — they only ever exit via the concentration-based runner-rule
    trim, which lives outside this function. SPECULATIVE swaps all four
    triggers for a single hard_stop_pct floor. Only SWING runs the original
    four, in their original priority order."""
    if sleeve in ("CORE", "HEDGE_CASH"):
        return HeldPositionEvaluation(ticker=ticker, triggers=[])

    if sleeve == "SPECULATIVE":
        triggers: list[ExitTrigger] = []
        if hard_stop_pct is not None:
            stop_hit, stop_detail = hard_stop_breached(current_price, avg_cost, hard_stop_pct)
            if stop_hit:
                triggers.append(ExitTrigger(type="HARD_STOP", detail=stop_detail))
        return HeldPositionEvaluation(ticker=ticker, triggers=triggers)

    triggers = []

    stop_hit, stop_detail = trailing_stop_breached(current_price, peak_price, atr_14, conviction_now, scaling)
    if stop_hit:
        triggers.append(ExitTrigger(type="TRAILING_STOP", detail=stop_detail))

    profit_hit, profit_detail = profit_band_crossed(current_price, avg_cost, conviction_now, scaling)
    if profit_hit:
        triggers.append(ExitTrigger(type="PROFIT_BAND", detail=profit_detail))

    decay_hit, decay_detail = thesis_decay_triggered(conviction_now, conviction_at_entry, config)
    if decay_hit:
        triggers.append(ExitTrigger(type="THESIS_DECAY", detail=decay_detail))

    if conviction_is_fresh:
        floor_hit, floor_detail = conviction_floor_triggered(conviction_now, config)
        if floor_hit:
            triggers.append(ExitTrigger(type="CONVICTION_FLOOR", detail=floor_detail))

    return HeldPositionEvaluation(ticker=ticker, triggers=triggers)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_risk_rules.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: all pass — no other module calls `evaluate_held_position` with a positional argument in that range, so the new keyword-only-by-convention params (given defaults) don't break `core/orchestrator.py`'s existing call yet (Task 8 updates it deliberately).

```bash
git add core/risk_rules.py tests/test_risk_rules.py
git commit -m "$(cat <<'EOF'
Gate exit machinery by sleeve; add SPECULATIVE's hard stop

CORE/HEDGE_CASH get no signal-based exits. SPECULATIVE swaps
TRAILING_STOP/PROFIT_BAND/THESIS_DECAY/CONVICTION_FLOOR for a single
hard_stop_pct floor (new HARD_STOP trigger type). SWING is unchanged
and remains the default so every pre-existing caller/test keeps
working without modification.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `core/risk_rules.py` — sleeve-room BUY gating and SPECULATIVE sizing

**Files:**
- Modify: `core/risk_rules.py`
- Test: `tests/test_risk_rules.py`

**Interfaces:**
- Consumes: nothing new (takes a plain `sleeve_room: float | None` value — the orchestrator computes it via `core.sleeves.sleeve_room` before calling).
- Produces: `size_new_position(..., sleeve_room: float | None = None)`; `size_speculative_position(nav_usd, cash_available_usd, sleeve_room, open_speculative_slots, sleeve_config, config) -> SizingResult`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_risk_rules.py`:

```python
class TestSizeNewPositionSleeveRoom:
    def test_sleeve_room_caps_position_size(self):
        result = size_new_position(
            conviction_score=90, atr_pct_of_price=None, nav_usd=100_000, sector=None, cluster=None,
            current_sector_pct={}, current_cluster_pct={}, cash_available_usd=100_000,
            scaling=SCALING, config=RISK, sleeve_room=3.0,
        )
        assert result.approved is True
        assert result.position_pct == pytest.approx(3.0)
        assert any("sleeve room" in r for r in result.reasons)

    def test_zero_sleeve_room_rejects_the_buy(self):
        result = size_new_position(
            conviction_score=90, atr_pct_of_price=None, nav_usd=100_000, sector=None, cluster=None,
            current_sector_pct={}, current_cluster_pct={}, cash_available_usd=100_000,
            scaling=SCALING, config=RISK, sleeve_room=0.0,
        )
        assert result.approved is False

    def test_none_sleeve_room_means_uncapped(self):
        # existing callers that don't know about sleeves yet keep working
        result = size_new_position(
            conviction_score=90, atr_pct_of_price=None, nav_usd=100_000, sector=None, cluster=None,
            current_sector_pct={}, current_cluster_pct={}, cash_available_usd=100_000,
            scaling=SCALING, config=RISK,
        )
        assert result.approved is True
```

Before adding the next test class, make two changes to this test file's existing imports: change the existing `from core.config import ConvictionScalingConfig, RiskConfig` line to also import `SleeveConfig`:

```python
from core.config import ConvictionScalingConfig, RiskConfig, SleeveConfig
```

And add `size_speculative_position` to the existing `from core.risk_rules import (...)` block.

Then add:

```python
SPECULATIVE = SleeveConfig(
    target_pct=7, band_low_pct=0, band_high_pct=12, tickers=["RKLB", "SOFI"],
    slot_count=5, slot_pct=2.5, hard_stop_pct=-60, reclass_at_pct=15,
)


class TestSizeSpeculativePosition:
    def test_sizes_at_fixed_slot_pct_regardless_of_room(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=10.0,
            open_speculative_slots=1, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.approved is True
        assert result.position_pct == pytest.approx(2.5)
        assert result.position_usd == pytest.approx(2_500.0)

    def test_all_slots_filled_rejects(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=10.0,
            open_speculative_slots=5, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.approved is False
        assert any("slots filled" in r for r in result.reasons)

    def test_sleeve_room_caps_slot_size(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=1.0,
            open_speculative_slots=0, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.position_pct == pytest.approx(1.0)

    def test_cash_available_caps_position(self):
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=1_000, sleeve_room=10.0,
            open_speculative_slots=0, sleeve_config=SPECULATIVE, config=RISK,
        )
        assert result.position_usd == pytest.approx(1_000.0)

    def test_below_min_order_value_rejects(self):
        tiny_risk = RiskConfig(min_order_value_usd=10_000)
        result = size_speculative_position(
            nav_usd=100_000, cash_available_usd=100_000, sleeve_room=10.0,
            open_speculative_slots=0, sleeve_config=SPECULATIVE, config=tiny_risk,
        )
        assert result.approved is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_risk_rules.py::TestSizeNewPositionSleeveRoom tests/test_risk_rules.py::TestSizeSpeculativePosition -v`
Expected: FAIL — `TypeError: size_new_position() got an unexpected keyword argument 'sleeve_room'`, then `ImportError: cannot import name 'size_speculative_position'`.

- [ ] **Step 3: Implement**

In `core/risk_rules.py`, update `size_new_position`'s signature and body. Change the signature to add `sleeve_room: float | None = None` as the last parameter (before the closing `) -> SizingResult:`), and insert the sleeve-room cap right after the existing cluster-room cap block and before the cash-available check:

```python
    if cluster is not None:
        cluster_room = max(0.0, config.max_correlated_cluster_pct - current_cluster_pct.get(cluster, 0.0))
        if pct > cluster_room:
            reasons.append(f"capped by correlated-cluster room {cluster_room:.1f}% (cluster {cluster})")
            pct = cluster_room

    if sleeve_room is not None and pct > sleeve_room:
        reasons.append(f"capped by sleeve room {sleeve_room:.1f}%")
        pct = sleeve_room

    position_usd = nav_usd * (pct / 100.0)
```

(The existing `position_usd = nav_usd * (pct / 100.0)` line stays — just insert the new `if sleeve_room is not None:` block directly above it.)

Add `size_speculative_position` after `size_new_position`:

```python
def size_speculative_position(
    nav_usd: float,
    cash_available_usd: float,
    sleeve_room: float,
    open_speculative_slots: int,
    sleeve_config,  # core.config.SleeveConfig — the SPECULATIVE entry
    config: RiskConfig,
) -> SizingResult:
    """SPECULATIVE is "sized by slots not conviction: 5 slots at 2.5% NAV
    each" — no conviction_score parameter here at all, unlike
    size_new_position. Slot count and slot_pct both come from the
    SPECULATIVE sleeve's config entry, not a global RiskConfig field,
    since they only apply to this one sleeve."""
    reasons: list[str] = []

    if sleeve_config.slot_count is not None and open_speculative_slots >= sleeve_config.slot_count:
        return SizingResult(
            approved=False, position_pct=0.0, position_usd=0.0,
            reasons=[f"all {sleeve_config.slot_count} SPECULATIVE slots filled"],
        )

    pct = sleeve_config.slot_pct or 0.0
    if pct > sleeve_room:
        reasons.append(f"capped by sleeve room {sleeve_room:.1f}%")
        pct = sleeve_room

    position_usd = nav_usd * (pct / 100.0)
    if position_usd > cash_available_usd:
        reasons.append(f"capped by cash available ${cash_available_usd:,.0f}")
        position_usd = cash_available_usd
        pct = (position_usd / nav_usd * 100.0) if nav_usd > 0 else 0.0

    if position_usd < config.min_order_value_usd:
        reasons.append(f"below min_order_value_usd ${config.min_order_value_usd:,.0f}")
        return SizingResult(approved=False, position_pct=0.0, position_usd=0.0, reasons=reasons)

    return SizingResult(approved=True, position_pct=pct, position_usd=position_usd, reasons=reasons)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_risk_rules.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: all pass — `sleeve_room` defaults to `None` (uncapped), so `core/orchestrator.py`'s existing call to `size_new_position` (which doesn't pass it yet) is unaffected until Task 8.

```bash
git add core/risk_rules.py tests/test_risk_rules.py
git commit -m "$(cat <<'EOF'
Add sleeve-room BUY gating and SPECULATIVE's slot-based sizing

size_new_position gains an optional sleeve_room cap, same shape as
its existing sector/cluster room caps — over the sleeve's band blocks
the BUY by capping room to zero. size_speculative_position sizes by
fixed slot_pct of NAV and a slot_count ceiling instead of conviction.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `core/briefing.py` — carry sleeve data into the briefing

**Files:**
- Modify: `core/briefing.py`
- Test: `tests/test_briefing.py`

**Interfaces:**
- Produces: `ActionItem.speculative_warning: list[str] = field(default_factory=list)`; `SleeveBreachAdvisory` dataclass; `PortfolioHealth.sleeve_band_breaches: list[SleeveBreachAdvisory] = field(default_factory=list)`.

- [ ] **Step 1: Write failing tests**

Read `tests/test_briefing.py`'s imports first (`grep -n "^from\|^import" tests/test_briefing.py`) to match style, then add:

```python
class TestSpeculativeWarningOnActionItem:
    def test_defaults_to_empty_list(self):
        item = ActionItem(order=some_order_fixture(), headline="New position")
        assert item.speculative_warning == []

    def test_can_carry_reasons(self):
        item = ActionItem(order=some_order_fixture(), headline="New position", speculative_warning=["negative free cash flow"])
        assert item.speculative_warning == ["negative free cash flow"]


class TestSleeveBandBreachesOnPortfolioHealth:
    def test_defaults_to_empty_list(self):
        health = PortfolioHealth()
        assert health.sleeve_band_breaches == []

    def test_can_carry_advisories(self):
        advisory = SleeveBreachAdvisory(sleeve="SWING", direction="OVER", weight_pct=47.0, streak_days=11)
        health = PortfolioHealth(sleeve_band_breaches=[advisory])
        assert health.sleeve_band_breaches[0].sleeve == "SWING"
```

Check whether `tests/test_briefing.py` already has an `OrderProposal` test fixture/helper (search for `OrderProposal(` in the file) — if it does, reuse that helper instead of inventing `some_order_fixture()`; write the actual helper call in place of the placeholder name before running the test. If none exists, construct one inline:

```python
def some_order_fixture():
    from agents.order_builder import OrderProposal
    return OrderProposal(
        ticker="NVDA", action="BUY", quantity=1, order_type="LIMIT", limit_price=100.0,
        estimated_cost_usd=100.0, weight_pct=1.0, conviction=60.0, trigger_type=None, is_trim=False,
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_briefing.py::TestSpeculativeWarningOnActionItem tests/test_briefing.py::TestSleeveBandBreachesOnPortfolioHealth -v`
Expected: FAIL — `TypeError: ActionItem() got an unexpected keyword argument 'speculative_warning'`, then `ImportError: cannot import name 'SleeveBreachAdvisory'`.

- [ ] **Step 3: Implement**

In `core/briefing.py`, update `ActionItem`:

```python
@dataclass
class ActionItem:
    order: OrderProposal
    headline: str  # e.g. "New position", "Trailing stop triggered", "Trim 50%"
    thesis_summary: str | None = None
    bear_case: str | None = None
    # Informational only (core.sleeves.speculative_look_reasons) — set on a
    # new BUY that defaulted to SWING but looks SPECULATIVE by market cap /
    # FCF / earnings. Empty for every other action item.
    speculative_warning: list[str] = field(default_factory=list)
```

Add a new dataclass near `PortfolioHealth`:

```python
@dataclass
class SleeveBreachAdvisory:
    sleeve: str
    direction: str  # 'OVER' | 'UNDER'
    weight_pct: float
    streak_days: int
```

Update `PortfolioHealth`:

```python
@dataclass
class PortfolioHealth:
    sleeve_weights_pct: dict[str, float] = field(default_factory=dict)
    sleeve_targets_pct: dict[str, float] = field(default_factory=dict)
    correlated_cluster_pct: dict[str, float] = field(default_factory=dict)
    cash_pct: float = 0.0
    drawdown_from_peak_pct: float = 0.0
    kill_switch: KillSwitchStatus | None = None
    # Sustained (>breach_margin_pct beyond the band edge, for
    # breach_sustain_days consecutive runs) sleeve breaches — advisory only,
    # never a forced trade. Populated by core/orchestrator.py.
    sleeve_band_breaches: list[SleeveBreachAdvisory] = field(default_factory=list)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_briefing.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: all pass.

```bash
git add core/briefing.py tests/test_briefing.py
git commit -m "$(cat <<'EOF'
Carry sleeve data into the briefing: speculative warnings, breach advisories

ActionItem.speculative_warning surfaces the informational
speculative-look reasons on a new BUY. PortfolioHealth.sleeve_band_breaches
(new SleeveBreachAdvisory dataclass) surfaces sustained sleeve-band
breaches. Both default empty, so every existing caller is unaffected.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `core/orchestrator.py` — wire it all together

**Files:**
- Modify: `core/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: a fully wired nightly run — sleeve weights computed and populated in `PortfolioHealth`, held-position exits gated by `pos.sleeve`, new-BUY sizing routed to `size_new_position` (SWING, with `sleeve_room`) or `size_speculative_position` (SPECULATIVE), sustained-breach `RiskEvent`s + advisories, speculative-look warnings attached.

- [ ] **Step 1: Read the exact current code you're modifying**

Run: `sed -n '1,90p' core/orchestrator.py` (imports), `sed -n '394,545p' core/orchestrator.py` (NAV pass + held-position loop), `sed -n '546,640p' core/orchestrator.py` (new-candidate loop + briefing assembly) to confirm line numbers match what's described below — the file may have shifted slightly from earlier edits in this session; adjust line anchors accordingly, the surrounding code (function names, variable names) is the reliable anchor, not line numbers.

- [ ] **Step 2: Write failing integration tests**

Add to `tests/test_orchestrator.py`, in a new test class (place it near `TestFullNightlyRun`):

```python
class TestSleeveWiring:
    def test_core_position_produces_no_exit_trigger_even_with_bad_conviction(self, session, portfolio, tmp_path):
        # VTI resolves to CORE via config defaults — a conviction floor / thesis
        # decay / trailing stop that would fire on SWING must not fire here.
        portfolio.add_manual_position("VTI", qty=10, avg_cost=400.0, opened_at=dt.datetime(2026, 7, 1), conviction_at_entry=90.0)
        inputs_by_ticker = {
            "VTI": screener_input("VTI", is_held=True, technical=technical(atr_14=1.0)),
        }
        gateway = FakeGateway(inputs=inputs_by_ticker, prices={"VTI": 300.0})  # -25% from cost, conviction about to crater
        script = [FakeResponse(parsed_output=memo(subscore=5.0, thesis_summary="VTI thesis gutted"))]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(as_of=dt.datetime(2026, 9, 1), cash=usd(1_000.0), universe=["VTI"])
        briefing = run_nightly(session=session, portfolio=portfolio, gateway=gateway, llm=llm, config=config, inputs=run_inputs)
        vti_entry = next(b for b in briefing.book if b.ticker == "VTI")
        assert vti_entry.has_exit_trigger is False

    def test_swing_position_still_triggers_conviction_floor(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("NVDA", qty=10, avg_cost=400.0, opened_at=dt.datetime(2026, 7, 1), conviction_at_entry=90.0)
        inputs_by_ticker = {"NVDA": screener_input("NVDA", is_held=True, technical=technical(atr_14=1.0))}
        gateway = FakeGateway(inputs=inputs_by_ticker, prices={"NVDA": 500.0})
        script = [FakeResponse(parsed_output=memo(subscore=5.0, thesis_summary="NVDA thesis gutted"))]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(as_of=dt.datetime(2026, 9, 1), cash=usd(1_000.0), universe=["NVDA"])
        briefing = run_nightly(session=session, portfolio=portfolio, gateway=gateway, llm=llm, config=config, inputs=run_inputs)
        nvda_entry = next(b for b in briefing.book if b.ticker == "NVDA")
        assert nvda_entry.has_exit_trigger is True

    def test_portfolio_health_carries_sleeve_weights(self, session, portfolio, tmp_path):
        portfolio.add_manual_position("VTI", qty=10, avg_cost=400.0, opened_at=dt.datetime(2026, 7, 1))
        inputs_by_ticker = {"VTI": screener_input("VTI", is_held=True, technical=technical(atr_14=1.0))}
        gateway = FakeGateway(inputs=inputs_by_ticker, prices={"VTI": 400.0})
        script = [FakeResponse(parsed_output=memo(subscore=60.0))]
        llm = make_llm(tmp_path, script)
        config = make_config()
        run_inputs = NightlyRunInputs(as_of=dt.datetime(2026, 9, 1), cash=usd(3_000.0), universe=["VTI"])
        briefing = run_nightly(session=session, portfolio=portfolio, gateway=gateway, llm=llm, config=config, inputs=run_inputs)
        assert "CORE" in briefing.portfolio_health.sleeve_weights_pct
        assert briefing.portfolio_health.sleeve_targets_pct["CORE"] == 50
        # VTI 10*$400=$4,000 of $7,000 NAV = ~57.1%
        assert briefing.portfolio_health.sleeve_weights_pct["CORE"] == pytest.approx(57.14, abs=0.1)
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_orchestrator.py::TestSleeveWiring -v`
Expected: FAIL — `test_core_position_produces_no_exit_trigger_even_with_bad_conviction` fails because `evaluate_held_position` isn't called with `sleeve=pos.sleeve` yet, so CORE's protection doesn't apply; `test_portfolio_health_carries_sleeve_weights` fails because `sleeve_weights_pct`/`sleeve_targets_pct` are still empty dicts.

- [ ] **Step 4: Wire the NAV pass to compute sleeve values**

Find the "NAV, sector, cluster pass" loop (search for `sector_value: dict[str, Money] = {}`). Change:

```python
    position_values: list[Money] = []
    sector_value: dict[str, Money] = {}
    cluster_value: dict[str, Money] = {}
    for pos in held_positions:
        price = price_by_ticker.get(pos.ticker)
        if price is None:
            continue
        value = usd(pos.qty * price)
        position_values.append(value)
        sector = gateway.get_sector(pos.ticker)
        cluster = gateway.get_cluster(pos.ticker)
        if sector:
            sector_value[sector] = sector_value.get(sector, usd(0.0)) + value
        if cluster:
            cluster_value[cluster] = cluster_value.get(cluster, usd(0.0)) + value

    nav = compute_nav(position_values, inputs.cash)
    sector_pct = {k: (v / nav) * 100 for k, v in sector_value.items()} if nav.amount else {}
    cluster_pct = {k: (v / nav) * 100 for k, v in cluster_value.items()} if nav.amount else {}
```

to:

```python
    position_values: list[Money] = []
    sector_value: dict[str, Money] = {}
    cluster_value: dict[str, Money] = {}
    sleeve_value: dict[str, Money] = {}
    for pos in held_positions:
        price = price_by_ticker.get(pos.ticker)
        if price is None:
            continue
        value = usd(pos.qty * price)
        position_values.append(value)
        sector = gateway.get_sector(pos.ticker)
        cluster = gateway.get_cluster(pos.ticker)
        if sector:
            sector_value[sector] = sector_value.get(sector, usd(0.0)) + value
        if cluster:
            cluster_value[cluster] = cluster_value.get(cluster, usd(0.0)) + value
        sleeve_value[pos.sleeve] = sleeve_value.get(pos.sleeve, usd(0.0)) + value

    nav = compute_nav(position_values, inputs.cash)
    sector_pct = {k: (v / nav) * 100 for k, v in sector_value.items()} if nav.amount else {}
    cluster_pct = {k: (v / nav) * 100 for k, v in cluster_value.items()} if nav.amount else {}
    sleeve_pct = {k: (v / nav) * 100 for k, v in sleeve_value.items()} if nav.amount else {}
    # HEDGE_CASH's target/band includes uninvested cash, not just IAU's
    # market value — the only sleeve where that's true (config-driven, not
    # a hardcoded ticker check).
    if nav.amount:
        for name, defn in config.sleeves.definitions.items():
            if defn.includes_account_cash:
                sleeve_pct[name] = sleeve_pct.get(name, 0.0) + (inputs.cash / nav) * 100
```

- [ ] **Step 5: Wire the held-position loop to pass sleeve and hard_stop_pct**

Find (from Part 1's fix) the block computing `pos.peak_price_since_activation = update_peak_price(...)` followed by the `evaluate_held_position(...)` call. Change the call:

```python
        if conviction_now is None:
            evaluation = HeldPositionEvaluation(ticker=pos.ticker, triggers=[])
        else:
            evaluation = evaluate_held_position(
                ticker=pos.ticker,
                current_price=current_price,
                avg_cost=pos.avg_cost,
                peak_price=pos.peak_price_since_activation,
                atr_14=atr_14,
                conviction_now=conviction_now,
                conviction_at_entry=pos.conviction_at_entry if has_fresh_conviction else None,
                scaling=config.conviction_scaling,
                config=config.risk,
            conviction_is_fresh=has_fresh_conviction,
            )
```

to (adding the two new keyword arguments; everything else in this block is unchanged):

```python
        if conviction_now is None:
            evaluation = HeldPositionEvaluation(ticker=pos.ticker, triggers=[])
        else:
            sleeve_defn = config.sleeves.definitions.get(pos.sleeve)
            evaluation = evaluate_held_position(
                ticker=pos.ticker,
                current_price=current_price,
                avg_cost=pos.avg_cost,
                peak_price=pos.peak_price_since_activation,
                atr_14=atr_14,
                conviction_now=conviction_now,
                conviction_at_entry=pos.conviction_at_entry if has_fresh_conviction else None,
                scaling=config.conviction_scaling,
                config=config.risk,
                conviction_is_fresh=has_fresh_conviction,
                sleeve=pos.sleeve,
                hard_stop_pct=sleeve_defn.hard_stop_pct if sleeve_defn else None,
            )
```

(Indentation note: the existing code has a pre-existing inconsistent indent on `conviction_is_fresh=has_fresh_conviction,` — four spaces short of the other kwargs. Fix that alignment as part of this edit since you're touching the block anyway.)

- [ ] **Step 6: Persist the sustained-breach streak, once per run**

Add this block right after the `sleeve_pct` computation from Step 4 (still before the held-positions loop, since it doesn't depend on it) — import `SleeveBreachState` from `core.models` and `update_breach_streak`, `SleeveBreachStatus` from `core.sleeves` at the top of the file first:

```python
    sleeve_band_breaches: list[SleeveBreachAdvisory] = []
    for name, defn in config.sleeves.definitions.items():
        weight_pct = sleeve_pct.get(name, 0.0)
        state_row = session.get(SleeveBreachState, name)
        previous = SleeveBreachStatus(direction=state_row.direction if state_row else None, streak_days=state_row.streak_days if state_row else 0)
        updated = update_breach_streak(previous, weight_pct, defn, config.sleeves.breach_margin_pct)
        if state_row is None:
            state_row = SleeveBreachState(sleeve=name, direction=updated.direction, streak_days=updated.streak_days, last_run_id=run_row.id)
            session.add(state_row)
        else:
            state_row.direction = updated.direction
            state_row.streak_days = updated.streak_days
            state_row.last_run_id = run_row.id
        if updated.streak_days >= config.sleeves.breach_sustain_days:
            session.add(RiskEvent(
                run_id=run_row.id, type="REBALANCE_ADVISORY",
                detail_json=json.dumps({"sleeve": name, "direction": updated.direction, "weight_pct": weight_pct, "streak_days": updated.streak_days}),
            ))
            sleeve_band_breaches.append(SleeveBreachAdvisory(sleeve=name, direction=updated.direction, weight_pct=weight_pct, streak_days=updated.streak_days))
    session.flush()
```

Add the necessary imports at the top of `core/orchestrator.py` (find the existing `from core.risk_rules import (...)` and `from core.briefing import (...)` blocks and extend them, plus a new import line for `core.sleeves` and `core.config`):

```python
from core.briefing import (
    ActionItem,
    # ... existing names ...
    SleeveBreachAdvisory,
)
from core.models import (
    # ... existing names ..., add:
    SleeveBreachState,
)
from core.sleeves import resolve_sleeve, sleeve_room, speculative_look_reasons, update_breach_streak, SleeveBreachStatus
```

(Read the actual current import blocks first with `grep -n "^from core" core/orchestrator.py` and merge these names into the existing lists rather than duplicating import statements — keep one import line per module.)

- [ ] **Step 7: Wire the new-candidate loop to route by sleeve and attach warnings**

Find the new-candidate loop (search for `for scored in capped:`). Before the loop, compute how many SPECULATIVE slots are currently open:

```python
    open_speculative_slots = sum(1 for p in held_positions if p.sleeve == "SPECULATIVE")
```

Change the body of the loop from:

```python
    for scored in capped:
        screener_input = screener_inputs.get(scored.ticker)
        if screener_input is None:
            continue
        try:
            current_price = gateway.get_current_price(scored.ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("price fetch failed for candidate ticker=%s error=%s", scored.ticker, exc)
            continue

        sector = gateway.get_sector(scored.ticker)
        cluster = gateway.get_cluster(scored.ticker)
        sizing = size_new_position(
            conviction_score=scored.conviction,
            atr_pct_of_price=screener_input.technical.atr_pct_of_price,
            nav_usd=nav.amount,
            sector=sector,
            cluster=cluster,
            current_sector_pct=running_sector_pct,
            current_cluster_pct=running_cluster_pct,
            cash_available_usd=running_cash.amount,
            scaling=config.conviction_scaling,
            config=config.risk,
        )
        if not sizing.approved:
            session.add(RiskEvent(run_id=run_row.id, type="SIZING_REJECTED", detail_json=json.dumps({"ticker": scored.ticker, "reasons": sizing.reasons})))
            continue

        order = build_buy_order(scored.ticker, scored.conviction, sizing, current_price, config.order_builder)
        if order is None:
            continue
        memo = memo_by_ticker.get(scored.ticker)
        action_items.append(
            ActionItem(
                order=order, headline="New position",
                thesis_summary=getattr(memo, "thesis_summary", None),
                bear_case=getattr(getattr(memo, "bear_case", None), "thesis", None),
            )
        )
```

to:

```python
    for scored in capped:
        screener_input = screener_inputs.get(scored.ticker)
        if screener_input is None:
            continue
        try:
            current_price = gateway.get_current_price(scored.ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("price fetch failed for candidate ticker=%s error=%s", scored.ticker, exc)
            continue

        candidate_sleeve = resolve_sleeve(scored.ticker, config.sleeves)
        sleeve_defn = config.sleeves.definitions.get(candidate_sleeve)
        room = sleeve_room(running_sleeve_pct.get(candidate_sleeve, 0.0), sleeve_defn) if sleeve_defn else None

        sector = gateway.get_sector(scored.ticker)
        cluster = gateway.get_cluster(scored.ticker)

        if candidate_sleeve == "SPECULATIVE":
            sizing = size_speculative_position(
                nav_usd=nav.amount,
                cash_available_usd=running_cash.amount,
                sleeve_room=room if room is not None else 0.0,
                open_speculative_slots=open_speculative_slots,
                sleeve_config=sleeve_defn,
                config=config.risk,
            )
        else:
            sizing = size_new_position(
                conviction_score=scored.conviction,
                atr_pct_of_price=screener_input.technical.atr_pct_of_price,
                nav_usd=nav.amount,
                sector=sector,
                cluster=cluster,
                current_sector_pct=running_sector_pct,
                current_cluster_pct=running_cluster_pct,
                cash_available_usd=running_cash.amount,
                scaling=config.conviction_scaling,
                config=config.risk,
                sleeve_room=room,
            )
        if not sizing.approved:
            session.add(RiskEvent(run_id=run_row.id, type="SIZING_REJECTED", detail_json=json.dumps({"ticker": scored.ticker, "reasons": sizing.reasons})))
            continue

        order = build_buy_order(scored.ticker, scored.conviction, sizing, current_price, config.order_builder)
        if order is None:
            continue

        speculative_warning: list[str] = []
        if candidate_sleeve == "SWING":
            speculative_warning = speculative_look_reasons(
                market_cap_usd=screener_input.market_cap_usd,
                free_cash_flow=screener_input.free_cash_flow,
                trailing_pe=screener_input.trailing_pe,
                config=config.speculative_look,
            )

        memo = memo_by_ticker.get(scored.ticker)
        action_items.append(
            ActionItem(
                order=order, headline="New position",
                thesis_summary=getattr(memo, "thesis_summary", None),
                bear_case=getattr(getattr(memo, "bear_case", None), "thesis", None),
                speculative_warning=speculative_warning,
            )
        )
        if candidate_sleeve == "SPECULATIVE":
            open_speculative_slots += 1
```

Then find the `session.add(Proposal(...))` call immediately after (within the same loop) and add the new column:

```python
        session.add(
            Proposal(
                run_id=run_row.id, ticker=order.ticker, action=order.action, quantity=order.quantity,
                order_type=order.order_type, limit_price=order.limit_price, est_cost=order.estimated_cost_usd,
                conviction=order.conviction, rationale=getattr(memo, "thesis_summary", "") or "",
                risk_checks_json=json.dumps(sizing.reasons), trigger_type=None, status="proposed",
                created_at=inputs.as_of,
                speculative_warning_json=json.dumps(speculative_warning) if speculative_warning else None,
            )
        )
```

Also add `running_sleeve_pct = dict(sleeve_pct)` next to the existing `running_sector_pct = dict(sector_pct)` / `running_cluster_pct = dict(cluster_pct)` initialization, and update it after each approved BUY the same way sector/cluster are updated (find `if sector: running_sector_pct[...] += order.weight_pct` and add alongside it):

```python
        running_sleeve_pct[candidate_sleeve] = running_sleeve_pct.get(candidate_sleeve, 0.0) + order.weight_pct
```

- [ ] **Step 8: Populate `PortfolioHealth.sleeve_weights_pct`/`sleeve_targets_pct`/`sleeve_band_breaches`**

Find the `portfolio_health=PortfolioHealth(...)` construction inside `assemble_briefing(...)` and change it from:

```python
        portfolio_health=PortfolioHealth(
            correlated_cluster_pct=cluster_pct,
            cash_pct=(inputs.cash / nav * 100) if nav.amount else 0.0,
            drawdown_from_peak_pct=nav_status.drawdown_pct,
            kill_switch=kill_status,
        ),
```

to:

```python
        portfolio_health=PortfolioHealth(
            sleeve_weights_pct=sleeve_pct,
            sleeve_targets_pct={name: defn.target_pct for name, defn in config.sleeves.definitions.items()},
            correlated_cluster_pct=cluster_pct,
            cash_pct=(inputs.cash / nav * 100) if nav.amount else 0.0,
            drawdown_from_peak_pct=nav_status.drawdown_pct,
            kill_switch=kill_status,
            sleeve_band_breaches=sleeve_band_breaches,
        ),
```

- [ ] **Step 9: Run the new tests**

Run: `.venv/bin/python -m pytest tests/test_orchestrator.py::TestSleeveWiring -v`
Expected: PASS (3 tests). Debug against actual output if not — this is the densest wiring task in the plan; read the failure carefully rather than guessing.

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -60`
Expected: all pass. Pay particular attention to `tests/test_orchestrator.py::TestFullNightlyRun` and anything in `tests/test_briefing.py`/`tests/test_api_briefing.py` that constructs or asserts on `PortfolioHealth` — those may need `sleeve_weights_pct`/`sleeve_band_breaches` accounted for if they do exact-equality dataclass comparisons rather than field-by-field assertions. Fix any such test by adding the new expected fields, not by loosening the assertion.

- [ ] **Step 11: Commit**

```bash
git add core/orchestrator.py tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
Wire sleeve architecture into the nightly orchestrator

Sleeve weights (HEDGE_CASH includes account cash) feed PortfolioHealth,
held-position exits are gated by pos.sleeve, new-BUY sizing routes to
size_new_position (SWING, sleeve_room-capped) or size_speculative_position
(SPECULATIVE, slot-based), sustained band breaches persist a streak and
emit an advisory RiskEvent, and SWING BUYs get a speculative-look warning
when they look like RKLB/SOFI's cohort.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Startup drift-check wiring

**Files:**
- Modify: `scripts/run_live_briefing.py`
- Modify: `api/server.py`
- Test: `tests/test_api_briefing.py` or a new small test for the script's drift check (see Step 3)

**Interfaces:**
- Consumes: `find_sleeve_drift` from Task 2, `PortfolioService.list_positions()` (existing).

- [ ] **Step 1: Wire `scripts/run_live_briefing.py`**

Find `held_positions = portfolio.list_positions()` (right after the sync block). Add immediately after it:

```python
    held_positions = portfolio.list_positions()
    drift = find_sleeve_drift([(p.ticker, p.sleeve) for p in held_positions], config.sleeves)
    for d in drift:
        logging.getLogger(__name__).warning(
            "sleeve drift: %s stored as %s but config now resolves it to %s",
            d.ticker, d.stored_sleeve, d.resolved_sleeve,
        )
```

Add the import at the top: `from core.sleeves import find_sleeve_drift  # noqa: E402` alongside the other `# noqa: E402` imports in that block.

- [ ] **Step 2: Wire `api/server.py`**

Add imports:

```python
import logging

from core.config import load_config
from core.portfolio import PortfolioService
from core.sleeves import find_sleeve_drift
```

In `create_app`, right after `app.state.data_dir = ...` and before `app.include_router(...)`, add:

```python
    _log_sleeve_drift(engine, config_path)
```

Add a module-level helper function above `create_app`:

```python
def _log_sleeve_drift(engine, config_path: Path) -> None:
    """Startup reconciliation check (user-requested): sleeve is assigned
    once at position-open time and never auto-corrected, so editing
    config.yaml's ticker lists afterward can silently orphan a position's
    stored sleeve. Logs a warning per mismatch; never writes anything."""
    try:
        config = load_config(config_path)
    except Exception as exc:  # noqa: BLE001 - startup check must never block app boot
        logging.getLogger(__name__).warning("sleeve drift check skipped: could not load config: %s", exc)
        return
    session_factory = make_session_factory(engine)
    session = session_factory()
    try:
        positions = PortfolioService(session, config=config.portfolio, sleeves=config.sleeves).list_positions()
        drift = find_sleeve_drift([(p.ticker, p.sleeve) for p in positions], config.sleeves)
        for d in drift:
            logging.getLogger(__name__).warning(
                "sleeve drift: %s stored as %s but config now resolves it to %s",
                d.ticker, d.stored_sleeve, d.resolved_sleeve,
            )
    finally:
        session.close()
```

- [ ] **Step 3: Write a test proving the drift check runs at app startup**

Add to `tests/test_api_briefing.py` (or create `tests/test_api_startup.py` if that file's fixtures don't fit — check its `create_app` usage pattern first):

```python
def test_startup_logs_sleeve_drift(tmp_path, caplog):
    import logging as _logging
    from api.server import create_app
    from core.config import Config
    from core.db import init_db, make_engine, make_session_factory
    from core.portfolio import PortfolioService
    import datetime as dt
    import yaml

    db_path = tmp_path / "t.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(Config().model_dump(mode="json")))

    engine = make_engine(db_path)
    init_db(engine)
    session = make_session_factory(engine)()
    portfolio = PortfolioService(session, config=Config().portfolio, sleeves=Config().sleeves)
    portfolio.add_manual_position("VTI", qty=1, avg_cost=300.0, opened_at=dt.datetime(2026, 1, 1))
    portfolio.reclassify_sleeve(portfolio.get_position("VTI").id, "SWING")  # force a mismatch
    session.commit()
    session.close()

    with caplog.at_level(_logging.WARNING):
        create_app(db_path=db_path, config_path=config_path, data_dir=tmp_path)

    assert any("sleeve drift" in r.message and "VTI" in r.message for r in caplog.records)
```

- [ ] **Step 4: Run to verify it fails, then implement, then verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_briefing.py::test_startup_logs_sleeve_drift -v` (or wherever you placed it)
Expected first: FAIL (no drift logged, since `_log_sleeve_drift` doesn't exist yet — if you implemented Step 1/2 already before writing the test, run this test BEFORE those steps by temporarily commenting out the `_log_sleeve_drift(engine, config_path)` call, confirm the failure, then uncomment and re-run to confirm it passes. Do not skip watching it fail.)

Run: `.venv/bin/python -m pytest tests/test_api_briefing.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: all pass.

```bash
git add scripts/run_live_briefing.py api/server.py tests/test_api_briefing.py
git commit -m "$(cat <<'EOF'
Log sleeve drift at startup, in both the nightly script and the API server

Compares every held position's stored sleeve against what
resolve_sleeve would return today and logs a warning per mismatch.
Never auto-corrects — the user decides.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite one more time**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -30`
Expected: all pass, same or higher count than the 462 baseline from before this plan started (462 + ~50 new tests across Tasks 1–9).

- [ ] **Step 2: Confirm the live database matches what's expected**

Run:
```bash
sqlite3 data/z_money.db ".headers on" ".mode column" "SELECT ticker, sleeve, peak_price_since_activation FROM positions ORDER BY ticker;"
```
Expected: sleeve column matches Task 3's migration (CORE for VTI/VGT, HEDGE_CASH for IAU, SPECULATIVE for RKLB/SOFI, SWING for the rest), and `peak_price_since_activation` still reflects Part 1's reset (NULL for the 13 tickers reset earlier, populated for AMD/NBIS/VGT).

- [ ] **Step 3: Report to the user**

Summarize: tests passing (count), sleeve assignments confirmed in the live DB, and that Part 2 is complete — ready for Part 3 (conviction band recalibration).
