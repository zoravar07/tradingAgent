"""LLMClient tests — the Anthropic client is fake throughout. No test in this
file may call a real Anthropic API or spend real budget."""

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


class FakeMessages:
    """Serves a scripted sequence of responses/exceptions, one per .parse() call."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


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
