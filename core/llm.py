"""Anthropic client wrapper — §4's core/llm.py: "Anthropic client, schema
enforcement, token accounting." First LLM integration (§10 step 6), so kept
deliberately small and defensive: schema-enforced structured output with
retry (§5.2: "malformed output is rejected and retried"), plus per-call cost
estimation and a monthly spend guard (§9's budget.monthly_api_cap_usd
"hard-stops LLM calls if exceeded").

The Anthropic client is injected (`AnthropicClient` protocol), never
imported and constructed directly, so nothing in this codebase's test suite
can make a real API call or spend real money — see tests/test_llm.py for the
fake-client pattern. Structured output uses `client.messages.parse(...,
output_format=<pydantic model>)` — see the claude-api skill for why this is
the recommended approach over manual JSON-schema wrangling.

Pricing table verified against the claude-api skill (cached 2026-06-24) for
the two models the spec actually configures (`claude-haiku-4-5` for Stage 2
triage, `claude-sonnet-4-6` for research memos, per config.yaml §9) — not
against whatever the skill's own "always use the newest model" default is.
The spec picked Haiku/Sonnet specifically for cost (§11: "$20-35/month");
this code respects that choice rather than upgrading it. Re-verify prices
before trusting this for a real budget decision if it's been a while since
2026-06-24.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Web search is billed per search on top of tokens ($10 per 1,000 — see the
# Anthropic web search tool docs, "Usage and pricing"); the count comes back
# on `usage.server_tool_use.web_search_requests`.
WEB_SEARCH_COST_PER_REQUEST_USD = 0.01

# (input $ per 1M tokens, output $ per 1M tokens)
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (3.00, 15.00),  # intro pricing (2.00/10.00 through 2026-08-31) not modeled
    "claude-opus-5": (5.00, 25.00),
}


class LLMError(RuntimeError):
    pass


class MonthlyBudgetExceeded(LLMError):
    pass


class UnknownModelPricing(LLMError):
    pass


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int, web_search_requests: int = 0) -> float:
    if model not in PRICING:
        raise UnknownModelPricing(f"no pricing entry for model {model!r} — add it to PRICING before using it")
    input_rate, output_rate = PRICING[model]
    tokens = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
    return tokens + web_search_requests * WEB_SEARCH_COST_PER_REQUEST_USD


# Always the basic web search variant. The dynamic-filtering variant
# (web_search_20260209, Sonnet/Opus 4.6+) was measured on 2026-09-09 against
# the real API for one ticker's news digest: 416 seconds, ~$0.97, and zero
# citation URLs on the returned text — it runs a server-side code-execution
# loop over the results, which is slow, expensive per call, and strips the
# per-block citations this pipeline requires before it will show anything
# as news. The basic variant answered the same question in ~5 seconds with
# citations attached, on Haiku 4.5 and Sonnet 4.6 alike.
WEB_SEARCH_TOOL_TYPE = "web_search_20250305"


def web_search_tool(model: str, max_uses: int) -> dict:
    return {"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": max_uses}


def _web_search_requests(usage: Any) -> int:
    server_tool_use = getattr(usage, "server_tool_use", None)
    return int(getattr(server_tool_use, "web_search_requests", 0) or 0)


class MonthlySpendTracker:
    """§9: "budget.monthly_api_cap_usd: 40 # halts LLM calls if exceeded."
    Cost per call is only known after the call returns (output token count
    isn't predictable), so this is a pre-flight gate (refuse to start a new
    call once already over) plus unconditional post-call recording — not a
    check-then-call budget like DailyCallBudget's FMP guard, where the cost
    of one call (1) is known in advance."""

    def __init__(self, path: str | Path, monthly_cap_usd: float, month_fn: Callable[[], str] | None = None):
        self.path = Path(path)
        self.monthly_cap_usd = monthly_cap_usd
        self._month_fn = month_fn or (lambda: time.strftime("%Y-%m", time.gmtime()))

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))

    def spent_this_month(self) -> float:
        return self._read().get(self._month_fn(), 0.0)

    def remaining_this_month(self) -> float:
        return max(0.0, self.monthly_cap_usd - self.spent_this_month())

    def is_exceeded(self) -> bool:
        return self.spent_this_month() >= self.monthly_cap_usd

    def record(self, cost_usd: float) -> None:
        month = self._month_fn()
        data = self._read()
        data[month] = data.get(month, 0.0) + cost_usd
        self._write(data)


@dataclass
class UsageRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    web_search_requests: int = 0


@dataclass
class StructuredResult:
    parsed: BaseModel
    usage: UsageRecord
    attempts: int


@dataclass
class TextResult:
    """A plain-text (non-schema) call — the shape used with server tools like
    web search, whose results carry citations that structured outputs
    reject. `source_urls` are the citation URLs the model actually leaned on,
    in first-seen order, de-duplicated; empty means nothing was cited."""

    text: str
    source_urls: list[str]
    usage: UsageRecord
    attempts: int


class AnthropicMessages(Protocol):
    def parse(self, *, model: str, max_tokens: int, system: str, messages: list[dict], output_format: type) -> Any: ...

    def create(self, *, model: str, max_tokens: int, system: str, messages: list[dict]) -> Any: ...


class AnthropicClient(Protocol):
    messages: AnthropicMessages


class LLMClient:
    def __init__(self, client: AnthropicClient, budget: MonthlySpendTracker):
        self.client = client
        self.budget = budget

    def call_structured(
        self,
        model: str,
        system: str,
        user_message: str,
        output_model: type[T],
        max_tokens: int = 4096,
        max_retries: int = 2,
    ) -> StructuredResult:
        self._check_budget()

        last_error: Exception | None = None
        for attempt in range(1, max_retries + 2):
            try:
                response = self.client.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                    output_format=output_model,
                )
            except Exception as exc:  # noqa: BLE001 — any failure here is retryable per §5.2
                last_error = exc
                continue

            usage = response.usage
            cost = estimate_cost_usd(model, usage.input_tokens, usage.output_tokens)
            self.budget.record(cost)  # spend happened regardless of whether output was usable

            parsed = getattr(response, "parsed_output", None)
            if parsed is not None:
                return StructuredResult(
                    parsed=parsed,
                    usage=UsageRecord(
                        model=model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=cost
                    ),
                    attempts=attempt,
                )
            last_error = LLMError(f"{model} returned no parsed_output on attempt {attempt}")

        raise last_error or LLMError("structured call failed with no output and no captured error")

    def _check_budget(self) -> None:
        if self.budget.is_exceeded():
            raise MonthlyBudgetExceeded(
                f"monthly API budget exhausted: ${self.budget.spent_this_month():.2f}"
                f"/${self.budget.monthly_cap_usd:.2f} — no further LLM calls this month"
            )

    def call_text(
        self,
        model: str,
        system: str,
        user_message: str,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        max_retries: int = 2,
        max_continuations: int = 3,
    ) -> TextResult:
        """Plain-text call, optionally with server tools (web search). Not
        schema-enforced on purpose: web search always attaches citations to
        the text blocks it grounds, and structured outputs reject citations —
        so grounded research is a text call whose output is then fed into a
        separate structured memo call (see agents/research.py).

        A `pause_turn` stop (the server-side search loop hit its iteration
        cap) is continued by re-sending the assistant content unchanged, per
        the web search docs — the encrypted search results in it must go
        back byte-for-byte."""
        self._check_budget()

        last_error: Exception | None = None
        for attempt in range(1, max_retries + 2):
            messages: list[dict] = [{"role": "user", "content": user_message}]
            total_in = total_out = total_searches = 0
            response = None
            try:
                for _ in range(max_continuations + 1):
                    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
                    if tools:
                        kwargs["tools"] = tools
                    response = self.client.messages.create(**kwargs)
                    usage = response.usage
                    total_in += usage.input_tokens
                    total_out += usage.output_tokens
                    total_searches += _web_search_requests(usage)
                    if getattr(response, "stop_reason", None) != "pause_turn":
                        break
                    messages = [*messages, {"role": "assistant", "content": response.content}]
            except Exception as exc:  # noqa: BLE001 — retryable, same policy as call_structured
                last_error = exc
                if total_in or total_out or total_searches:
                    self.budget.record(estimate_cost_usd(model, total_in, total_out, total_searches))
                continue

            cost = estimate_cost_usd(model, total_in, total_out, total_searches)
            self.budget.record(cost)

            text_parts: list[str] = []
            urls: list[str] = []
            for block in getattr(response, "content", []) or []:
                if getattr(block, "type", None) != "text":
                    continue
                text_parts.append(getattr(block, "text", "") or "")
                for citation in getattr(block, "citations", None) or []:
                    url = getattr(citation, "url", None)
                    if url and url not in urls:
                        urls.append(url)
            text = "".join(text_parts)
            if text.strip():
                return TextResult(
                    text=text,
                    source_urls=urls,
                    usage=UsageRecord(
                        model=model, input_tokens=total_in, output_tokens=total_out, cost_usd=cost,
                        web_search_requests=total_searches,
                    ),
                    attempts=attempt,
                )
            last_error = LLMError(f"{model} returned no text blocks on attempt {attempt}")

        raise last_error or LLMError("text call failed with no output and no captured error")
