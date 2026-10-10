# Z Money — Session Handoff
## Thematic Exposure, Signal Hygiene, and the Robotics Universe

**Date:** 9 September 2026
**Purpose:** Context transfer from a research session into the main build session. Read Parts 0–2 before touching code. Part 3 is the actual work.

---

## Part 0 — What this document is

This is a handoff from a research conversation about the humanoid robotics / actuator theme. That conversation surfaced three structural weaknesses in the current Z Money design that have nothing to do with robotics specifically — robotics was just the test case that exposed them.

Do not treat this as "add robotics stocks to the watchlist." That is the least important instruction in here. The important part is that the system currently has no way to tell me that a new idea is the *same bet I already own*, no way to detect a stock that has re-rated on narrative rather than revenue, and no record of where an idea came from.

---

## Part 1 — Project context

For a session that doesn't have the full history.

**What Z Money is:** A multi-agent trading research system. Four-agent pipeline: Screener → Research → Risk Manager → Order Builder. Deterministic code handles all risk rules and scoring math; LLM judgment is reserved for research synthesis only. Currently in **Phase 1: shadow mode** — reads real IBKR account data, places no orders, logs proposals for human review. Manual order placement in IBKR follows.

**Location:** `~/zmoney`

**Scoring:** 13-component continuous conviction score (0–100), null-handled, weights renormalized when a factor's data is unavailable so missing data is excluded rather than dragging scores to the middle.

**Risk:** Deterministic Risk Manager with hard gates and conviction-scaled exits — trailing stop ATR multiples, profit-taking thresholds, activation levels via linear interpolation across the conviction range.

**Data:** FMP (fundamentals, free tier, aggressive caching — 250 calls/day, exhausted once already), yfinance (prices), Anthropic API (research agents).

**Broker:** IBKR Lite. No TWS API access, so the architecture uses manual CSV position import plus a mark-as-filled workflow. Multi-currency handling matters: account summary returns SGD (base currency) while position values are USD. An early bug inflated NAV ~27% before this was corrected.

**UI:** Eight screens — Briefing, Watchlist, Positions, Orders, Insights, Performance, Journal, Settings.

**Current portfolio:** AMD, NVDA, MRVL, CRDO, NBIS, VRT, CLS, CEG, MP, PLTR and others. Heavily concentrated in AI/semiconductor names. **Nearly fully invested with minimal cash.** This last fact matters enormously for Part 3.

**Goals:** Investing discipline, portfolio growth, eventual side income. Also positioned on my CV as a *quantitative research* project — universe construction, cross-sectional screening, signal generation, conviction scoring, risk overlay architecture.

**Known gap (already flagged, still open):** no statistical validation of signal quality. No information coefficient, no decile spread, no hit rate with survivorship and look-ahead controls. I'm sceptical of naive backtests and don't want a validation harness that flatters the system.

---

## Part 2 — What the research session established

### 2.1 Robotics / humanoid market, ground truth as of Sept 2026

Keep these numbers — they are the factual base for anything built here.

- **Market size is small.** 2025 humanoid shipments were ~18,000 units on ~$440M revenue (up ~508% YoY). 2026 revenue estimates cluster around $1.8B, growing ~95% YoY, path to $10–15B by 2030. The entire global humanoid market generates less revenue today than a mid-cap software company.
- **Actuators genuinely dominate the bill of materials.** McKinsey teardown work puts actuation (motors, gearboxes, joint assemblies, integrated sensors/drivers) at **40–60% of BOM**. Morgan Stanley's estimate is ~56%. Perception and compute are 10–20%; compute/control 10–15%; structure 5–10%; battery 5–10%. Apptronik's CEO has said motor drivers and actuators are 60%+ of system cost. **This part of the popular thesis is correct.**
- **But the value pool is Chinese.** One analysis cited by McKinsey found that building a Tesla Optimus Gen 2 without Chinese suppliers would triple BOM from ~$46,000 to ~$131,000. Unitree lists the G1 at $16,000. Western firms can't approach that. The investable conclusion of a correct premise points somewhere I mostly can't or shouldn't trade.
- **Delivery risk is high.** Polymarket odds of a commercial Optimus launch by end-2026 recently sat around 9%, down from ~33% a month earlier. Musk calls Optimus Tesla's hardest product to scale. Gen 3 has slipped repeatedly without being shown.
- **Agility Robotics is going public via SPAC** — merger with Churchill Capital Corp XI (CCXI), announced 24 June 2026, implied valuation ~$2.5B, expected ticker AGLT. It has booked multi-year revenue >$300M covering ~1,000 robots (GXO, Amazon, Toyota Manufacturing Canada, Schaeffler, Mercado Libre). It is arguably the only humanoid company with consistent revenue from productive commercial work. Operating costs are $10–12/hour and must fall substantially. Amazon is both investor and primary deployment partner.

### 2.2 Three failure modes this exposed

These are the actual deliverable of the research session.

**A. Correlation blindness.**
I got excited about robotics as a *new* idea. It isn't. My book is AMD, NVDA, MRVL, CRDO, NBIS, VRT, CLS, CEG, MP, PLTR. That is long AI capex, long physical-AI narrative, long risk appetite, high beta. NVDA is the humanoid compute proxy. **MP is literally a rare-earth magnet name inside the humanoid BOM.** Adding VPG or CCXI doesn't diversify anything; it increases the size of a bet I've already made. And with minimal cash, it's a *sell-something-to-buy-this* decision, not a deploy-fresh-capital decision.

The system currently has no representation of this. It scores names in isolation. It will happily propose a name that is 0.9 correlated with three existing positions and call it a new idea.

**B. Narrative–revenue divergence.**
Vishay Precision Group (VPG) is the canonical case. It makes foil strain gauges for robot joint force/torque sensing — a legitimate picks-and-shovels position. But:

| Metric | Value |
|---|---|
| Humanoid bookings, Q1 2026 | $1.0M |
| Humanoid bookings, Q2 2026 | ~$0.5M |
| Quarterly revenue | $83.9M |
| Humanoid as % of business | ~1% |
| GAAP result Q2 2026 | **loss** of $1.7M |
| Stock move, trailing 90 days | **+172%, to ~$122** |
| Analyst PT move | $39 → $77 (stock above both) |
| P/S vs estimated fair ratio | 2.8x vs 1.6x |

There is a real catalyst in there — a vendor nomination letter from its first humanoid customer for an H2 2026 production ramp, and nomination letters are how auto-style supply chains actually commit. But a 172% re-rate on 1% revenue exposure is a *measurable gap* between narrative exposure and revenue exposure. The system should be able to compute that gap and surface it, rather than leaving me to notice it.

Same pattern elsewhere: Moog re-rated 92% on planetary roller screw association. Schaeffler +90–100% over a year. Leader Drive +89%, Sanhua +95.6% since KOID inception. And Tuopu is *down 24%* over the year — the trade isn't one-way.

**C. Idea provenance is unrecorded.**
Both robotics pitches I brought into the session were engagement-farmed social content ending in "comment X for the link." Their structure: open with a real past return, attach it to a real trend, stop before the question of what you pay today.

Worth being precise, because the noise is mixed with signal:

- The SanDisk anchor ("$1k → $34k in a year") is **true** — SNDK returned ~3,170% trailing. It's also causally irrelevant to robotics; it's a NAND supply-shortage cycle. And it peaked near $2,354 on 25 June and has since retreated 30%+, which went unmentioned.
- The Symbotic pitch stated true facts — $22.5B backlog, real deployed systems, actually getting paid — and omitted that **Walmart was 85% of FY2025 revenue**, that the backlog is mostly Walmart and GreenBox, and that the stock went public via SPAC at $10.51 in 2022, hit a record $87.30 in Nov 2025, and now trades ~$38, down ~32% in 2026.
- The actuator BOM thesis was **correct** and worth keeping.

The lesson is not "social content is bad." It's that ideas arrive with a provenance that predicts something about their quality, and I currently record nothing about where an idea came from.

### 2.3 The anti-pattern — what NOT to build

The other piece of content described a Grok agent given $50 and "pay for yourself or you die," claimed to be holding $5,000 after 48 hours, running autonomously with its own VM, browser and terminal, scanning ~1,000 Polymarket markets every 10 minutes, flagging >8% mispricings, sizing via Kelly at max 6% of bankroll, no human approval.

**The arithmetic doesn't close.** $50 → $5,000 is 100x. At a 6% risk cap, even if every bet is a 10:1 longshot resolving in your favour, each win takes you to 1.6x — you'd need ~10 consecutive wins on 10:1 shots with zero losses. And an 8% mispricing at 6% sizing produces a fraction of a percent of EV per bet, needing thousands of bets, against a stated 10-minute cycle capped at 288 cycles over 48 hours. Either the risk framework is real and the return isn't, or the return is real and it was unhedged concentration with Kelly mentioned as decoration.

Two further points to internalise:

- **"Pay for yourself or you die" is survivorship bias installed as a product feature.** Run a hundred; the ninety-nine that blow up don't post. 48 hours is a sample size of one over a weekend.
- **The most-praised feature is the most dangerous one.** "When its strategy stopped working it adapted, nobody told it how" describes an agent whose risk parameters no longer describe what it's doing. Every stop level, sizing rule and conviction threshold was calibrated against a strategy that no longer exists, and nothing logged the change.

Z Money already solves this by construction — deterministic risk, LLM for synthesis only, proposal-only orders, shadow mode. **Part 3 must not weaken any of that.** WS-6 below exists to make it explicit and enforced.

---

## Part 3 — Build instructions

Seven workstreams. WS-1 and WS-6 are the priority; the rest can follow. Each has rationale, spec, data source, and an acceptance test.

Where a workstream touches the 13-component conviction score, **do not reconstruct the current component list from memory — read the live scoring module and report the actual composition and weights back to me before changing anything.**

---

### WS-1 — Thematic Exposure & Correlation Layer *(highest priority)*

**Rationale:** Failure mode A. The system must be able to tell me that a candidate is the bet I already own.

**Spec:**
1. Add a `themes` tag array to every universe member. Start with a hand-curated map, not an LLM-generated one — this needs to be stable and auditable. Suggested initial tags: `ai_compute`, `ai_datacenter_power`, `ai_networking`, `memory_storage`, `physical_ai_actuation`, `physical_ai_sensing`, `critical_materials`, `warehouse_automation`, `defense_aero`.
2. Compute a rolling correlation matrix across the current portfolio plus any candidate, using trailing 120 and 250 trading days of daily returns from yfinance. Cache it; recompute daily at most.
3. Produce two portfolio-level outputs per candidate:
   - **Max pairwise correlation** to any existing position, and the name it's against.
   - **Marginal contribution to portfolio variance** if added at the proposed size.
4. Add a **hard gate** in the Risk Manager (deterministic, not LLM): if a candidate's max pairwise correlation to an existing position exceeds a configurable threshold (start at 0.75) **and** portfolio cash is below a configurable floor, the proposal is downgraded from BUY to a **SWITCH candidate** — meaning the Order Builder must name which existing position it would be funded from, and score both sides.
5. Surface a **theme concentration bar** on the Briefing screen: % of NAV by theme tag. This is the single most useful thing this workstream produces.

**Data:** yfinance daily closes for correlation; hand-maintained theme map in a versioned YAML/JSON file.

**Acceptance test:** Feed the system VPG as a candidate against the current portfolio. It must (a) tag it `physical_ai_sensing`, (b) report meaningful correlation to the existing AI complex, (c) note that MP already carries `physical_ai_actuation` / `critical_materials` exposure, and (d) because cash is minimal, emit a SWITCH proposal naming a funding source rather than a clean BUY.

---

### WS-2 — Narrative–Revenue Divergence Score

**Rationale:** Failure mode B. VPG is the reference case.

**Spec:**
1. For each candidate, compute:
   - **Theme revenue share** — revenue attributable to the hot theme ÷ total revenue. This will usually require pulling it from earnings-call disclosure rather than a clean API field. Where it can't be sourced, **leave it null and let the existing renormalization handle it** — do not impute a neutral value. The null-handling bug is already fixed; don't reintroduce it.
   - **Trailing price re-rate** — 90-day and 250-day total return, and the same as a percentile within the candidate's sector.
   - **Multiple expansion vs. estimate revision** — change in forward P/S over the window, versus change in consensus forward revenue over the same window. This decomposes the move into "numbers went up" vs. "the market decided to pay more."
2. Define **divergence = re-rate percentile − theme revenue share percentile.** High positive divergence means the price has moved far more than the exposure justifies.
3. This becomes a **new conviction sub-component**, not a gate. It should push conviction down, not veto. Weight it modestly at first (suggest ≤5%) and renormalize the rest.
4. Log the raw inputs, not just the score, so I can audit why a name scored what it did.

**Data:** FMP for revenue and consensus (cache aggressively — the 250/day cap is real); yfinance for price.

**Acceptance test:** Run VPG. It should show ~1% theme revenue share against a top-decile 90-day return, produce a high divergence score, and visibly reduce conviction. Run a name where numbers actually drove the move and confirm the divergence score stays low — this is the false-positive check and it matters more than the VPG hit.

---

### WS-3 — Structural Risk Flags

**Rationale:** Three specific, cheap, deterministic checks that the Symbotic and Agility cases both surfaced.

**Spec:** Add to the Risk Manager as boolean/scalar flags, surfaced on the Watchlist and Positions screens:

1. **Customer concentration.** Largest customer as % of revenue, from 10-K risk factors / segment disclosure. Flag above a configurable threshold (start at 30%). Symbotic at 85% Walmart is the calibration case.
2. **De-SPAC history.** Went public via SPAC, with the date. Symbotic (June 2022, $10.51 → $87.30 → ~$38) is the cautionary case.
3. **Pending SPAC merger.** Currently trading as a SPAC shell with an announced target. Agility/CCXI is live right now. This should be a **hard gate against automatic inclusion** in the tradeable universe — not a ban, but it must require an explicit manual override with a Journal entry explaining the reasoning.

**Data:** FMP `secFilings` and `company` endpoints; manual entry fallback with a `source` field.

**Acceptance test:** SYM flags customer concentration and de-SPAC. CCXI flags pending-SPAC and is excluded from auto-proposals pending override.

---

### WS-4 — Crowding / Late-to-Theme Detector

**Rationale:** Every name in both pitches had already re-rated. The system should know when it's arriving late.

**Spec:** A composite indicator, surfaced on Insights:
- Trailing 90d return percentile within sector.
- Distance from consensus price target — specifically flag when **price exceeds the highest recent analyst PT**, which is what VPG did ($122 vs a PT raised to $77).
- Short interest and days-to-cover trend, where available.
- Rate of analyst PT revisions (a cluster of rapid upward revisions is a crowding signal, not a confirmation signal).

Feed this into conviction as a **modest negative** at extremes only. It should not penalise ordinary momentum — the goal is to detect the tail, not to fight trends.

**Acceptance test:** VPG in August 2026 scores high on crowding. A steadily-appreciating name with matching earnings revisions does not.

---

### WS-5 — Idea Provenance in the Journal

**Rationale:** Failure mode C. Also directly serves the learning goal that the Journal screen exists for.

**Spec:** Add structured fields to every Journal entry and every watchlist addition:
- `source_type`: one of `screener` | `social` | `newsletter` | `sell_side` | `own_research` | `friend` | `other`
- `source_url` (optional)
- `claimed_return` (optional, free text — capture the hook if there was one, e.g. "$1k → $34k")
- `date_first_seen`
- `price_at_first_seen` — auto-populated

Then, on the Performance screen, add a **provenance cohort view**: realised and unrealised return by `source_type`, and — critically — **forward return from `price_at_first_seen`**, whether or not I ever bought it.

This is the highest-value item for the CV framing. It is a genuine, honest, personally-generated dataset on signal quality by origin, and it accumulates from day one without requiring capital at risk.

**Acceptance test:** Log VPG and CCXI now with `source_type: social`. In six months I should be able to see how the `social` cohort performed against the `screener` cohort from first-seen price.

---

### WS-6 — Strategy Version Lock *(second priority — do this early)*

**Rationale:** Section 2.3. This is the anti-drift guarantee, and it's the thing that makes the whole system defensible when explaining it to anyone.

**Spec:**
1. Every scoring weight, gate threshold, ATR multiple, and interpolation parameter lives in a **single versioned config file** with a semantic version string.
2. The config version is **stamped onto every proposal, every Journal entry, and every logged run.**
3. **No agent may write to this file.** Not the Research agent, not the Screener, not any future component. Changes are made by me, by hand, and produce a diff entry in a changelog with a written rationale.
4. Add a startup assertion that fails loudly if the config hash doesn't match the recorded version.
5. On the Performance screen, show performance **segmented by config version**, so a strategy change never silently contaminates a track record.

**Acceptance test:** Attempt a programmatic write to the config from within an agent context. It must fail. Change a weight by hand and confirm the version bump propagates to new proposals while historical proposals retain their original stamp.

---

### WS-7 — Fractional Kelly Sizing *(optional, lower priority)*

**Rationale:** Kelly came up in the anti-pattern content, dressed up as sophistication. It is one line of algebra. **The hard part is estimating edge, and that is precisely the input I don't have validated yet.**

**Spec — only implement after the validation harness exists (see Part 4):**
1. Implement fractional Kelly at **quarter-Kelly or less**, never full Kelly.
2. Edge estimate must come from **measured historical performance of the conviction score** — decile spread, hit rate — not from a model's stated confidence. If the harness doesn't exist, the edge input doesn't exist, and this workstream should not ship.
3. Keep the existing hard position-size cap as an outer bound that Kelly can only ever reduce, never raise.

**Do not build this before WS-6 and the validation harness.** A sizing formula fed a fabricated edge estimate is worse than a flat sizing rule, because it looks rigorous.

---

## Part 4 — Universe additions

Add these as **watchlist-only, tagged, not auto-proposable**, so they flow through WS-1 and WS-2 as test cases rather than as recommendations:

| Ticker | Name | Theme tags | Note |
|---|---|---|---|
| VPG | Vishay Precision Group | `physical_ai_sensing` | WS-2 reference case |
| SYM | Symbotic | `warehouse_automation` | WS-3 reference case (85% Walmart, de-SPAC) |
| CCXI | Churchill Capital XI → Agility | `physical_ai_actuation` | WS-3 pending-SPAC gate test |
| RRX | Regal Rexnord | `physical_ai_actuation` | Cheapest US mechanical-layer name; low actual robotics revenue |
| MOG-A | Moog | `physical_ai_actuation`, `defense_aero` | +92% on association; aero volumes/prices |
| KOID | KraneShares Humanoid Robotics ETF | basket | Note: heavy China weight, holdings already re-rated |
| MP | *already held* | `critical_materials`, `physical_ai_actuation` | **Retag existing position** — this is the correlation-blindness proof |

The MP retag is the important one. It's the line item that demonstrates the robotics theme was already in the book before the research session started.

---

## Part 5 — Explicit non-goals

Say no to all of these, including if I ask for them later in a moment of enthusiasm:

- **No autonomous execution.** Order Builder stays proposal-only. Phase 3 is not now.
- **No self-modifying strategy.** See WS-6. An agent that adapts without a logged change is the failure mode, not the feature.
- **No LLM in the risk path.** Deterministic code owns every gate, threshold and sizing rule. LLM is for research synthesis only.
- **No backtest that flatters.** If a validation harness is built, it needs survivorship-bias and look-ahead controls, out-of-sample holdout, and it must be capable of returning "no detectable edge." A harness that can't fail isn't a harness.
- **No prediction-market or high-frequency module.** Different venue, different liquidity, different edge structure. Out of scope.

---

## Part 6 — Open questions for the building session

Answer these before or during implementation:

1. **What are the current 13 components and their weights?** Read the live scoring module and report them. WS-2 and WS-4 both add sub-components and I need the real composition, not a reconstruction, to decide what gets renormalized.
2. **Where does theme revenue share realistically come from?** FMP segment data is probably too coarse. Is this a manual field with a `source` and `as_of_date`? If so, how is staleness handled?
3. **What's the FMP call budget for WS-2 and WS-3 at current universe size?** The 250/day cap has already been hit once. Model this before writing the fetch layer.
4. **Correlation on what return series?** Daily is noisy at 120 days, weekly loses resolution. Propose and justify.
5. **What does the validation harness actually need to exist?** This is the biggest open gap in the project and it now blocks WS-7. Scope it.

---

## Part 7 — Priority order

1. **WS-6** (Strategy Version Lock) — cheap, foundational, makes everything else auditable
2. **WS-1** (Correlation & Theme Exposure) — highest analytical value
3. **WS-5** (Idea Provenance) — cheap, starts accumulating data immediately, best CV artefact
4. **WS-3** (Structural Risk Flags) — cheap, deterministic
5. **WS-2** (Narrative–Revenue Divergence) — highest data-sourcing difficulty
6. **WS-4** (Crowding Detector)
7. **Validation harness** — scope it, then reassess
8. **WS-7** (Fractional Kelly) — blocked on the harness

---

## Appendix — The one-line version

The research session was nominally about robotics. What it actually found is that Z Money can score a stock but cannot yet score a *portfolio*, cannot distinguish a price move driven by revenue from one driven by narrative, and cannot remember where an idea came from. Fix those three things and the robotics question answers itself.
