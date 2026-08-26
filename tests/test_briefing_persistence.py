import datetime as dt
import json

from agents.order_builder import OrderProposal
from core.briefing import ActionItem, BookEntry, PortfolioHealth, UnpricedPosition, UnresearchedHolding, assemble_blocked_briefing, assemble_briefing
from core.briefing_persistence import deserialize_briefing, serialize_briefing
from core.portfolio import DriftStatus
from core.risk_rules import KillSwitchStatus

NOW = dt.datetime(2026, 8, 25, 22, 0, 0)


def order(ticker="AMD", conviction=54.0):
    return OrderProposal(
        ticker=ticker, action="SELL", quantity=1, order_type="LIMIT", limit_price=476.78,
        estimated_cost_usd=476.78, weight_pct=13.7, conviction=conviction, trigger_type="PROFIT_BAND", is_trim=True,
    )


class TestSerializeRoundTrip:
    def test_normal_briefing_round_trips(self):
        briefing = assemble_briefing(
            generated_at=NOW,
            actions_today=[ActionItem(order=order(), headline="Trim 50%", thesis_summary="thesis", bear_case="bear")],
            watching=[],
            overnight_changes=[],
            book=[BookEntry(ticker="AMD", qty=3.5, value_usd=1681.0, weight_pct=13.7, unrealized_pnl_pct=132.5, conviction_now=54.0, has_exit_trigger=True)],
            portfolio_health=PortfolioHealth(cash_pct=0.3, drawdown_from_peak_pct=0.0, kill_switch=KillSwitchStatus(triggered=False)),
            drift=DriftStatus(stale=True, last_import_at=None, days_since_import=None, threshold_days=7),
            unresearched_holdings=[UnresearchedHolding(ticker="VGT", reason="Stage 1 data fetch failed: no fundamentals")],
        )

        raw = serialize_briefing(briefing)
        result = deserialize_briefing(raw)

        assert result["generated_at"] == "2026-08-25T22:00:00"
        assert result["actions_today"][0]["order"]["ticker"] == "AMD"
        assert result["actions_today"][0]["headline"] == "Trim 50%"
        assert result["book"][0]["ticker"] == "AMD"
        assert result["book"][0]["value_usd"] == 1681.0
        assert result["portfolio_health"]["kill_switch"]["triggered"] is False
        assert result["drift_warning"]["stale"] is True
        assert result["unresearched_holdings"][0]["ticker"] == "VGT"
        assert result["blocked"] is None

    def test_blocked_briefing_round_trips(self):
        briefing = assemble_blocked_briefing(
            NOW, [UnpricedPosition(ticker="CEG", error="402 Restricted Endpoint")], tolerance=0, total_held=16
        )
        raw = serialize_briefing(briefing)
        result = deserialize_briefing(raw)

        assert result["blocked"]["unpriced_positions"][0]["ticker"] == "CEG"
        assert "16" in result["blocked"]["reason"]
        assert result["actions_today"] == []

    def test_output_is_valid_json(self):
        briefing = assemble_briefing(
            generated_at=NOW, actions_today=[], watching=[], overnight_changes=[], book=[],
            portfolio_health=PortfolioHealth(), drift=None,
        )
        raw = serialize_briefing(briefing)
        json.loads(raw)  # must not raise

    def test_empty_briefing_round_trips(self):
        briefing = assemble_briefing(
            generated_at=NOW, actions_today=[], watching=[], overnight_changes=[], book=[],
            portfolio_health=PortfolioHealth(), drift=None,
        )
        result = deserialize_briefing(serialize_briefing(briefing))
        assert result["actions_today"] == []
        assert result["book"] == []
        assert result["unresearched_holdings"] == []
