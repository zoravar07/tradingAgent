# ZMONEY-CONTEXT.md

**Purpose:** Ground-truth context for an agent answering questions about the Z Money project.
**Last updated:** 10 September 2026

> **Provenance.** Architecture, strategy, and status below come from design specs and
> build-session history. Section 5a and everything it corrects come from
> `docs/side-effect-inventory.md`, a source-verified inventory of all 176 public
> functions. Items still marked `[SPEC — unverified]` have not been checked against code.
> §8 lists what is genuinely unknown — an agent should say it doesn't know rather than
> reconstruct those.

---

## 1. What Z Money is

A personal, single-user investment research system running on the owner's laptop. It
ingests market data, produces structured research on a set of stocks, scores each name for
conviction, applies deterministic risk rules, and outputs fully-specified order tickets
that a human then places by hand in Interactive Brokers.

Two purposes at once:
1. A real tool managing a real, concentrated personal equity portfolio (~16 positions).
2. A quantitative research artifact intended for a CV.

Originally named **Zopro**, renamed to **Z Money** mid-build. There is a **separate,
unrelated project also called Zopro** (an AI orchestrator / second-brain using Pipecat,
CrewAI, AnythingLLM, Firecrawl, Browser-Use); Z Money is eventually meant to run as a
sub-agent inside it. **Do not conflate them** — disambiguate before answering any question
that says "Zopro."

**Location:** `~/zmoney/`

### Stack
- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, SQLite, pandas, Anthropic SDK
- **Frontend:** React + Vite + TypeScript + Tailwind
- **LLMs:** Claude Haiku (screener triage), Claude Sonnet (research memos)
- **No broker SDK of any kind.** Verified — see §5a.

### Frontend navigation
`Briefing · Watchlist · Positions · Orders · Insights · Performance · Journal · Settings`

**Journal** exists for the learning goal: the user records their own read on a proposal
*before* the outcome is known, so their judgment can be scored separately from the system's.

---

## 2. What "semi-automated" means in practice

The most misunderstood thing about the project. Be precise.

**Automated:** universe construction, screening, data fetching, research memo generation,
conviction scoring, risk-rule evaluation, order ticket construction, briefing assembly. A
full run is one command and needs no human input while it executes.

**Not automated:** anything that moves money.

The boundary is structural, not policy:

- The Order Builder writes rows to `proposals` with `status="proposed"`.
- **No module imports a broker SDK or holds broker credentials.** There is no code path
  from a pipeline run to an order. Confirmed by exhaustive source search (§5a).
- Positions enter via **IBKR Flex Query CSV import** or manual entry.
- Orders leave via **the human typing them into IBKR**.
- The only broker-adjacent code paths are the Flex Query import and `mark_filled`, by
  which the user tells the app about a fill they placed by hand.

This is **Phase 1 / shadow mode**, the current and only implemented phase.

**Phase 2 (designed, not built):** a separate module invoked only by
`POST /proposals/{id}/approve` would submit, re-running the full risk gate immediately
before submission in case conditions moved. None of it exists. Phase 2 is enabled by a
manual `config.yaml` edit, never by anything the system decides.

**Phase 1 → 2 exit criteria:** review 3–4 weeks of shadow proposals and answer — what was
the hit rate, average gain on winners vs. loss on losers, and would these trades have beaten
just holding what was already owned. If unclear or unfavourable, stay in shadow. Shadow mode
is allowed to say no.

Non-negotiable design principles: human-in-the-loop always; deterministic risk layer with
LLM confined to research synthesis; shadow-mode-first before any live reliance on a signal.

---

## 3. Trading strategy

### 3.1 What it trades
US-listed common stocks and ETFs, long-only, cash account. The live book is heavily
concentrated in AI/semiconductors (AMD, NVDA, MRVL, CRDO, NBIS, VRT, CLS, CEG, PLTR), with
broad ETFs (VTI, VGT), gold (IAU), and speculative names (RKLB, SOFI, MP). ~16 positions,
near-zero cash.

**No options are traded.** Options fields exist in the order model (`legs_json`) but no
options strategy is implemented. See §7.

Account **base currency is SGD while all positions are USD-denominated.** This previously
caused a NAV inflation bug; all financial figures are now explicitly currency-tagged.

### 3.2 Strategy paradigm
**Not** a discrete-setup strategy. There is no "if price > yesterday's high AND close >
200 SMA then buy." It is a **continuous conviction-scoring** strategy: every candidate gets
a 0–100 score, and position sizing and exit parameters scale with it.

Known cost of this choice: continuous composites are much harder to validate than binary
triggers. Discrete triggers give clean hit rate and expectancy; a continuous score needs IC
and decile-spread analysis. That validation does not exist yet (§7).

### 3.3 Universe

```
Universe = broad US equity universe + watchlist + ALL current holdings
```

Broad universe is **1,803 US common stocks** from the NASDAQ directory, priced via yfinance.
This was a fix: the S&P 500 constituent list came from FMP and was 402-paywalled, so the
screener silently fell back to the user's own holdings — making it a position monitor, not an
opportunity finder. The expansion runs in ~16 minutes with zero failures.

**Held positions always enter the pipeline regardless of screener output.** This is what
catches a decaying thesis on something already owned.

### 3.4 Entry logic

**Stage 1 — deterministic quant filter (no LLM, no cost).** `[SPEC — unverified]`
liquidity (min ADV, min market cap) · price vs. 50/200 DMA · relative strength vs. sector
ETF and SPY · ATR percentile · valuation bands (flag, don't auto-exclude) · earnings
proximity flag · fundamental floor (positive FCF or revenue growth above threshold).

**Stage 2 — Haiku triage.** Cheap LLM prioritisation pass over Stage 1 survivors. Target
~15 names. Config key `max_candidates_per_run` = 15.

**Research — Sonnet memo per surviving name.** Written to `research_outputs`: sub-scores,
reasoning, consensus view, variant view, bear case, catalysts, risks, thesis summary, token
accounting.

**Scoring — `core/scoring.py`, verified pure.** Rolls memo sub-scores into a 0–100
conviction score using a configurable YAML weight dictionary that auto-normalizes.
- **13 sub-score categories.** Known: business quality, what's-priced-in (reverse-DCF),
  variant perception vs. consensus, downside asymmetry, catalyst path, portfolio fit.
  **The other seven are unrecorded — see §8.**
- **Null handling:** an unavailable factor has its weight renormalized out. Missing data is
  *excluded*, never imputed to a neutral 50 — imputing to neutral compresses dispersion and
  destroys signal.
- Weights are data, not code. Scoring iterates the dict and never hardcodes factor names.
- `discord_signal` ships at weight 0.0 deliberately: log and score the mentions, let them
  contribute nothing until there's evidence they add value.

### 3.5 Exit logic

Three independent triggers, all deterministic:

**1. Trailing stop.** Fires when price pulls back more than `atr_multiple × ATR` from the
post-activation peak. The peak is persisted in
`positions_snapshot.peak_price_since_activation`, updated every run, **never recomputed from
scratch.** That persistence is what makes the trailing stop work.

**2. Profit-taking bands.** Crossing a milestone → TRIM proposal.

**3. Thesis decay / conviction floor.** Conviction dropped materially since entry
(`conviction_at_entry` vs. current) → exit **regardless of unrealized P&L.** A profitable
position can be sold if the reason for owning it is gone.

**Conviction-scaled parameters — linear interpolation, not discrete tiers:**

```
activation_threshold_pct:    score 0 → 8%     score 100 → 35%
trailing_stop_atr_multiple:  score 0 → 1.5x   score 100 → 4.5x
profit_taking_start_pct:     score 0 → 15%    score 100 → 60%
```

High conviction gets more room and a wider stop; low conviction gets cut fast. The reason
this doesn't go further (e.g. per-ticker LLM-chosen numbers) is that the Risk Manager must
stay deterministic and auditable — letting the LLM emit arbitrary stop parameters would
reintroduce freeform judgment into the safety rail.

Motivating real example: **NBIS** ran up substantially and gave it all back with no exit
trigger. The trailing stop and conviction floor were designed to prevent a repeat.

### 3.6 Risk Manager — the only component that can say no
Fully deterministic, no LLM, cannot be overruled. Hard gates in order:

1. **Kill switches** — daily loss limit? drawdown limit? → halt, generate nothing
2. **Daily proposal cap** reached?
3. **Position sizing** — from conviction + volatility, hard-capped by `max_position_pct`
4. **Concentration** — single-name, sector, sleeve limits
5. **Correlated-cluster limit** — the AI/semis cluster cap
6. **Buying power** available?

For existing positions, additionally:

7. **Trailing stop** breached?
8. **Profit-taking band** crossed?
9. **Thesis decay**?

Any of 7/8/9 → SELL or TRIM proposal.

Also a **data-integrity gate** that halts the pipeline on stale marks rather than
propagating an invalid NAV into downstream sizing and exposure math.

### 3.7 Order Builder
Builds a fully-specified order object — type, limit price, quantity, TIF, and for options
the exact legs — and writes it to `proposals` with `status="proposed"`. Never submits.
`order_builder.py` line 9 carries the spec quote: "There is no submit function in this
codebase."

### 3.8 Recurring live output
Across runs the consistent proposals have been **AMD trim, RKLB exit, MP exit.**

---

## 4. Data sources — what handles what, and where

### yfinance — prices, historicals, universe
Universe construction (1,803 names via NASDAQ directory), price data, historical bars, ATR,
moving averages, relative strength inputs for Stage 1. Free, no API key. The workhorse for
the quant stage.

### FMP — fundamentals
Fundamentals, earnings, analyst data, 13F filings. Wired in at `core/market_data.py` (client
+ aggressive caching) and `sources/fmp.py`.

- **The paywall is a live constraint.** S&P 500 constituents returns 402 on the current plan.
  Quote coverage was also 402-gated, at one point leaving 11 of 16 held positions unpriced.
  The universe was moved off FMP because of this.
- **FMP anchors fundamentals on period-end, not filing date**, leaking ~6 weeks of future
  information into any historical analysis. Unfixed. Critical for the validation harness.

### Anthropic API — research and triage
Stage 2 triage (Haiku), research memos (Sonnet), news digests via the `web_search` tool with
citation requirements. Client in `core/llm.py`. Exact spend surface documented in §5a.

### IBKR — **not integrated**
The most common wrong assumption about this project. Be explicit.

- The account is **IBKR Lite**, which does not provide TWS API access.
- **There is no IBKR client in the codebase.** Verified by exhaustive search (§5a).
- Positions enter by **IBKR Flex Query CSV import** or manual entry (`core/portfolio.py`).
- Orders leave by **the human typing them into IBKR**.
- An **IBKR MCP connector** exists and has been used *in chat sessions* to pull account
  summary and positions. It is **not wired into Z Money.** Future integration is backlog,
  untested. Note: when used, `net liquidation` returns in **SGD** while position values
  return in **USD**.

---

## 5. Architecture and data model

```
core/
  config.py          # load, validate, hot-reload, version snapshots
  orchestrator.py    # run sequencing, logging; the only place proposals are inserted
  portfolio.py       # position book, Flex Query CSV import, reconciliation, drift check
  market_data.py     # FMP client + aggressive caching
  scoring.py         # DETERMINISTIC conviction math — verified pure
  risk_rules.py      # DETERMINISTIC gates, sizing, stops, bands — verified pure
  briefing.py        # assembles the morning briefing
  llm.py             # LLMClient: Anthropic calls, schema enforcement, token accounting
  money.py / nav.py  # currency-tagged financial primitives, NAV math

sources/             # plugin layer
  base.py            # FactorSource ABC: fetch(self, ticker: str, ctx: RunContext) -> FactorData
  fmp.py
  prices.py
  discord_signals.py # optional, weight 0 by default

agents/
  screener.py        # Stage 1 quant, Stage 2 Haiku triage
  research.py        # Sonnet memos
  risk_manager.py    # deterministic, the only thing that can veto
  order_builder.py   # fully-specified orders, never submits

api/server.py + routes/
scripts/run_live_briefing.py   # the only entry point that can spend Anthropic credits
ui/
tests/
```

Adding a data source = one file in `sources/` plus a config entry. No changes to the
Research Agent, scoring math, or risk rules. Adding a factor = a key in `conviction_weights`
plus a source module.

Every tunable lives in `config.yaml`; nothing tunable lives in a `.py` file. Settings page
reads it, validates against a Pydantic schema, writes it back, snapshots the old version to
`config_versions`. The orchestrator re-reads config at the start of every run.
`config_snapshot_json` on each run is what makes tuning meaningful — six weeks in you need to
know which settings produced which proposals.

### Database tables

```
runs               id, started_at, finished_at, phase, status, config_version,
                   config_snapshot_json, error
candidates         id, run_id, ticker, stage1_scores_json, stage1_passed,
                   stage2_verdict, stage2_material, stage2_passed
research_outputs   id, run_id, ticker, subscores_json, reasoning_json,
                   consensus_view, variant_view, bear_case_json, catalysts_json,
                   risks_json, thesis_summary, model, input_tokens, output_tokens
conviction         id, run_id, ticker, score, weights_snapshot_json, derivation_json
proposals          id, run_id, ticker, action, quantity, order_type, limit_price,
                   legs_json, conviction_score, rationale, risk_checks_json,
                   status, created_at, decided_at, decided_by,
                   filled_at, fill_price          # ← never written, always NULL
positions_snapshot id, run_id, ticker, qty, avg_cost, mkt_price, mkt_value,
                   unrealized_pnl, peak_price_since_activation, conviction_at_entry
risk_events        id, run_id, type, detail_json
source_data        id, run_id, ticker, source_name, payload_json, fetched_at
config_versions    id, version, yaml_text, created_at, note
```

---

## 5a. Side-effect inventory (source-verified, 10 Sep 2026)

Source: `docs/side-effect-inventory.md`. **176 public functions and methods across 32
non-test Python modules.** Each classified by the **strongest effect reachable through what
it calls**, not by its own body.

| Class | Meaning | Count |
|---|---|---|
| A | Pure — no I/O, deterministic | 90 |
| B | Reads external (network / filesystem read) | 15 |
| C | Reads DB (SELECT only) | 14 |
| D | Writes DB | 14 |
| E | Writes filesystem | 43 |

### Broker submission: confirmed absent
Every non-venv Python file, tests included, was searched for `ib_insync`, `ibapi`, `ibkr`,
`placeOrder`, `place_order`, `submit_order`, `.submit(`, `alpaca`, `tradier`, `schwab`,
`iserver`, and the bare word `submit`. **Zero code hits.** All matches are prose: docstrings
in `money`, `nav`, and `portfolio` describing the Flex Query CSV import, and `order_builder`
line 9 quoting the spec.

**This is the verified basis for the Phase 1 claim in §2 — no longer an assertion from
design intent.**

### Deterministic core: confirmed pure
All 16 public functions in `core/scoring.py` and `core/risk_rules.py` are class A. No
violations. `scoring` imports only `dataclasses`; `risk_rules` imports `dataclasses`,
`typing`, and the Pydantic config models. Neither touches clock, randomness, files, DB, or
network. No function mutates an input.

Two type-level notes that don't affect purity:
- `evaluate_held_position` emits a `CONVICTION_FLOOR` trigger **absent from the
  `ExitTriggerType` Literal**
- `ConvictionResult.derivation` returns its contributions dict **by reference**

### Anthropic spend surface
Exactly two functions make the call: **`LLMClient.call_structured`** and
**`LLMClient.call_text`**.

Five functions reach them: `run_stage2_batch`, `run_research`, `run_research_batch`,
`run_news_digest`, and the private `_preflight` probe.

All five are reachable **only** from `scripts/run_live_briefing.py::main`.
**No API route constructs an Anthropic client** — the web UI cannot spend money.

The `_preflight` probe **bypasses the spend tracker**, so its ~half-cent per run never lands
in the spend file. Recorded spend is therefore systematically understated.

### Proposals writers
Two insert sites, both in the orchestrator pipeline: held-position exits and new-candidate
buys. Both set `status="proposed"`.

**Nothing anywhere updates or deletes a proposal, or writes `filled_at` or `fill_price`.**
Those columns are permanently NULL despite the Orders screen rendering them.

---

## 6. Build status

### Working
- Four-agent pipeline end to end
- `scoring.py` and `risk_rules.py` — verified pure and unit-testable
- Order Builder producing fully-specified proposals with no submission path
- FastAPI backend + React UI across all eight screens
- Flex Query CSV / manual position import
- Universe expansion to 1,803 names (16 min, zero failures)
- Config versioning with per-run snapshots
- Token/cost accounting per research call
- Pre-flight credit balance probe (`_preflight`)
- **Seven live pipeline runs.** Run 5 (~$0.45) produced full conviction scores on all 16
  holdings and is the reference "good run."

### Fixed during the build
- NAV currency mixing (SGD base vs. USD positions) → all figures currency-tagged
- FMP 402 gating leaving 11/16 positions unpriced
- Field-name bugs making P/E and volume silently `None` every run
- Overnight-changes briefing hallucinating news from model memory → grounded web search with
  citation requirements
- Screener universe silently falling back to the user's own holdings

### Absent by design
- Broker submission — no SDK, no credentials, no code path (verified)
- `POST /proposals/{id}/approve` submission module — Phase 2
- `sources/discord_signals.py` — present, weight 0
- Options handling — `legs_json` exists, no strategy implemented

### Broken / open
Run 7 cost **$5** and produced **zero conviction scores** (credits exhausted mid-run). Five
fixes were specified:

1. **Fabricated fallback conviction of 50.** With no memos the pipeline used a hardcoded 50,
   and that placeholder fired real trailing-stop exits on **CRDO and IAU**. Specified: a
   failed memo yields no score and no proposal. **Status unverified — the most dangerous
   known bug.**
2. **`max_candidates_per_run` not binding** — config says 15, 31 reached research. Unverified.
3. **No pre-flight credit balance check.** ✅ **Landed** — `_preflight` exists.
4. **Watching list uncapped** — reached 82 names. Unverified.
5. **Stage 2 grounded search too expensive** — $2.60 to filter 56→31. Specified: drop web
   search from Stage 2, digest only names that get a memo, `web_search_max_uses` = 1, cache
   digests 48h, weekly refresh for holdings. Unverified.

Additional defects surfaced by the inventory:
- **`write_raw` truncates `config.yaml` non-atomically.** A crash mid-write leaves a
  truncated config with no backup. `config.yaml` is the single source of every tunable.
- **The cache stores a `fetch_fn` returning `None` but always reads it back as a miss.** Any
  factor legitimately returning "no data" is re-fetched every run forever.
- **No proposal→outcome loop.** See §7.

**Cost target: under $0.75/run** (~$15/month daily). The run-7 lesson: the expensive part
isn't the intelligence, it's the searching. Memos are ~$0.03 each; per-name daily web search
is 10x the analysis cost.

### Planned (not started)
- **WS-1 / Module A — signal validation harness (highest priority).** IC, decile spread, hit
  rate, with point-in-time discipline, survivorship and look-ahead controls. Start with one
  conviction component. Filed-date anchoring for FMP.
- **WS-2** — null baseline via alpha bench in an isolated venv (HKUDS/Vibe-Trading method).
- **WS-4** — TradingView MCP as a chart-perception layer, encoded as a discrete
  technical-structure sub-score inside the existing 13.
- **WS-5** — hash-chained audit ledger for idea provenance.
- **WS-6** — make the paper/live boundary structural rather than conventional.
- **WS-7** — budget-tiered LLM degradation when costs spike.
- **Module B** — narrowly scoped *index-level* volatility premium sleeve. **Conditional on
  Module A existing and producing results.**
- **Module C** — deterministic Risk Manager gate blocking covered-call writing against
  high-conviction positions. Encodable whether or not options are ever traded.
- IBKR MCP connector evaluation.

---

## 7. Known problems and open questions

### The validation gap — the central problem
The 13-component conviction score has **no measured information coefficient against any
baseline.** Until it does, Z Money is a software claim, not a quant research claim. No new
capital allocation to any new strategy is justified before this exists.

Three constraints on the harness:
- **FMP's period-end anchoring leaks ~6 weeks of lookahead.** Must switch to filed-date.
- **Cross-sectional IC on 10–15 concentrated semiconductor names is near-meaningless** — too
  few observations, and a shared sector factor dominates. Running IC on the existing book
  produces a number that means nothing.
- **There is no closed loop from proposal to outcome.** `filled_at` and `fill_price` are
  never written by anything, and no code updates a proposal after insert. The system never
  learns which proposals were executed or at what price. **You cannot compute a hit rate on
  trades the system doesn't know happened.** This is arguably a harder blocker to Module A
  than the FMP anchoring issue, and it needs resolving first. Related open question: what
  `mark_filled` actually writes, given the inventory found nothing updating `proposals`.

### The fabricated-value problem
Any code path substituting a placeholder for a missing measurement is a live risk to real
money. The conviction-50 fallback already caused two unjustified trim proposals. Same class
of bug as the hallucinated news and the silent-`None` fields. This is the recurring failure
mode of the project — when in doubt, the answer is to produce nothing, not a default.

### Wheel strategy — assessed and rejected for this book
Do not recommend it:
- Variance risk premium largely disappears on single stocks (~1–2.5% annually) vs. index
  options (~3.3–3.9%)
- Covered calls would have truncated AMD's actual +133% gain
- Delta escalation during drawdowns creates maximum long exposure at the worst moment
- Realized-only accounting structurally conceals losses

### Thematic concentration
The robotics/actuator theme was investigated and found to **re-expose the existing AI/semis
cluster** rather than diversify it. MP Materials, already held, already carries
physical-actuation and critical-materials exposure. The investable actuator pool is
predominantly Chinese-listed. The structural gap this exposed: the system has **no way to
tell the user that a new idea is the same bet already owned.**

### Undecided
- **UK tax treatment of options income** — open, blocks Module B
- **Historical options data cost** — open, blocks Module B
- **Point-in-time fundamental data sourcing** — open, blocks Module A
- Whether TradingView MCP becomes a real input or stays exploratory
- Whether IBKR MCP is ever wired into the pipeline

### Behavioural note
Ideas frequently arrive from engagement-farmed social content (wheel strategy, Polymarket
Grok agent claims, TradingView bot videos, SanDisk return anchors). The established pattern
is to **fact-check these rigorously against source material, not validate them.** The
Polymarket claim was mathematically self-contradicting — Kelly sizing structurally prevents
the claimed returns. Conway/Automaton was flagged as dangerous: a self-replicating agent with
shell access and an Ethereum wallet, unsuitable for the same machine as Z Money.

---

## 8. Unknown / needs filling in

Absent from all available sources. An agent asked about these should say it doesn't know.

**Scoring**
- [ ] The full named list of all 13 conviction sub-components. Six known (business quality,
      what's-priced-in, variant perception, downside asymmetry, catalyst path, portfolio
      fit). **Seven unrecorded.**
- [ ] Actual weight values in the YAML weight dictionary
- [ ] How each sub-score is bounded (0–10? 0–100? signed?)

**Risk parameters — all numeric values**
- [ ] `max_position_pct`
- [ ] Daily loss limit, drawdown limit (kill-switch thresholds)
- [ ] Daily proposal cap
- [ ] Single-name, sector, sleeve concentration limits
- [ ] Correlated-cluster cap value and how cluster membership is defined
- [ ] Sleeve definitions and target weights
- [ ] The position sizing formula (conviction + volatility → quantity)
- [ ] Profit-taking band structure: count, spacing, fraction trimmed at each
- [ ] Conviction floor value and the "material drop" threshold for thesis decay
- [ ] ATR lookback period and calculation method
- [ ] How `activation_threshold_pct` interacts with peak tracking

**Function-level detail**
- [ ] Signatures, arguments, and return types for the 176 public functions.
      `docs/side-effect-inventory.md` has them; only the totals have been extracted so far.
- [ ] Which 43 functions are class E, and how much of that is cache/log propagation vs.
      genuine filesystem writes
- [ ] What `mark_filled` actually writes

**Order construction**
- [ ] Order type selection logic (market vs. limit vs. other)
- [ ] Limit price derivation
- [ ] TIF defaults
- [ ] Quantity rounding / minimum trade size

**Screener**
- [ ] Actual Stage 1 threshold values
- [ ] The Stage 2 Haiku prompt and its verdict schema
- [ ] What `stage2_material` encodes

**Operational**
- [ ] Whether run-7 fixes 1, 2, 4, 5 have landed — **verify before answering any question
      about current run safety**
- [ ] Whether run 8 has executed and what it cost
- [ ] Scheduling — cron / launchd, or manual runs?
- [ ] Whether Alembic is in use or the schema is created directly
- [ ] Current test coverage beyond `scoring` and `risk_rules`
- [ ] Whether the on-disk package dir is `zopro/` or `z_money/` post-rename
- [ ] Actual DB filename and path
- [ ] Exact model version strings for Haiku and Sonnet
- [ ] FMP cache location and TTL
- [ ] How the 48h news-digest cache is keyed, if implemented

**Portfolio**
- [ ] Flex Query CSV schema; reconciliation and drift-check thresholds
- [ ] How the SGD/USD FX rate is sourced and how often it refreshes
