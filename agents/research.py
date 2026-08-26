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
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

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


class ResearchMemo(BaseModel):
    business_quality: float = Field(ge=0, le=100)
    financial_health: float = Field(ge=0, le=100)
    whats_priced_in: float = Field(ge=0, le=100)
    variant_perception: float = Field(ge=0, le=100)
    earnings_quality: float = Field(ge=0, le=100)
    catalyst_path: float = Field(ge=0, le=100)
    downside_asymmetry: float = Field(ge=0, le=100)
    ownership_flow: float = Field(ge=0, le=100)
    analyst_signals: float = Field(ge=0, le=100)
    news_sentiment: float = Field(ge=0, le=100)
    technical_momentum: float = Field(ge=0, le=100)

    consensus_view: str
    variant_view: str
    bear_case: BearCase
    catalysts: list[Catalyst]
    key_risks: list[str]
    thesis_summary: str

    def subscores(self) -> dict[str, float]:
        """§6's research_outputs.subscores_json — everything compute_conviction
        needs, minus portfolio_fit/discord_signal which are merged in by the
        caller from elsewhere (see module docstring)."""
        return {name: getattr(self, name) for name in RESEARCH_SUBSCORE_NAMES}


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
