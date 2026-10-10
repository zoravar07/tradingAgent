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

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, model_validator

from core.cache import FileCache
from core.config import ResearchConfig
from core.llm import LLMClient, UsageRecord, web_search_tool

# The digest call is told to emit exactly this when its searches turn up
# nothing dated and sourced — a machine-checkable "no news" rather than
# prose that could be mistaken for a finding.
NO_MATERIAL_NEWS_MARKER = "NO_MATERIAL_NEWS"

NEWS_DIGEST_SYSTEM_PROMPT = f"""You are a news researcher for an equity analyst. Use the web_search tool to find what has actually been reported about one company in the last N days: earnings and guidance, filings (8-K, 10-Q, 10-K, 13D), contracts, management changes, regulatory actions, product events, and sector news that hits the name directly.

Hard rules:
- Report only what you found via search in this session. Do not use prior knowledge for events, dates, or figures — your training data is stale and unsourced facts are worse than none.
- Every item must be dated (YYYY-MM-DD) and drawn from a cited source. One line per item: date, what happened, why it matters to the investment case.
- If your searches return nothing dated within the window that could matter to the investment case, respond with exactly {NO_MATERIAL_NEWS_MARKER} and nothing else.
- No preamble, no narration of your searching, no summary of the company, no opinions about the stock. Facts with dates and sources only.
- Write each item so a smart beginner can follow it: plain words, and explain any technical term or abbreviation in brackets the first time it appears (e.g. "guidance (the company's own forecast)", "8-K (a filing companies must make when something important happens)")."""

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

You do not decide whether to buy or sell, how large a position should be, where a stop should sit, or what the final conviction score is. You analyze the evidence; something else decides.

Writing style — this is read by a smart beginner, not an analyst:
- Plain English, short sentences. Say what a number means for the investment, not just the number.
- The first time you use a technical term or abbreviation, explain it in a few words in brackets right there, e.g. "free cash flow (the cash left over after running the business)", "P/E of 40 (the share price is 40 times last year's profit per share)". After that, use the term freely.
- No unexplained abbreviations: no FCF, TAM, SBC, ROIC, DMA, RS, YoY, capex without the bracketed meaning on first use.
- Prefer "the company", "its customers", "its profit" over sector shorthand. Say "compared with the S&P 500" rather than "vs SPY".
- Keep the analysis as rigorous as before; only the words get simpler."""


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
class NewsDigest:
    """The grounded-news result for one ticker. `found_news` is the only
    thing the briefing may show: it requires at least one citation URL, so
    an unsourced claim — however plausible — is never surfaced as news."""

    ticker: str
    text: str = ""
    source_urls: list[str] = field(default_factory=list)
    usage: UsageRecord | None = None
    error: str | None = None
    cached: bool = False  # served from the news cache, no call made

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def found_news(self) -> bool:
        if not self.ok or not self.source_urls:
            return False
        return NO_MATERIAL_NEWS_MARKER not in self.text


def _digest_cache_key(ticker: str, config: ResearchConfig) -> str:
    return f"news:{ticker.upper()}:{config.news_lookback_days}d"


def run_news_digest(
    llm: LLMClient, ticker: str, config: ResearchConfig, cache: FileCache | None = None
) -> NewsDigest:
    """One web-search-grounded text call per researched name, reused from
    `cache` for `config.news_cache_hours` so the same name isn't searched
    again the next night. A failure surfaces as `error`, never raises — a
    missing digest degrades the memo to "no recent news retrieved", it
    doesn't kill the run. Only successful digests are cached."""
    key = _digest_cache_key(ticker, config)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return NewsDigest(ticker=ticker, text=hit["text"], source_urls=list(hit["source_urls"]), cached=True)
    user_message = (
        f"Company ticker: {ticker}\nWindow: the last {config.news_lookback_days} days, ending today.\n"
        f"Search for material developments in that window and list them as instructed. "
        f"If there are none, reply {NO_MATERIAL_NEWS_MARKER}."
    )
    tools = [web_search_tool(config.digest_model, config.web_search_max_uses)]
    try:
        result = llm.call_text(
            model=config.digest_model, system=NEWS_DIGEST_SYSTEM_PROMPT, user_message=user_message, tools=tools, max_tokens=1200
        )
    except Exception as exc:  # noqa: BLE001 — one bad digest must not kill the run
        return NewsDigest(ticker=ticker, error=str(exc))
    digest = NewsDigest(ticker=ticker, text=result.text.strip(), source_urls=result.source_urls, usage=result.usage)
    if cache is not None:
        cache.set(key, {"text": digest.text, "source_urls": digest.source_urls}, config.news_cache_hours * 3600)
    return digest


@dataclass
class ResearchContext:
    ticker: str
    context_text: str  # pre-assembled by the caller: fundamentals, technicals, earnings, ownership
    news_digest: NewsDigest | None = None  # grounded via web search (run_news_digest); None = not retrieved


@dataclass
class ResearchResult:
    ticker: str
    memo: ResearchMemo | None
    usage: UsageRecord | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.memo is not None


def _news_section(context: ResearchContext) -> str:
    """The only recent-events evidence the memo is allowed to use. The system
    prompt already forbids inventing data; this makes the absence of news an
    explicit input rather than a gap the model might fill from memory."""
    digest = context.news_digest
    if digest is not None and digest.found_news:
        sources = "\n".join(f"- {url}" for url in digest.source_urls)
        return (
            "Recent news (retrieved by web search, dated, sourced — the ONLY evidence to use for recent events; "
            "do not add events from memory):\n"
            f"{digest.text}\nSources:\n{sources}"
        )
    return (
        "Recent news: no recent news was retrieved for this name (either none was found in the lookback "
        "window or retrieval failed). Do not supply recent events from memory; if you have no other "
        "evidence for news_sentiment, mark it data_available=false."
    )


def run_research(llm: LLMClient, context: ResearchContext, config: ResearchConfig, max_tokens: int = 4096) -> ResearchResult:
    """One memo call. A failure (budget exhausted, malformed output after
    retries, API error) doesn't raise — it surfaces as `error` so a batch run
    can skip one bad ticker without losing the rest of the briefing."""
    user_message = (
        f"Ticker: {context.ticker}\n\n{context.context_text}\n\n{_news_section(context)}\n\n"
        "Produce the investment memo now."
    )
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
