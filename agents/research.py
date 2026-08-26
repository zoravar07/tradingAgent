"""Research Agent — §10 step 7: Sonnet, one call per candidate, schema-
enforced JSON (§5.2). Produces an investment memo: subscores across the
factors an LLM can reasonably judge from research, plus consensus/variant
views, a bear case with an estimated downside %, dated catalysts, key risks,
and a thesis summary.

§5.2, verbatim, is the boundary this module exists inside: "The LLM does not
output position sizes, stop levels, buy/sell decisions, or the final
conviction score. It analyses. It does not decide." Nothing here decides
anything — core/scoring.py rolls the subscores into a conviction number
afterward, core/risk_rules.py decides what (if anything) happens next.

Two of §5.2's twelve named subscores are deliberately NOT part of this
module's schema or its LLM call:

* `portfolio_fit` — "correlation to what you already own... penalty applied
  after roll-up." That's a computable quantity (return correlation,
  sector/cluster overlap against the current book) — not something to ask an
  LLM to eyeball from a memo written about one ticker in isolation, with no
  view of the rest of the portfolio. scoring.py already treats it as a
  separate penalty stage; something else needs to compute it and merge it
  into the subscores dict before compute_conviction runs.
* `discord_signal` — "optional... see §8.3", sourced from
  sources/discord_signals.py (a different plugin, weight 0 by default), not
  from a research memo.

Gathering the input context (FMP fundamentals, technical snapshot, earnings,
ownership, news) is the orchestrator's job (§10 step 9, not yet built) — this
module takes an already-assembled `ResearchContext.context_text` and doesn't
fetch anything itself.

**Null subscores, added after a real finding**: a live run showed
`ownership_flow` (and, to a lesser extent, `catalyst_path` and
`downside_asymmetry`) clustering near 40 across every researched name
regardless of company quality — correlated with 13F/insider data being
frequently unavailable. The root cause wasn't those specific factors; it was
that a subscore had no way to say "I have no evidence here" — a plain 0-100
float always produces *some* number, and an LLM asked to score without real
data defaults to a hedged, uninformative middle rather than an honest
absence. That number then gets weighted into the roll-up as if it were a
finding, quietly dragging conviction toward the middle for every name with a
data gap, not just the ones that genuinely warrant a neutral score.

Each subscore is now a `Subscore` (value + an explicit `data_available`
flag) instead of a bare float. When `data_available` is False, `subscores()`
excludes that factor entirely — and core/scoring.py's `compute_conviction`
already renormalizes weights over whatever's present (§8.3: "weights
auto-normalise to 1.0 regardless of what's enabled"), so a missing factor
contributes nothing rather than a fabricated middle. This is deliberately
the general fix, not a 13F/insider-specific one — it's cheap (one schema
change) and it corrects the same failure mode for any factor, on any
ticker, any time the evidence just isn't there.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

from core.config import ResearchConfig
from core.llm import LLMClient, UsageRecord

# Matches §5.2's table order, minus portfolio_fit and discord_signal (see
# module docstring). scoring.py's compute_conviction only uses whatever
# names appear in both a subscores dict and the configured weights dict, so
# this list exists for documentation/iteration, not as an enforced contract.
RESEARCH_SUBSCORE_NAMES = [
    "business_quality",
    "financial_health",
    "whats_priced_in",
    "variant_perception",
    "earnings_quality",
    "catalyst_path",
    "downside_asymmetry",
    "ownership_flow",
    "analyst_signals",
    "news_sentiment",
    "technical_momentum",
]

RESEARCH_SYSTEM_PROMPT = """You are an equity research analyst producing a structured investment memo for one candidate at a time. Score each factor 0-100 based only on the evidence given to you in the user message — do not invent data you weren't given.

Each factor is scored as an object: {"value": <0-100 or null>, "data_available": <true or false>}. If the user message gives you no real evidence to judge a factor on — not "the evidence is mixed" or "this looks average", but genuinely nothing to go on (e.g. no 13F/insider data was provided, no analyst coverage exists) — set data_available to false and leave value null. Do NOT default to a middling number like 40-60 when you have no evidence; that number gets treated as a real finding downstream and it isn't one. Only set data_available to true when you're scoring actual evidence, even evidence that itself points to a middling picture.

Factor definitions (§5.2 of the house research spec):
- business_quality: ROIC and its trend. Gross margin durability — pricing power or commodity exposure? Reinvestment runway.
- financial_health: growth trend, FCF conversion, balance sheet strength, debt maturities.
- whats_priced_in: reverse-DCF — what growth rate does the current price require? Is that plausible or heroic? A great company at a price that already assumes greatness is not automatically a good trade.
- variant_perception: state the consensus view explicitly first, then where this thesis differs from consensus and why it might be right. A thesis that just restates consensus is exposure, not edge.
- earnings_quality: beat/miss magnitude, guidance direction, post-earnings drift, accruals vs. cash earnings.
- catalyst_path: what specifically converts a mispriced security into a correctly priced one, and roughly when — dated where the evidence supports it. A thesis with no catalyst is a hope with a ticker.
- downside_asymmetry: score the MAGNITUDE of the bear case, not its probability. What breaks, and how much is lost if it does?
- ownership_flow: 13F trend across multiple quarters (a single quarter is noise), Form 4 insider activity weighted by seniority and whether it's a real buy vs. an option exercise.
- analyst_signals: rating changes, price target revisions, and the DIRECTION of estimate revisions.
- news_sentiment: volume, tone, and material events — including sector news that hits this name indirectly.
- technical_momentum: price vs. moving averages, relative strength, current volatility regime.

Also produce:
- consensus_view: the market's current view of this name, stated plainly.
- variant_view: where and why your view differs from consensus (can restate that it doesn't differ, if that's honestly the case).
- bear_case: a specific thesis for what goes wrong, with an estimated downside percentage — magnitude, not a probability estimate.
- catalysts: dated where you can date them, undated where you honestly can't.
- key_risks: concrete, specific risks — not generic boilerplate ("market risk", "execution risk" alone are not acceptable).
- thesis_summary: 2-3 sentences a reader acts on.

You do not decide whether to buy or sell, how large a position should be, where a stop should sit, or what the final conviction score is. You analyze the evidence; something else decides."""


class Catalyst(BaseModel):
    description: str
    expected_date: str | None = None  # free text — not every catalyst has an exact date


class BearCase(BaseModel):
    thesis: str
    estimated_downside_pct: float = Field(ge=0, le=100)


class Subscore(BaseModel):
    """One factor's judgment. `data_available=False` means the memo found no
    real evidence to score this factor on — `value` must then be null, not a
    hedged middling number. See module docstring for why this exists."""

    value: float | None = Field(default=None, ge=0, le=100)
    data_available: bool

    @model_validator(mode="after")
    def _value_matches_availability(self) -> "Subscore":
        if self.data_available and self.value is None:
            raise ValueError("data_available=True requires a non-null value")
        if not self.data_available and self.value is not None:
            raise ValueError("data_available=False must leave value null, not a number")
        return self


class ResearchMemo(BaseModel):
    business_quality: Subscore
    financial_health: Subscore
    whats_priced_in: Subscore
    variant_perception: Subscore
    earnings_quality: Subscore
    catalyst_path: Subscore
    downside_asymmetry: Subscore
    ownership_flow: Subscore
    analyst_signals: Subscore
    news_sentiment: Subscore
    technical_momentum: Subscore

    consensus_view: str
    variant_view: str
    bear_case: BearCase
    catalysts: list[Catalyst]
    key_risks: list[str]
    thesis_summary: str

    def subscores(self) -> dict[str, float]:
        """§6's research_outputs.subscores_json — everything compute_conviction
        needs, minus portfolio_fit/discord_signal which are merged in by the
        caller from elsewhere (see module docstring). Factors marked
        data_available=False are excluded entirely, not passed through as
        some fallback number — core/scoring.py's compute_conviction
        renormalizes weights over whatever's left."""
        result: dict[str, float] = {}
        for name in RESEARCH_SUBSCORE_NAMES:
            sub: Subscore = getattr(self, name)
            if sub.data_available and sub.value is not None:
                result[name] = sub.value
        return result

    def unavailable_factors(self) -> list[str]:
        """Factors this memo explicitly found no evidence for — a research-
        quality signal worth surfacing (e.g. in the UI), not just an internal
        detail of the conviction roll-up."""
        return [name for name in RESEARCH_SUBSCORE_NAMES if not getattr(self, name).data_available]


@dataclass
class ResearchContext:
    ticker: str
    context_text: str  # pre-assembled by the caller: fundamentals, technicals, earnings, ownership, news


@dataclass
class ResearchResult:
    ticker: str
    memo: ResearchMemo | None
    usage: UsageRecord | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.memo is not None


def run_research(llm: LLMClient, context: ResearchContext, config: ResearchConfig, max_tokens: int = 4096) -> ResearchResult:
    """One memo call. A failure (budget exhausted, malformed output after
    retries, API error) doesn't raise — it surfaces as `error` so a batch run
    can skip one bad ticker without losing the rest of the briefing."""
    user_message = f"Ticker: {context.ticker}\n\n{context.context_text}\n\nProduce the investment memo now."
    try:
        result = llm.call_structured(
            model=config.model,
            system=RESEARCH_SYSTEM_PROMPT,
            user_message=user_message,
            output_model=ResearchMemo,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 — one bad memo must not kill the run
        return ResearchResult(ticker=context.ticker, memo=None, error=str(exc))

    return ResearchResult(ticker=context.ticker, memo=result.parsed, usage=result.usage)


def run_research_batch(
    llm: LLMClient, contexts: list[ResearchContext], config: ResearchConfig
) -> list[ResearchResult]:
    """§5's pipeline caps this at `max_candidates_per_run` (§9: 15) — Stage 2
    is what's responsible for handing this function no more than that many
    contexts; this function itself doesn't second-guess the input size."""
    return [run_research(llm, ctx, config) for ctx in contexts]
