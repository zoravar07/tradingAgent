# Z Money — Build Specification v3

A multi-agent investment research system that runs on a laptop. Every morning it
presents a briefing: what to buy, what to sell, what it's watching, and why. You place
the orders yourself in IBKR.

**What changed from v2:** no IBKR API dependency. The account is IBKR Lite, which does
not permit API access. Positions are imported; orders are prepared, not submitted.
Nothing else about the analytical design changes.

---

## 1. The daily loop

```
Overnight (scheduled)            Morning (you)
─────────────────────            ─────────────
screen universe                  open Z Money
research survivors               read briefing
score conviction                 place orders in IBKR
check every held position        mark filled
generate proposals               done
build briefing
```

Z Money never touches your broker. It reads market data, reads your imported positions,
and writes a briefing. Order placement is manual and always was going to be — the
approval step was in the design from the start. The only loss versus v2 is that you
type the order instead of clicking approve.

---

## 2. Position tracking without an API

Three ways positions get in, in order of preference:

1. **Flex Query CSV import.** IBKR Client Portal → Performance & Reports → Flex
   Queries. Build a positions query, download the CSV, drag it into Z Money. Works on
   Lite. Do this weekly, or after any trading day.
2. **Mark-as-filled.** When Z Money proposes a trade and you place it, click "Filled" and
   enter the actual fill price. Z Money updates its own book immediately. This keeps
   positions accurate between CSV imports.
3. **Manual entry.** Add or edit a position by hand. Fallback, and for the initial load.

Z Money maintains its own `positions` table as the source of truth, reconciled against
the CSV whenever you import one. A **drift warning** appears on the dashboard if the
last import is more than N days old, so stale position data never silently corrupts
sizing and stop calculations.

---

## 3. The briefing — the primary screen

This is what you see when you open the laptop. Everything else is secondary.

### Section 1 — Actions today
Each item is a ready-to-place order:

```
BUY   ANET    3 shares   LIMIT $142.50   ~$427   (3.5% of NAV)
      Conviction 74 · New position · Diversifies away from AI-semis cluster
      Why: [2-3 line thesis summary]
      Bear case: -28% if [specific risk]
      [Copy details] [Mark filled] [Dismiss]

SELL  NBIS    2 shares   LIMIT $218.00   ~$436   (trim 50%)
      Trailing stop triggered · Peak $241 → now $222 (-7.9%, threshold -7.2%)
      Conviction 68 at entry → 61 now
      [Copy details] [Mark filled] [Dismiss]
```

"Copy details" puts ticker, action, quantity, order type and limit price on the
clipboard in a format that's fast to transfer into IBKR's order ticket.

### Section 2 — Watching
Names approaching a trigger but not there yet. No action needed; this exists so nothing
surprises you tomorrow.

```
CRDO   3.1% from trailing stop     Conviction 58 (was 71 at entry) — decaying
MP     earnings in 2 days          position flagged, no new adds until after
VRT    4.2% below next profit band
```

### Section 3 — Overnight changes
Anything material that happened to what you hold: earnings, guidance, downgrades,
sector news, unusual moves.

### Section 4 — Your book
Every position: value, weight, unrealized P&L, **conviction now vs. at entry**,
distance to trailing stop, next profit band. Sorted by whatever needs attention most.

### Section 5 — Portfolio health
Sleeve weights vs. targets. Correlated-cluster exposure vs. cap. Cash. Drawdown from
peak. Kill-switch state.

---

## 4. Architecture

```
zopro/
  main.py
  config.yaml
  .env                       # ANTHROPIC_API_KEY, FMP_API_KEY

  core/
    config.py                # load, validate, hot-reload, version snapshots
    orchestrator.py          # nightly run, sequencing, logging
    portfolio.py             # position book, CSV import, reconciliation, drift check
    market_data.py           # FMP client + aggressive caching
    scoring.py               # DETERMINISTIC conviction math
    risk_rules.py            # DETERMINISTIC gates, sizing, stops, bands
    briefing.py              # assembles the morning briefing
    llm.py                   # Anthropic client, schema enforcement, token accounting

  sources/                   # plugin layer
    base.py                  # FactorSource ABC
    fmp.py
    prices.py                # FMP historicals → ATR, MAs, relative strength
    discord_signals.py       # optional, weight 0 by default

  agents/
    screener.py              # Stage 1 quant, Stage 2 Haiku triage
    research.py              # Sonnet memos
    risk_manager.py          # deterministic, the only thing that can veto
    order_builder.py         # produces fully-specified orders (never submits)

  api/server.py + routes/
  ui/  Briefing · Positions · Research · History · Settings
  tests/                     # scoring + risk_rules first
  data/z_money.db
```

Stack: Python 3.11+, FastAPI, SQLAlchemy + Alembic + SQLite, pandas, Anthropic SDK,
React + Vite + TypeScript + Tailwind. Optional Tauri wrap for a real app icon.

**No ib_insync. No broker connection of any kind.**

---

## 5. Pipeline

```
Universe = S&P500 + watchlist + ALL current holdings
  │
  ├─ Screener Stage 1   pure quant, free            ~500 → ~40
  ├─ Screener Stage 2   Haiku triage, cheap          ~40 → ~15
  ├─ Research           Sonnet memo per name         15 memos
  ├─ Scoring            deterministic roll-up
  ├─ Risk Manager       gates, sizing, stops, bands
  ├─ Order Builder      fully-specified orders
  └─ Briefing           assembled for the morning
```

Held positions always enter the pipeline regardless of screener output. This is the
mechanism that catches a decaying thesis on something you already own.

### 5.1 Screener

**Stage 1 — quant, no LLM, no cost**
Liquidity (min ADV, min market cap) · price vs 50/200 DMA · relative strength vs sector
ETF and SPY · ATR percentile · valuation bands (flag, don't auto-exclude) · earnings
proximity flag · fundamental floor (positive FCF or revenue growth above threshold).

**Stage 2 — Haiku triage**
One short call per survivor: any material development in the last N days — contracts,
guidance, regulatory, management change, sector shock? Returns a one-line verdict and a
material/not-material flag. Roughly 1/15th the cost of full research.

### 5.2 Research Agent — Sonnet, one call per candidate

Produces an investment memo. Schema-enforced JSON; malformed output is rejected and
retried.

| Sub-score | What it evaluates |
|---|---|
| `business_quality` | ROIC and its **trend**. Gross margin durability — pricing power or commodity? Reinvestment runway. |
| `financial_health` | Growth trend, FCF conversion, balance sheet, debt maturities |
| `whats_priced_in` | **Reverse-DCF: what growth does the current price require?** Plausible or heroic? A great company at a price assuming greatness is not a good trade. |
| `variant_perception` | State the consensus view explicitly, then where this thesis differs and why it might be right. Consensus thesis = exposure, not edge. |
| `earnings_quality` | Beat/miss magnitude, guidance direction, post-earnings drift, accruals vs cash earnings |
| `catalyst_path` | What specifically converts mispriced → correctly priced, and when. Dated where possible. A thesis without a catalyst is a hope with a ticker. |
| `downside_asymmetry` | **Bear case magnitude, not probability.** What breaks, and how much is lost. |
| `ownership_flow` | 13F trend across multiple quarters (not single-quarter noise), Form 4 insider activity weighted by seniority and buy vs option-exercise |
| `analyst_signals` | Rating changes, target revisions, estimate revision *direction* |
| `news_sentiment` | Volume, tone, material events, sector news hitting the name indirectly |
| `technical_momentum` | Price vs MAs, relative strength, volatility regime |
| `portfolio_fit` | **Correlation to what you already own.** Penalty applied after roll-up. |
| `discord_signal` | Optional. Weight 0 until earned — see §8.3. |

Output includes `consensus_view`, `variant_view`, `bear_case` with an estimated
downside %, dated catalysts, key risks, and a thesis summary.

The LLM does not output position sizes, stop levels, buy/sell decisions, or the final
conviction score. It analyses. It does not decide.

### 5.3 Risk Manager — deterministic, no LLM

Gates in order: kill switches (daily loss, drawdown) → daily proposal cap → position
sizing from conviction and volatility, hard-capped → concentration limits → correlated
cluster cap → cash available.

For held positions additionally: trailing stop breach · profit band crossed · thesis
decay since entry. Any of these generates a SELL or TRIM.

Conviction-scaled, continuously interpolated:
```
activation_threshold_pct:    score 0 → 8%     score 100 → 35%
trailing_stop_atr_multiple:  score 0 → 1.5x   score 100 → 4.5x
profit_taking_start_pct:     score 0 → 15%    score 100 → 60%
```

### 5.4 Order Builder

Takes an approved-by-risk proposal and produces a complete order: action, quantity
(whole shares — no fractional, since you're placing manually), order type, limit price
(from recent price action and spread), and estimated total cost. Formatted for fast
manual entry.

Never submits. There is no submit function in this codebase.

---

## 6. Database

```
runs               id, started_at, finished_at, status, config_snapshot_json, error
positions          id, ticker, qty, avg_cost, opened_at, source, last_verified_at,
                   conviction_at_entry, peak_price_since_activation
position_imports   id, imported_at, filename, rows, reconciliation_json
candidates         id, run_id, ticker, stage1_json, stage1_passed,
                   stage2_verdict, stage2_material, stage2_passed
research_outputs   id, run_id, ticker, subscores_json, reasoning_json, consensus_view,
                   variant_view, bear_case_json, catalysts_json, risks_json,
                   thesis_summary, model, input_tokens, output_tokens
conviction         id, run_id, ticker, score, weights_snapshot_json, derivation_json
proposals          id, run_id, ticker, action, quantity, order_type, limit_price,
                   est_cost, conviction, rationale, risk_checks_json, trigger_type,
                   status, created_at, filled_at, fill_price
watchlist_items    id, run_id, ticker, reason, distance_to_trigger
risk_events        id, run_id, type, detail_json
config_versions    id, version, yaml_text, created_at, note
```

`peak_price_since_activation` must be updated every run and persisted — it's what makes
trailing stops work. Never recompute it from scratch.

`config_snapshot_json` on every run is what makes tuning meaningful later.

---

## 7. UI

**Briefing** (default screen, §3) · **Positions** · **Research** (memo archive per
ticker over time — watch a thesis strengthen or decay) · **History** (every run,
proposal, and outcome; filterable) · **Settings** (edit config with validation).

Design: dark, dense, data-first. Read `/mnt/skills/public/frontend-design/SKILL.md` and
the impeccable-design-rules skill before building. Avoid templated dashboard look.

---

## 8. Built for change

### 8.1 Config is data
Every tunable lives in `config.yaml`; nothing tunable in `.py` files. The Settings page
validates against a Pydantic schema, writes back, and snapshots the previous version.
The orchestrator re-reads config each run — changes apply next cycle, no restart.

### 8.2 Sources are plugins
```python
class FactorSource(ABC):
    name: str
    @abstractmethod
    def fetch(self, ticker: str, ctx: RunContext) -> FactorData: ...
```
Add a source = one new file + one config line. No changes to research, scoring, or risk.

### 8.3 Factor weights are data
Scoring iterates the weights dict; it never hardcodes factor names. Weights
auto-normalise to 1.0 regardless of what's enabled.

`discord_signal` ships at weight **0.0** deliberately. Log the mentions, score them,
contribute nothing — then after a few weeks compare whether Discord-flagged names
actually outperformed the ones Z Money found independently. Raise the weight with
evidence, or leave it at zero. Memory of past picks is unreliable: the ones that ran
are memorable, the ones that didn't aren't.

### 8.4 Deterministic core is tested
`scoring.py` and `risk_rules.py` are pure functions, no I/O. Write the tests first.
A bug here is the one that costs real money.

---

## 9. config.yaml

```yaml
version: 1

portfolio:
  import_reminder_days: 7        # warn if positions haven't been verified recently
  allow_fractional: false        # you place orders manually — whole shares only

schedule:
  nightly_run: "0 22 * * 0-4"    # after US close, briefing ready by morning

universe:
  include_holdings_always: true
  screener_universe: SP500
  watchlist: [AMD, NVDA, MRVL, CRDO, NBIS, VRT, CLS, CEG, MP, PLTR, RKLB, SOFI, MSFT]

screener:
  stage1:
    min_avg_daily_volume_usd: 20000000
    min_market_cap_usd: 2000000000
    max_survivors: 40
  stage2:
    model: claude-haiku-4-5
    lookback_days: 7
    max_survivors: 15

research:
  model: claude-sonnet-4-6
  max_candidates_per_run: 15

sleeves:                         # % of NAV
  core_longterm: 35              # VTI, VGT, IAU — held, not actively traded
  thematic: 45
  tactical: 15
  cash_buffer: 5

risk:
  max_position_pct: 12
  max_sector_pct: 40
  max_correlated_cluster_pct: 50    # see note below
  max_daily_proposals: 5
  max_daily_loss_pct: 3
  max_drawdown_pct: 12
  min_order_value_usd: 150          # avoid orders where costs dominate

conviction_weights:                 # auto-normalised; add or remove freely
  business_quality: 0.15
  financial_health: 0.10
  whats_priced_in: 0.15
  variant_perception: 0.10
  earnings_quality: 0.10
  catalyst_path: 0.08
  downside_asymmetry: 0.10
  ownership_flow: 0.07
  analyst_signals: 0.05
  news_sentiment: 0.03
  technical_momentum: 0.07
  portfolio_fit: 0.00               # penalty-only, applied after roll-up
  discord_signal: 0.00              # earn the weight with data

conviction_scaling:
  activation_threshold_pct:   { at_0: 8,   at_100: 35 }
  trailing_stop_atr_multiple: { at_0: 1.5, at_100: 4.5 }
  profit_taking_start_pct:    { at_0: 15,  at_100: 60 }

sources:
  fmp:             { enabled: true }
  prices:          { enabled: true }
  discord_signals: { enabled: false, channels: [], lookback_hours: 48 }

options:
  enabled: false                    # only after the equity loop is proven

budget:
  monthly_api_cap_usd: 40           # halts LLM calls if exceeded
```

**On `max_correlated_cluster_pct: 50`** — your AI/semis cluster (AMD, NVDA, MRVL, CRDO,
NBIS, VRT, CLS, CEG, MP, PLTR) sits near 46% of NAV. At a 50% cap Z Money will mostly
decline to add more of that theme and will favour diversifying names. That is
deliberate. Raise it consciously if you disagree, not by accident.

**On `min_order_value_usd: 150`** — you're on IBKR Lite, so US stock and ETF trades are
commission-free. This threshold exists to avoid trivially small positions cluttering
the book, not to manage commissions.

---

## 10. Build order

1. Skeleton — config loader with validation and versioning, DB models, migrations
2. Portfolio module — CSV import, manual entry, mark-filled, reconciliation, drift check
3. FMP source — fundamentals, earnings, prices, analysts, 13F, insider. Cache hard;
   free tier is 250 calls/day
4. Screener Stage 1 — pure quant. Eyeball output against names you know
5. Scoring + risk rules **+ tests, written first**. Safety-critical
6. Screener Stage 2 — Haiku triage. First LLM integration, cheap to get wrong
7. Research Agent — Sonnet, schema-enforced, token accounting
8. Briefing assembler
9. Orchestrator — wire, schedule, log everything
10. UI — Briefing first, then Positions, Research, History, Settings
11. **Run it for weeks without acting on it.** Tune via Settings. Compare its picks to
    what you'd have done. Then decide how much to trust it.

---

## 11. Cost

| Item | Monthly |
|---|---|
| Anthropic API — Haiku triage + ~15 Sonnet memos daily | $20–35 |
| FMP | $0 free tier; $30–50 if you later need real-time or 13F |
| IBKR | $0 — Lite, commission-free US stocks and ETFs |
| **Total** | **$20–85** |

`budget.monthly_api_cap_usd` hard-stops LLM calls if exceeded.

---

## 12. What this cannot do

Keep this visible in the UI so it never implies otherwise.

- It cannot predict tops or bottoms. Trailing stops exist *because* timing isn't
  predictable.
- It cannot guarantee its proposals beat an index fund. Most active strategies don't,
  over time, after costs.
- A high conviction score summarises available evidence. It is not a probability of
  profit.
- Good-looking results over a few weeks are weak evidence: small sample, one regime.
- It does not learn on its own. What improves is the config — tuned by you, informed by
  logged outcomes. That's real, but it's your learning encoded, not the system's.
- Positions are only as accurate as your last import. Stale data produces wrong sizing
  and wrong stops. The drift warning exists for a reason.

The genuine value: it watches every position every day, applies exit rules without
emotion, and surfaces decaying theses before you'd notice. That's the NBIS problem.
That's worth building.
