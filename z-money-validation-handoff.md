# Z Money — Context & Build Handoff

**Purpose of this document:** hand a new build session enough context to work on Z Money without re-explaining the project, plus a prioritised set of build instructions. Written after a research session reviewing three external projects. Read the whole thing before starting work.

---

## Part 1 — Project context

### What Z Money is

A multi-agent trading research system built by Zoravar (19, London), serving two purposes at once: a learning vehicle for developing investing discipline, and a source of systematic, AI-assisted signal generation on a real portfolio.

It is **not** an attempt at full automation. The explicit goal is human-in-the-loop discipline, not replacing judgement.

On a CV it is positioned as a **quantitative research project**, not a software engineering one. Use the vocabulary of quant research when describing it: universe construction, cross-sectional screening, signal generation, conviction scoring, risk overlay architecture. Avoid framing it as an app or an infra project.

There is a separate, unrelated project called **Zopro** (personal AI second-brain/orchestrator). Do not conflate the two. There is also a separate passive wealth sleeve on Endowus which is not connected to Z Money in any way.

### Current architecture

Lives at `~/zmoney`. Built and iterated through Claude Code CLI sessions.

**Four-agent pipeline:** Screener → Research → Risk Manager → Order Builder

**Division of labour (this is a core design commitment):**
- Deterministic code handles all risk rules and scoring math
- LLM judgement is confined to research synthesis only
- Nothing safety-critical depends on model output

**Conviction score:** 13 components, continuous 0–100. Null-handled: when a data factor is unavailable it is excluded from scoring and the remaining weights are renormalised, rather than assigning a neutral score that silently drags results toward the middle. (This was a real bug that got fixed; preserve the behaviour.)

**Risk Manager:** fully deterministic. Hard gates plus conviction-scaled exits — trailing stop ATR multiples, profit-taking thresholds, and activation levels interpolated linearly across the conviction range.

**Order Builder:** proposal-only. There is no auto-execution code path. Proposals are logged for human review, then orders are placed manually in IBKR.

**Data sources:**
- FMP for fundamentals (free tier, aggressively cached — 250 calls/day was exhausted in a single early run)
- yfinance for price data (switched away from FMP for prices)
- Anthropic API for the research agents

**Broker:** IBKR Lite. Does not support the TWS API, so the current workflow is manual CSV position import plus a mark-as-filled step. Multi-currency handling matters here: account summary returns SGD (base currency) while position values are in USD. Early runs inflated NAV by roughly 27% before this was corrected. Any new valuation code must handle this explicitly.

**UI:** eight screens — Briefing, Watchlist, Positions, Orders, Insights, Performance, Journal, Settings. Light theme, card-based, clear hierarchy. The Journal screen exists to support the learning goal (personal trade reflections).

**Current phase:** Phase 1, shadow mode. Reads real IBKR account data, places no orders. Live pipeline runs have surfaced real signals (AMD as a trim candidate, RKLB and MP as exit candidates), so the system works end to end.

**Portfolio context:** heavily concentrated in AI/semiconductor names — AMD, NVDA, MRVL, CRDO, NBIS, VRT, CLS, CEG, MP, PLTR and similar. Nearly fully invested, minimal cash. This concentration matters for the validation work below.

### Non-negotiable design principles

Do not propose changes that violate these without flagging the conflict explicitly:

1. **Human-in-the-loop.** The Order Builder stays proposal-only. Autonomous execution, even for stops and trims under a size cap, is Phase 3 and is not on the current roadmap.
2. **Deterministic risk, LLM synthesis.** Risk rules and scoring math stay in code. This keeps the system auditable and prevents model drift from touching safety-critical logic.
3. **Null handling.** Missing data excludes a factor and renormalises weights. Never a silent neutral score.
4. **Shadow mode first.** Calibrate conviction thresholds against real portfolio signals before committing capital.
5. **Skepticism of naive backtests.** A backtest without survivorship and look-ahead controls is a credibility liability, not an asset. Rigorous validation or none.

### Working preferences

- Prefers precise analysis against actual code and configs over reconstruction from memory. If the exact composition of the 13 conviction components matters to a task, ask for the scoring module to be pasted rather than guessing.
- Builds iteratively through live pipeline runs to validate behaviour, rather than reasoning about it abstractly.
- UI iteration is heavy; reference mockups work better than verbal design briefs.
- Wants critical synthesis of external material, not summary.

---

## Part 2 — What was reviewed and what came out of it

Three external projects were assessed in the prior session. Summarised here so this session doesn't repeat the evaluation.

### HKUDS/Vibe-Trading (github.com/HKUDS/Vibe-Trading) — genuinely useful

Open-source (MIT) research workspace from the HKU Data Intelligence Lab. Python/FastAPI backend, React frontend, `pip install vibe-trading-ai`. ~32k stars. ReAct agent core, 107 tools, 90 finance skills, 30 multi-agent swarm presets, 10 backtest engines, 23 free data sources with per-market fallback chains, a `quantlib` module with 306 tested finance functions, 14 broker connectors, 74 MCP tools.

Verdict: **broader and shallower than Z Money in any single place. Do not rebuild on top of it.** Its value is as a source of four specific things:

1. **The alpha bench** — `vibe-trading alpha bench` scores a whole family of factors for IC, IR, and alive/reversed/dead status in one command. This is the validation methodology Z Money is missing. The Alpha Zoo (462 alphas: Qlib158, Kakushadze 101, GTJA 191, plus academic and PIT-safe fundamental factors) is all published public material with no expected edge, but it makes an excellent **null baseline**.
2. **Governance design** — every run writes a manifest hashing the prompt, skill contents, tool registry, and package versions. The audit ledger chains each record to its predecessor's hash and fsyncs, so an edit is detectable one record later even if it recomputes its own hash.
3. **Structural paper/live separation** — paper-vs-live is a per-broker runtime guard (account-ID format, host separation, demo flag), never a config flag the agent can flip. Order-placing tools are excluded from MCP entirely. Research and backtest paths are structurally barred from live endpoints.
4. **Their changelog** — an unusually honest catalogue of bugs a system like Z Money will hit. Several map onto bugs already encountered here.

Bugs from their changelog worth knowing about in advance:
- Futu HKD holdings valued as USD, overstated by the FX rate. (Same class as the SGD/USD NAV bug already fixed here.)
- Thirteen factors forward-filled a missing close before computing returns, turning a data gap into a finite 0% return. (Same class as the null-handling bug already fixed here.)
- A backtest moved `start_date` back a year to warm up MA200, then graded that year. A run billed as ten years reported eleven, internally consistent, nothing raised.
- `positions.csv` held target weights rather than fills, so reports claimed 80% exposure when lot rounding and fees left the book near 20%.
- A-share volume reported in board lots by five sources and shares by a sixth, so a fallback silently rescaled every volume signal 100×.
- A kill switch that marked itself fired without ever attempting the broker write, because a failed call returned an error envelope instead of raising.

They also hit the IBKR wall. Their IBKR connector is read-only via local TWS/Gateway, and they separately fought IBKR's official MCP endpoint (`api.ibkr.com/v1/api/mcp-public`) through OAuth registration failures before getting `get_account_summary` and `get_account_positions` working as a read-only portfolio source.

### The viral Grok/Polymarket post — fabricated

A widely-shared claim that a Grok agent turned $50 into ~$5,273 on Polymarket in 48 hours using Kelly sizing capped at 6% of bankroll and entering on mispricings above 8%.

X Community Notes flagged the original: the video shows a fabricated dashboard unrelated to Polymarket's interface, and the linked Polymarket account predates the claim by months with activity inconsistent with a $50 start. A copycat account posted the same template twice in two days with different numbers and market types; that one was noted too, with the video actually showing ~$50 to ~$1,100 over 26 hours.

The claim also fails on internal math independent of any fact-check. At a 6% maximum stake, a win at 2:1 net odds multiplies bankroll by 1.12, so 100× requires roughly 41 consecutive wins with no losses. At near-even Polymarket odds it's closer to 79. Kelly is the formula that *prevents* that outcome. Position-sizing rule and claimed return are mutually exclusive.

**Generalisable test:** when a claim gives you both a position-sizing rule and a return, check whether they're compatible. They usually aren't.

### Conway-Research/automaton — do not run

Self-replicating agent runtime. Generates an Ethereum wallet at boot, runs a Think→Act→Observe loop with shell access and file I/O, can edit its own source while running, spawns funded child agents. Four credit-based "survival tiers" from full frontier inference down to dead at zero balance.

No market data layer, no backtest engine, no risk model. Zero overlap with Z Money.

Every survival mechanic routes money to Conway Cloud — compute, inference, domains, payments. Independent reviewers describe adopting it as adopting Conway's infrastructure stack, a step backward in sovereignty for anyone already running their own server and calling model APIs directly, with a README that is more manifesto than documentation. The README itself says development has moved to Conway's internal environments; the public repo has 139 open issues and 88 open PRs against 307 commits, with issue creation now restricted.

Its safety model is the inverse of what Z Money should adopt: self-modification is controlled by filesystem permissions rather than sandboxing, so the agent can rewrite its own ReAct loop while a three-law constitution sits in read-only markdown files. The constraint is a prompt, and the thing constrained can rewrite the machinery reading the prompt.

**Do not install it.** The install path is `curl -fsSL https://conway.tech/automaton.sh | sh` and what it installs has shell execution, filesystem write, self-modification and a wallet. It must not run on the same machine as `~/zmoney`, which holds FMP and Anthropic keys, IBKR-connected code, and position data.

One idea worth taking: the tiered degradation pattern (full model → cheaper model → minimal → stop) as a cost-control policy. See Task G.

---

## Part 3 — The identified gap

**Z Money has no statistical validation of signal quality.** Neither the system nor the CV entry can currently answer: does the 13-component conviction score predict anything?

This is the single highest-priority piece of work. It is also the difference between "I built a multi-agent pipeline" (a software claim) and "I built a signal and measured its information coefficient against a public-factor baseline with survivorship and look-ahead controls" (a quant research claim).

Everything else on the roadmap — TradingView MCP chart perception, a technical sub-score, Phase 3 autonomy — is deferred until this exists. Adding a 14th component to a 13-component model that has never been measured is motion, not progress.

---

## Part 4 — Build instructions

Work in this order. Tasks A–C are the critical path.

### Task A — Generate a null baseline (do first, ~1 evening)

Install Vibe-Trading in a **fully isolated venv, in a separate directory, nowhere near `~/zmoney`**. Never configure a broker connector inside it.

```bash
python -m venv ~/vt && source ~/vt/bin/activate
pip install vibe-trading-ai
vibe-trading alpha bench --zoo alpha101 --universe sp500 --period 2018-2025 --top 20
```

Notes:
- `alpha bench` is a deterministic CLI command and should not require an LLM key. Only the agent paths need one.
- It defaults to free data sources (yahoo / yfinance / stooq), so FMP quota is untouched.
- Repeat for `--zoo qlib158` and `--zoo gtja191` if the first run works.

**Deliverable:** the IC distribution of published public alphas on a large-cap US universe over a real period. Save the raw output. This is the number Z Money's conviction score gets compared against.

Then attempt the same on a universe closer to Z Money's own. If there is no clean way to pass a custom symbol list, that is the first real integration question — document it rather than hacking around it.

### Task B — Extract the methodology (~1 hour of reading)

Read three files from the Vibe-Trading source. Do not read the whole repo.

- `agent/src/factors/bench_runner.py` — how IC is computed, how quantile groups are formed, how alive / reversed / dead is decided
- `src/quantlib/crossvalidation` and `src/quantlib/multipletesting` — purged cross-validation and deflated significance
- `agent/src/factors/base.py` — the 19 operators, specifically how lookahead is banned **at the operator layer** rather than tested for afterwards

That last point is the important one. Enforcing no-lookahead in the primitives is structurally different from checking for it after the fact, and it's what would let Z Money's validation claim be trustworthy.

**Deliverable:** a short written note on what to replicate and what to do differently, given Z Money's much smaller universe.

### Task C — Build the validation harness (the actual project)

This is a new module in Z Money. It does not touch the live pipeline.

**Start with one component, not all thirteen.** Pick the single component most expected to work. Get the full measurement chain working end to end on that one before extending.

**The measurement chain:**

For a fixed universe and period, at each rebalance date `t`:
1. Compute the component score cross-sectionally, using only data available at `t`
2. Compute forward returns at 1, 5 and 20 trading days
3. Compute Spearman rank IC between score and each forward-return horizon

Then across all dates:
- IC mean, IC standard deviation, IR (mean / std), t-statistic
- Hit rate (fraction of dates with IC > 0)
- Top-vs-bottom group spread (see universe caveat below)
- All of it repeated per horizon

**Controls that must be in place or the numbers are worthless:**

- **Point-in-time discipline.** Scores use only data available at `t`. No exceptions.
- **Filed-date anchoring for fundamentals.** This is a specific trap with FMP. FMP fundamentals are keyed on period end. A Q3 figure with a period-end date of 30 September was not public until the filing date, typically 30–45 days later. Anchoring on period end leaks roughly six weeks of future information into every fundamental factor. Anchor on filing date. If FMP's free tier doesn't expose filing dates reliably, apply a conservative fixed lag (e.g. 45 days for quarterlies, 90 for annuals) and **document that the lag is an approximation**.
- **Survivorship control.** Universe membership must be point-in-time, not today's list. Testing a signal on today's AMD/NVDA/PLTR list over 2018–2025 measures the performance of names that survived to 2026, which is not a signal.
- **Purged CV with an embargo.** 20-day forward returns overlap across adjacent rebalance dates. Without purging and an embargo gap, train and test windows share information and every result is inflated.
- **Multiple-testing correction.** Testing all 13 components is 13 hypotheses. The best of 13 random signals will look good. Apply a deflation (Bonferroni as a floor, deflated Sharpe if the quantlib implementation is portable).
- **Transaction costs.** Report both gross and net of a realistic cost assumption.

**The universe problem — address this explicitly.** Z Money's live universe is ~10–15 concentrated AI/semiconductor names. Cross-sectional IC on 10 names is close to meaningless: rank correlation on that few observations has enormous standard error, and every name shares the same sector factor, so the cross-section is mostly noise around a single common driver.

Two viable responses, and the harness should probably do both:
1. **Validate on a wide universe.** Run the components on S&P 500 or a 100+ name tech/semis universe where cross-sectional statistics actually have power. This measures whether the signal has any edge at all.
2. **Use time-series validation on the live universe.** On 10–15 names, ask a different question: does a high conviction score on a given name predict that name's own forward return relative to its own history, or relative to a sector benchmark? Event-study framing works better here than cross-sectional IC.

Do not report a cross-sectional IC computed on 12 names as if it were a validated result. That is exactly the kind of naive-backtest credibility liability the project is trying to avoid.

**Then, and only then:**
- Extend to all 13 components individually
- Measure the composite score
- Compare every number to the alpha101 baseline from Task A

**Deliverable and honest outcome:** a report giving, per component and for the composite, IC mean / IR / hit rate / spread at each horizon, with the baseline alongside. If the best single component doesn't clear the median public alpha, **that is the finding**, and being able to state it clearly is worth more than a working pipeline.

### Task D — Test the IBKR MCP connector (~30 min)

An IBKR connector is available in the Claude tool environment. Test whether it returns account summary and positions for an IBKR **Lite** account.

- If it works: the manual CSV import workflow can be retired and multi-currency handling moves into code that's controlled here. Handle the SGD-base / USD-position mismatch explicitly from the start.
- If it doesn't: the wall is confirmed and the manual workflow stays. Document the failure mode so it doesn't get re-litigated.

Either outcome is worth the time. This is read-only account and position data; it does not create any execution path.

### Task E — Governance and audit trail

Adapt the Vibe-Trading pattern to Z Money's proposal log.

- **Run manifest:** every pipeline run writes a manifest hashing the prompt(s), the scoring module contents, the risk-rule configuration, and package versions. A proposal from three months ago must be traceable to the exact methodology that produced it.
- **Hash-chained proposal ledger:** each proposal record chains to the previous record's hash, and writes are fsynced. An edit or deletion becomes detectable one record later, even if the edited record recomputes its own hash.
- **Caller-supplied timestamps** in the ledger module, never `datetime.now()` inside it, so the ledger is testable and deterministic.

This matters more than it looks. The whole output of shadow mode is a log of proposals that will later be graded. If that log is silently editable, the grading is worthless.

### Task F — Make the paper/live boundary structural (before any Phase 3 discussion)

Currently the Order Builder is proposal-only by design and convention. Convert that to an architectural invariant, along the lines of Vibe-Trading's approach:

- Live-vs-shadow determined by a runtime property that no config flag and no agent output can flip
- Any execution-capable code path physically absent from, or hard-refused by, the research and scoring modules
- If Z Money ever exposes tools over MCP, order-placing tools are excluded from that surface entirely
- Failed broker calls fail closed. An error envelope returned as a success value is the exact bug that let Vibe-Trading's kill switch mark itself fired without ever attempting the write.

Do this before Phase 3 is even discussed, not as part of it.

### Task G — Budget-tiered LLM degradation

Cost control, adapted from Automaton's survival tiers minus the philosophy.

- Full research synthesis (frontier model) reserved for high-conviction candidates only
- Cheaper model, or cached-only, for the rest of the universe
- Hard daily spend cap on the Anthropic API with graceful degradation rather than a mid-run failure
- Same treatment for FMP: the 250/day free-tier limit was exhausted in a single early run, so the cache policy should be tier-aware rather than uniform

Small task, real benefit, roughly an afternoon.

---

## Part 5 — Deferred and out of scope

**Deferred until the validation harness exists:**

- **TradingView MCP chart perception.** Genuinely interesting as an input layer (live charts, levels, timeframe switching, indicator state) but it adds a signal to a model that can't yet measure signals. Once the harness works, this becomes testable: does the technical sub-score add IC over the existing 13? That's a much better reason to build it.
- **Discrete price-action conditions** as a technical sub-score (breakout above prior high, above 200-day MA, relative sector strength). Same reasoning. Note: when this does get built, the exact current composition of all 13 components should be pasted into the session rather than reconstructed from memory.
- **Shadow Account-style behavioural diagnostics.** The best idea in the HKU repo: parse the broker export, profile behaviour quantitatively (holding days, win rate, PnL ratio, drawdown, disposition effect, overtrading, momentum chasing, anchoring), extract implicit trading rules, then backtest those extracted rules against the trades actually made to surface rule breaks and early exits. The Journal screen currently does the qualitative half of this. The quantitative half would be a strong differentiator — but it needs trade history that's still accumulating in shadow mode, and it competes with the validation work on the critical path.
- **Phase 3 autonomy** (auto-executing stops and trims under a size cap). Future consideration only. Not active. Task F is a prerequisite.

**Out of scope entirely:**

- Rebuilding Z Money on top of Vibe-Trading. Its model is LLM-generated strategy code in a hardened sandbox; Z Money's is deterministic risk with LLM confined to synthesis. Z Money's design is the more defensible one and the easier one to explain in an interview.
- Anything touching Vibe-Trading's live or broker execution paths. Their own disclaimer states the broker-trading capability is experimental and not verified against a real broker account.
- Installing or running Conway/Automaton in any form.
- Adopting the 462 published alphas as signals. They are a baseline and a measurement target, not a source of edge.

---

## Part 6 — Sequencing summary

| Order | Task | Effort | Blocks |
|---|---|---|---|
| 1 | A — null baseline via alpha bench | 1 evening | Task C comparison |
| 2 | B — read three methodology files | 1 hour | Task C design |
| 3 | C — validation harness, one component first | The real project | Everything deferred |
| 4 | D — IBKR MCP connector test | 30 min | Nothing (parallel) |
| 5 | E — run manifest + hash-chained ledger | Small | Shadow-mode grading integrity |
| 6 | F — structural paper/live guard | Small | Any Phase 3 discussion |
| 7 | G — budget-tiered degradation | Afternoon | Nothing |

Tasks D and G can run in parallel with C. Tasks E and F should land before shadow mode accumulates much more history.

---

## Part 7 — Standing note

There is a lot of content in circulation arguing that autonomy is the frontier and that human-in-the-loop is a limitation to be outgrown. Of the three projects reviewed in the prior session, one was a legitimate but over-hyped research repo, one was a fabricated viral post flagged by Community Notes, and one was a marketing funnel for a cloud provider wearing a manifesto.

Z Money's gap is not autonomy. It is that the signals have not been shown to have any edge. Proposals that increase autonomy, add components, or expand scope before the validation harness exists should be pushed back on, with this document as the reason.
