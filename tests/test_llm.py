"""LLMClient tests — the Anthropic client is fake throughout. No test in this
file may call a real Anthropic API or spend real budget."""

import json
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from core.llm import (
    LLMClient,
    LLMError,
    MonthlyBudgetExceeded,
    MonthlySpendTracker,
    UnknownModelPricing,
    estimate_cost_usd,
    web_search_tool,
)


class Verdict(BaseModel):
    verdict: str
    material: bool


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int


class FakeResponse:
    def __init__(self, parsed_output=None, input_tokens=100, output_tokens=20):
        self.parsed_output = parsed_output
        self.usage = FakeUsage(input_tokens, output_tokens)


@dataclass
class FakeServerToolUse:
    web_search_requests: int = 0


@dataclass
class FakeUsageWithSearch:
    input_tokens: int
    output_tokens: int
    server_tool_use: FakeServerToolUse | None = None


@dataclass
class FakeCitation:
    url: str
    title: str = ""
    type: str = "web_search_result_location"


class FakeTextBlock:
    def __init__(self, text: str, citations: list | None = None):
        self.type = "text"
        self.text = text
        self.citations = citations


class FakeServerToolUseBlock:
    """A server_tool_use block — present in real web-search responses and
    must be ignored (not read as text) by the client."""

    type = "server_tool_use"


class FakeTextResponse:
    def __init__(self, blocks: list, stop_reason: str = "end_turn", input_tokens=100, output_tokens=20, web_search_requests=0):
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = FakeUsageWithSearch(input_tokens, output_tokens, FakeServerToolUse(web_search_requests))


class FakeMessages:
    """Serves a scripted sequence of responses/exceptions, one per .parse()
    or .create() call, in order — a test scripting both kinds lists them in
    the order the code under test issues them."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    def _next(self, kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def parse(self, **kwargs):
        return self._next({**kwargs, "_method": "parse"})

    def create(self, **kwargs):
        return self._next({**kwargs, "_method": "create"})


class FakeClient:
    def __init__(self, script: list):
        self.messages = FakeMessages(script)


def make_tracker(tmp_path, cap=40.0, month="2026-08"):
    return MonthlySpendTracker(tmp_path / "spend.json", monthly_cap_usd=cap, month_fn=lambda: month)


class TestEstimateCost:
    def test_known_model(self):
        cost = estimate_cost_usd("claude-haiku-4-5", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(1.00 + 5.00)

    def test_unknown_model_raises(self):
        with pytest.raises(UnknownModelPricing):
            estimate_cost_usd("some-made-up-model", 100, 100)


class TestMonthlySpendTracker:
    def test_starts_at_zero(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.spent_this_month() == 0.0
        assert tracker.remaining_this_month() == 40.0
        assert tracker.is_exceeded() is False

    def test_record_accumulates(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record(10.0)
        tracker.record(5.0)
        assert tracker.spent_this_month() == 15.0
        assert tracker.remaining_this_month() == 25.0

    def test_exceeded_at_or_above_cap(self, tmp_path):
        tracker = make_tracker(tmp_path, cap=10.0)
        tracker.record(10.0)
        assert tracker.is_exceeded() is True

    def test_resets_on_new_month(self, tmp_path):
        month = {"value": "2026-08"}
        tracker = MonthlySpendTracker(tmp_path / "spend.json", monthly_cap_usd=10.0, month_fn=lambda: month["value"])
        tracker.record(10.0)
        assert tracker.is_exceeded() is True
        month["value"] = "2026-09"
        assert tracker.is_exceeded() is False
        assert tracker.spent_this_month() == 0.0

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "spend.json"
        MonthlySpendTracker(path, 40.0, month_fn=lambda: "2026-08").record(7.5)
        second = MonthlySpendTracker(path, 40.0, month_fn=lambda: "2026-08")
        assert second.spent_this_month() == 7.5

    def test_recording_in_a_new_month_does_not_erase_prior_months(self, tmp_path):
        path = tmp_path / "spend.json"
        month = {"value": "2026-08"}
        tracker = MonthlySpendTracker(path, 40.0, month_fn=lambda: month["value"])
        tracker.record(12.0)
        month["value"] = "2026-09"
        tracker.record(3.0)
        raw = json.loads(path.read_text())
        assert raw == {"2026-08": 12.0, "2026-09": 3.0}


class TestLLMClientCallStructured:
    def test_successful_call_returns_parsed_and_usage(self, tmp_path):
        client = FakeClient([FakeResponse(parsed_output=Verdict(verdict="looks fine", material=False))])
        llm = LLMClient(client, make_tracker(tmp_path))

        result = llm.call_structured(
            model="claude-haiku-4-5", system="sys", user_message="msg", output_model=Verdict
        )

        assert result.parsed.material is False
        assert result.attempts == 1
        assert result.usage.model == "claude-haiku-4-5"
        assert result.usage.cost_usd > 0

    def test_records_cost_against_budget(self, tmp_path):
        client = FakeClient([FakeResponse(parsed_output=Verdict(verdict="x", material=True))])
        tracker = make_tracker(tmp_path)
        llm = LLMClient(client, tracker)

        llm.call_structured(model="claude-haiku-4-5", system="s", user_message="m", output_model=Verdict)

        assert tracker.spent_this_month() > 0

    def test_retries_on_exception_then_succeeds(self, tmp_path):
        client = FakeClient([RuntimeError("boom"), FakeResponse(parsed_output=Verdict(verdict="ok", material=False))])
        llm = LLMClient(client, make_tracker(tmp_path))

        result = llm.call_structured(
            model="claude-haiku-4-5", system="s", user_message="m", output_model=Verdict, max_retries=2
        )

        assert result.attempts == 2

    def test_retries_on_missing_parsed_output(self, tmp_path):
        client = FakeClient([FakeResponse(parsed_output=None), FakeResponse(parsed_output=Verdict(verdict="ok", material=True))])
        llm = LLMClient(client, make_tracker(tmp_path))

        result = llm.call_structured(
            model="claude-haiku-4-5", system="s", user_message="m", output_model=Verdict, max_retries=2
        )

        assert result.parsed.material is True
        assert result.attempts == 2

    def test_exhausts_retries_and_raises(self, tmp_path):
        client = FakeClient([RuntimeError("1"), RuntimeError("2"), RuntimeError("3")])
        llm = LLMClient(client, make_tracker(tmp_path))

        with pytest.raises(RuntimeError):
            llm.call_structured(model="claude-haiku-4-5", system="s", user_message="m", output_model=Verdict, max_retries=2)

    def test_refuses_to_call_when_budget_already_exceeded(self, tmp_path):
        tracker = make_tracker(tmp_path, cap=1.0)
        tracker.record(1.0)
        client = FakeClient([FakeResponse(parsed_output=Verdict(verdict="ok", material=False))])
        llm = LLMClient(client, tracker)

        with pytest.raises(MonthlyBudgetExceeded):
            llm.call_structured(model="claude-haiku-4-5", system="s", user_message="m", output_model=Verdict)
        assert len(client.messages.calls) == 0  # never even attempted the call

    def test_failed_attempt_that_still_returned_usage_is_billed(self, tmp_path):
        # a response with no parsed_output still consumed real tokens
        client = FakeClient(
            [FakeResponse(parsed_output=None, input_tokens=500, output_tokens=50), FakeResponse(parsed_output=Verdict(verdict="ok", material=False))]
        )
        tracker = make_tracker(tmp_path)
        llm = LLMClient(client, tracker)

        llm.call_structured(model="claude-haiku-4-5", system="s", user_message="m", output_model=Verdict, max_retries=1)

        assert tracker.spent_this_month() > 0


class TestEstimateCostWebSearch:
    def test_web_searches_are_billed_at_one_cent_each(self):
        base = estimate_cost_usd("claude-sonnet-4-6", 1000, 100)
        with_search = estimate_cost_usd("claude-sonnet-4-6", 1000, 100, web_search_requests=3)
        assert with_search == pytest.approx(base + 0.03)


WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}


class TestLLMClientCallText:
    def test_concatenates_text_blocks_and_collects_citation_urls(self, tmp_path):
        response = FakeTextResponse(
            [
                FakeServerToolUseBlock(),
                FakeTextBlock("2026-09-08: AMD raised guidance. ", [FakeCitation("https://example.com/a")]),
                FakeTextBlock("Analysts reacted. ", [FakeCitation("https://example.com/b"), FakeCitation("https://example.com/a")]),
            ],
            web_search_requests=2,
        )
        llm = LLMClient(FakeClient([response]), make_tracker(tmp_path))

        result = llm.call_text(model="claude-sonnet-4-6", system="s", user_message="m", tools=[WEB_SEARCH_TOOL])

        assert result.text == "2026-09-08: AMD raised guidance. Analysts reacted. "
        assert result.source_urls == ["https://example.com/a", "https://example.com/b"]  # ordered, de-duplicated
        assert result.usage.web_search_requests == 2
        assert result.usage.cost_usd == pytest.approx(estimate_cost_usd("claude-sonnet-4-6", 100, 20, web_search_requests=2))

    def test_passes_tools_through_and_uses_create_not_parse(self, tmp_path):
        client = FakeClient([FakeTextResponse([FakeTextBlock("hi")])])
        llm = LLMClient(client, make_tracker(tmp_path))
        llm.call_text(model="claude-sonnet-4-6", system="s", user_message="m", tools=[WEB_SEARCH_TOOL])
        call = client.messages.calls[0]
        assert call["_method"] == "create"
        assert call["tools"] == [WEB_SEARCH_TOOL]
        assert "output_format" not in call  # plain text: structured outputs and web-search citations don't mix

    def test_records_search_cost_against_budget(self, tmp_path):
        tracker = make_tracker(tmp_path)
        llm = LLMClient(FakeClient([FakeTextResponse([FakeTextBlock("x")], web_search_requests=4)]), tracker)
        llm.call_text(model="claude-sonnet-4-6", system="s", user_message="m", tools=[WEB_SEARCH_TOOL])
        assert tracker.spent_this_month() >= 0.04

    def test_continues_after_pause_turn_by_resending_assistant_content(self, tmp_path):
        first = FakeTextResponse([FakeServerToolUseBlock()], stop_reason="pause_turn", web_search_requests=1)
        second = FakeTextResponse([FakeTextBlock("done", [FakeCitation("https://example.com/z")])], web_search_requests=1)
        client = FakeClient([first, second])
        llm = LLMClient(client, make_tracker(tmp_path))

        result = llm.call_text(model="claude-sonnet-4-6", system="s", user_message="m", tools=[WEB_SEARCH_TOOL])

        assert result.text == "done"
        assert result.usage.web_search_requests == 2  # both legs billed
        second_call = client.messages.calls[1]
        assert second_call["messages"][1]["role"] == "assistant"
        assert second_call["messages"][1]["content"] is first.content  # sent back unchanged, encrypted results intact

    def test_no_text_blocks_is_an_error_after_retries(self, tmp_path):
        client = FakeClient([FakeTextResponse([FakeServerToolUseBlock()]), FakeTextResponse([FakeServerToolUseBlock()])])
        llm = LLMClient(client, make_tracker(tmp_path))
        with pytest.raises(LLMError):
            llm.call_text(model="claude-sonnet-4-6", system="s", user_message="m", tools=[WEB_SEARCH_TOOL], max_retries=1)

    def test_refuses_to_call_when_budget_already_exceeded(self, tmp_path):
        tracker = make_tracker(tmp_path, cap=1.0)
        tracker.record(1.0)
        client = FakeClient([FakeTextResponse([FakeTextBlock("x")])])
        with pytest.raises(MonthlyBudgetExceeded):
            LLMClient(client, tracker).call_text(model="claude-sonnet-4-6", system="s", user_message="m")
        assert client.messages.calls == []


class TestWebSearchToolForModel:
    def test_basic_variant_for_every_model(self):
        # Measured live 2026-09-09: the dynamic-filtering variant took 416s
        # and ~$0.97 for one digest and returned no citation URLs. Basic
        # answered in ~5s with citations. See core/llm.py.
        for model in ("claude-sonnet-4-6", "claude-haiku-4-5", "some-future-model"):
            assert web_search_tool(model, max_uses=3) == {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
