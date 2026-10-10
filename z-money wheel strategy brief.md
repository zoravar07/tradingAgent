# Z Money — Options / Volatility Premium: Research Findings & Build Brief

**Purpose of this document.** This is a handoff from a research conversation into the main Z Money build session. It has two halves: (1) what the evidence actually says about the "wheel strategy" and options premium selling, and (2) what, if anything, should be built in Z Money as a result. Read part 1 as context. Read part 2 as a scoped proposal, not as approved work — the ordering in it matters more than the contents.

The short version: the volatility risk premium is real, but almost none of it is available where the retail wheel strategy tells you to look for it, and the highest-value thing to build out of this research is **not** an options module. It's the signal validation harness that Z Money is already missing.

---

## 1. System context (for a build chat with no prior state)

**Operator:** 19, London-based, self-directed. Z Money is simultaneously a learning vehicle and a real capital-allocation tool. Not a software engineering project — framed and presented as quantitative research.

**Current state of Z Money:**
- Phase 1, shadow mode. Reads real IBKR account data, places no orders. Proposals are logged for human review; order placement is manual.
- Four-agent pipeline: Screener → Research → Risk Manager → Order Builder.
- Deterministic code handles all risk rules and scoring math. LLM judgment is used only for research synthesis. This split is non-negotiable and any new module must respect it.
- 13-component continuous conviction score (0–100), null-handled with weight renormalisation.
- Deterministic Risk Manager: hard gates plus conviction-scaled exits (trailing stop ATR multiples, profit-taking thresholds, activation levels interpolated across the conviction range).
- Order Builder is proposal-only. No auto-execution path exists. Phase 3 autonomy (auto-executing stops and trims under a size cap) is a future consideration, not active.

**Infrastructure constraints that bound everything below:**
- Broker is **IBKR Lite**, which does not support the TWS API. Workflow is manual CSV position import plus mark-as-filled. Nothing in this brief can assume programmatic order placement or live position streaming.
- Multi-currency: account summary returns SGD (base), position values are USD. An earlier bug inflated NAV by ~27% before this was corrected. Any new NAV-relative sizing logic must handle this explicitly.
- Data: FMP (fundamentals, free tier, aggressively cached — 250 calls/day is exhaustible in a single run), yfinance (prices), Anthropic API (research agents).
- Portfolio is heavily concentrated in AI/semiconductor names (AMD, NVDA, MRVL, CRDO, NBIS, VRT, CLS, CEG, MP, PLTR and similar) and is **near fully invested with minimal cash**.

**Known gap, already flagged before this research:** the system has no statistical validation of signal quality. No information coefficient, no decile spread, no hit rate with survivorship and look-ahead controls. This gap is the through-line of the whole document.

---

## 2. What prompted the research

A social-media pitch for the "wheel strategy", presented as a three-step infinity loop that pays at every step:

1. Sell a cash-secured put — get paid upfront to promise to buy a stock "at a massive discount".
2. If assigned, sell covered calls against the shares — "charge the market weekly rent".
3. When the stock rises, get called away "for a massive profit", return to cash, repeat.

Framing: "stop holding and hoping, start acting like the casino", plus a call to action to join a paid community. The claim attached was beating the market every year without ever buying stock outright.

The strategy is real and widely traded. The pitch misrepresents it in three specific ways, and the misrepresentations matter for how Z Money should treat it.

---

## 3. Research findings

### 3.1 The underlying edge is real

Implied volatility has historically exceeded realized volatility on the index. From 1990 to 2018 the average VIX was 19.3% against average realized S&P volatility of 15.1% — a persistent gap of roughly 4.2 percentage points.

The cleanest live evidence is the Cboe S&P 500 PutWrite Index (PUT), which systematically sells one-month at-the-money SPX puts fully collateralised by T-bills. Over roughly 32 years it produced a compound annual return of **9.54% against 9.80% for the S&P 500**, with standard deviation of **9.95% against 14.93%** — comparable return, materially lower volatility, better Sharpe. It outperforms in flat and falling markets and underperforms when stocks rise sharply.

So: systematic index put-writing is a legitimate strategy with a real risk premium behind it. That is the strongest true statement available here, and it is an *index* statement.

### 3.2 The wheel is one position, not three income streams

By put–call parity, a covered call has the same payoff as a short put at the same strike. Both legs of the wheel have identical shape: **upside capped at the premium received, downside running the full distance to zero.**

The "paid at every step" framing describes a single short-volatility position whose delta wanders, not a loop through three distinct risk profiles.

### 3.3 The delta escalation problem

This is the structural objection, articulated most clearly by Karsten Jeske (Early Retirement Now, "Why the Wheel Strategy Doesn't Work"):

- You start at, say, 20-delta short put — a cautious position.
- The stock falls, you get assigned, and you now hold 100-delta stock offset by a short call.
- The further the stock falls, the more worthless the call becomes, and the closer your net delta goes to 100.

The strategy makes you **maximally long exactly when you have been most wrong.** It is a martingale / tactical valuation bet wearing the costume of an income strategy. It performs acceptably in choppy mean-reverting markets and fails badly in sustained downtrends — which is the risk that actually matters. Between 2000 and 2013 the S&P spent most of its time underwater; a wheel anchored to pre-2000 strikes would have generated almost nothing for over a decade.

### 3.4 The edge largely disappears on single stocks

This is the finding most retail wheel content omits, and it is the most decision-relevant one.

The variance risk premium that makes index put-writing profitable is substantially a **correlation risk premium** — it exists because institutions buy index puts as portfolio crash insurance, bidding index options expensive relative to the options on the same index's constituents.

- Driessen, Maenhout and Vilkov (2009): implied volatility exceeded realized by roughly **3.89% annually on S&P 100 options but only 2.47% on the individual constituent stocks**.
- Bakshi and Kapadia (2003): roughly **1% on single stocks against 3.3% on the index**.
- Carr and Wu note the single-stock variance risk premium is so noisy that only a handful of names in their sample showed a statistically significant negative premium at all.

Running the wheel on individual tickers therefore means accepting **the fattest idiosyncratic tail risk in exchange for the thinnest premium.** A single stock can go to zero and stay there. SPX cannot.

### 3.5 The backtests do not support the pitch

- Spintwig's SPY wheel backtest across ten configurations: the long SPY position accounted for **94–99% of total return**; the option legs were immaterial. **Not one of the ten configurations beat plain buy-and-hold on total return**, and four went negative.
- A wheel on AMD from Jan 2022 to Jan 2024: approximately **-4.75% with a 35% maximum drawdown**, against roughly +5% for simply holding the shares over the same window.

The general shape, consistent across sources: the wheel wins small and often, loses rarely and large, and underperforms buy-and-hold in bull markets while cushioning bear markets. Whether that trade is worth making depends entirely on the return distribution of the underlying — see section 4.

### 3.6 The "discount" claim is backwards

On assignment you buy at the strike, and the stock is by then trading *below* the strike. You have bought above market and are immediately underwater. The premium is a partial offset, not a discount. The discount framing only works by comparing the strike to the price on the day the put was sold, which was never an available purchase price.

### 3.7 The strategy is structurally easy to fake results with

Jeske's sharpest point. Practitioners commonly report **realized** P&L only. Assigned shares sitting 40% underwater are unrealized and never appear in the headline number, while the premium income does. A trader can post a run of profitable months while the account is materially down. Notable casualties among wheel practitioners include RIDE (bankrupt), PTON (down ~97% from peak) and ARKK.

Practical consequence: **any reported wheel performance that does not mark all positions to market is uninterpretable**, including one's own.

### 3.8 On the pitch itself

The video ends in a call to action to join a paid community. The strategy functions as a lead magnet. This does not make it wrong, but note that the specific claim made — beating the market every year — is both unverifiable and, per 3.7, trivially fakeable with this exact strategy. Treat the genre accordingly.

---

## 4. Why this matters specifically for the current portfolio

Three constraints make the naive version a poor fit here, independent of the general critique.

**Right-tail truncation is the wrong trade for this universe.** The portfolio is concentrated in AI/semiconductor names with heavily skewed return distributions — a small number of positions carry the entire portfolio return. Writing covered calls systematically truncates exactly the outcome those positions are held for. Selling a 25-delta monthly call on a name that then runs 60% means selling that year's return for a few percent of premium. Covered calls suit low-conviction, range-bound, mean-reverting holdings. That is the opposite of the current book.

**There is no cash to secure puts with.** The portfolio is near fully invested. In practice this means only the covered-call leg is executable — the half with capped upside and only premium-sized downside cushion. That is strictly worse than the full wheel.

**IBKR Lite has no TWS API.** Nothing here automates into the existing pipeline. Any options module would produce proposals that are then manually entered, adding operational load to a system already running a manual CSV import workflow.

**Tax treatment is unresolved.** Most wheel content is written for US traders and implicitly assumes SPX 1256 treatment (60/40 long/short-term). UK treatment of frequent options premium is different and the annual CGT exempt amount is small. This needs professional advice before any capital is committed — not a build-chat decision.

---

## 5. What to build

Ordered by priority. **Module A is the actual deliverable of this research. Modules B and C are conditional on A existing and producing results.**

### Module A — Signal Validation Harness (build this first, regardless of anything else)

The single highest-value thing to come out of this research is the realisation that the same skepticism applied to the wheel has not yet been applied to Z Money's own 13-component conviction score. If naive wheel backtests are a credibility liability, so is an unvalidated conviction score.

**Scope:** a standalone, deterministic validation module that can score any signal — the existing 13 components individually, the composite score, and any future component including options-derived ones.

**Required outputs per signal:**
- **Information coefficient** — rank correlation between signal value at time *t* and forward return over horizon *h*. Report across multiple horizons (1w, 1m, 3m, 6m). Report the IC time series, not just the mean; report IC standard deviation and IC information ratio.
- **Decile / quintile spread** — sort the universe cross-sectionally by signal each rebalance, report mean forward return by bucket. Monotonicity across buckets is the thing to look for, not just top-minus-bottom.
- **Hit rate** — fraction of periods where the top bucket beat the bottom bucket, and where the signal's directional call was correct.
- **Turnover and decay** — how fast does IC decay with horizon, and what is the implied holding period.

**Required controls (this is where naive backtests fail):**
- **Point-in-time data.** Fundamentals must be as-reported at the time, not as-restated. FMP's free tier does not reliably provide this. Flag as a hard open problem — see section 6.
- **Survivorship bias.** The universe at each historical date must include names that later delisted, went bankrupt or were acquired. A universe built from today's tickers is invalid.
- **Look-ahead bias.** Enforce a reporting lag on fundamentals (a filing dated Q1 was not available on the last day of Q1). Enforce that any signal computed on day *t* uses only data with timestamp ≤ *t*.
- **Transaction costs and slippage.** Model explicitly. Given IBKR Lite fills and the manual workflow, be conservative.
- **Purged and embargoed cross-validation** if any parameter is fit. Standard k-fold leaks across time-adjacent samples.

**Reporting requirement:** every result must be marked to market. No realized-only accounting anywhere in the system — this is the direct lesson from 3.7 and it applies to Z Money's own performance reporting, not just to options.

**Why this first:** it validates work already done, it is the credible quant-research artifact for the CV, and it is the only honest gate for deciding whether Module B is worth building at all.

### Module B — Volatility premium sleeve (conditional, only after A)

If, after A exists, the vol premium is still interesting as a research problem rather than an income promise, the defensible version is narrow:

**Design constraints, all mandatory:**
- **Index-level only.** SPX, XSP or SPY. No single-name option writing. This follows directly from 3.4 — the premium is thin and the tail is fat on individual stocks.
- **Fully cash-collateralised.** No leverage, no margin. The PUT index results assume full collateralisation and the risk profile changes completely without it.
- **Separate sleeve with a hard NAV cap.** Sized as a distinct allocation, not layered on existing equity positions. Must not interact with the existing conviction-scored book.
- **Shadow mode first**, consistent with Phase 1. Log proposals, mark to market daily, place nothing. Run it for a minimum period before considering capital.
- **Proposal-only.** No auto-execution path, same as the existing Order Builder.

**Metrics the sleeve must report (all of them, every period):**
- Premium collected (gross)
- Realized P&L *and* unrealized mark-to-market on every open position
- Net delta of the sleeve, tracked over time — this is the early-warning indicator for the escalation problem in 3.3
- Assignment events and post-assignment cost basis versus market
- Comparison against the honest benchmark: buy-and-hold of the same underlying over the same period, not against zero

**Explicit anti-requirement:** if the sleeve's reporting ever shows realized P&L without a matching unrealized column, the module is wrong and must be fixed before it runs again.

### Module C — Right-tail protection guardrail (build alongside B, or standalone)

A deterministic rule in the Risk Manager, in the same style as the existing hard gates:

**Reject any proposal that writes calls against a position whose conviction score is above a defined threshold.** The rationale is section 4 — call-writing is a bet against your own conviction signal, and doing it on high-conviction momentum names sells the exact outcome the position exists to capture. If the conviction score means anything, this rule follows from it mechanically.

Suggested shape (calibrate against actual score distribution, do not hardcode from this document):
- Conviction above upper threshold → call-writing proposals blocked entirely
- Conviction in middle band → permitted with a minimum strike distance scaled to the position's realized volatility or ATR
- Conviction below lower threshold → the position is an exit candidate anyway; the Risk Manager's existing exit logic takes precedence over any premium consideration

This module is worth building even if Module B is never built, because it encodes a real principle about the interaction between conviction and upside truncation.

---

## 6. Open problems for the build chat to solve or scope

1. **Point-in-time fundamental data.** FMP's free tier does not provide as-reported historical fundamentals with proper reporting lags. Without this, Module A's fundamental components cannot be validated honestly. Options to evaluate: paid FMP tier, Sharadar/Nasdaq Data Link, WRDS/Compustat access, or restricting validation to price-derived components only as a first pass. This is the binding constraint on Module A.

2. **Options data.** Neither FMP free nor yfinance provides reliable historical options chains or implied volatility surfaces. Module B cannot be backtested without one. Candidates to price out: Cboe DataShop, ORATS, Polygon, IBKR historical data. Note the cost may exceed the value of the module — which is itself a legitimate finding.

3. **Universe construction with delisted names.** Needed for survivorship-bias-free validation. Scope the source.

4. **How Module A plugs into the existing pipeline.** Probably as an offline analysis layer rather than a runtime agent — it should be able to run against historical signal outputs, which implies the pipeline needs to persist per-run signal values with timestamps if it does not already. Check whether the current logging captures enough.

5. **Contract granularity.** One options contract is 100 shares. At current prices most names in the universe imply $15k–$30k of notional per contract, which may exceed sensible position sizing for the account. Check whether the account size makes any single-name options work arithmetically possible at all — it may resolve Module B by default.

6. **Options approval level on IBKR** for the account, and whether the required level is available under IBKR Lite for a UK-resident account holder.

7. **UK tax treatment.** Out of scope for the build chat — flagged so it is not accidentally assumed away. Requires professional advice before capital is committed.

---

## 7. Guardrails — things not to build

- **No single-stock wheel.** The premium is thin and the tail is fat (3.4). If this appears in a proposal, it is a regression.
- **No covered calls on high-conviction holdings.** See Module C.
- **No auto-execution**, including of options positions. Phase 1 discipline holds.
- **No realized-only P&L reporting anywhere.** Mark to market or do not report.
- **No leverage on short options.** Full collateralisation only.
- **Do not let the options work displace Module A.** The validation harness is the priority; the vol premium sleeve is optional and may correctly turn out to be not worth building. If the research budget only covers one, it covers Module A.

---

## 8. Framing for the CV / project write-up

The research in this document is itself the kind of work worth describing. The honest framing:

> Evaluated systematic short-volatility strategies as a candidate return source for the system's universe. Established that the variance risk premium supporting index put-writing (Cboe PUT index: comparable return to S&P 500 at ~2/3 the volatility over 32 years) is substantially a correlation risk premium and is materially weaker on single names (implied-realized spread ~2.5% on constituents vs ~3.9% on the index). Concluded that call-writing against a high-momentum concentrated book truncates the right tail the strategy depends on, and encoded this as a deterministic gate in the risk overlay. Prioritised building a signal validation harness — information coefficient, decile spread, hit rate under survivorship and look-ahead controls — over adding the strategy.

Deciding not to build something, with the evidence written down, is a stronger signal of research judgment than building it. Keep the reasoning trail.

---

## 9. Source list

- Bondarenko, O. (2019), *Historical Performance of Put-Writing Strategies*, Cboe — PUT index long-run return, volatility, VIX vs realized spread
- Cboe / Ennis Knupp, *Evaluating the Performance Characteristics of the Cboe S&P 500 PutWrite Index*
- Driessen, Maenhout & Vilkov (2009), *The Price of Correlation Risk: Evidence from Equity Options* — index vs single-stock variance risk premium
- Bakshi & Kapadia (2003), on single-equity variance risk premia
- Carr & Wu (2009), on the noisiness of single-stock variance risk premium estimates
- Jeske, K. (2024), *Why the Wheel Strategy Doesn't Work — Options Series Part 12*, Early Retirement Now — delta escalation, downtrend failure, unrealized-loss accounting
- Spintwig, *SPY Wheel 45-DTE Options Backtest* — return attribution across ten configurations
- Callan Associates and Ibbotson studies of the Cboe BXM BuyWrite Index — bull-market underperformance, bear-market outperformance

---

*Nothing in this document is financial, tax or legal advice. Position sizing, tax treatment and capital commitment decisions sit outside the build scope and require professional input.*
