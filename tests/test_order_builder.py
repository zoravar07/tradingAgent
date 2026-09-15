import pytest

from agents.order_builder import build_buy_order, build_exit_order
from core.config import OrderBuilderConfig
from core.risk_rules import ExitTrigger, HeldPositionEvaluation, SizingResult

CONFIG = OrderBuilderConfig()


def sizing(**overrides):
    base = dict(approved=True, position_pct=3.5, position_usd=427.5, reasons=[])
    base.update(overrides)
    return SizingResult(**base)


class TestBuildBuyOrder:
    def test_builds_whole_share_limit_order_above_current_price(self):
        order = build_buy_order("ANET", conviction=74, sizing=sizing(position_usd=427.5), current_price=142.50, config=CONFIG)
        assert order.action == "BUY"
        assert order.quantity == 3  # floor(427.5 / 142.50) = 3
        assert order.limit_price == pytest.approx(142.50 * 1.005, abs=0.01)
        assert order.limit_price > 142.50  # buy limit set above market to be marketable
        assert order.trigger_type is None
        assert order.is_trim is False

    def test_estimated_cost_matches_quantity_times_limit(self):
        order = build_buy_order("ANET", 74, sizing(position_usd=427.5), 142.50, CONFIG)
        assert order.estimated_cost_usd == pytest.approx(order.quantity * order.limit_price, abs=0.01)

    def test_none_when_sizing_not_approved(self):
        order = build_buy_order("BAD", 20, sizing(approved=False, position_usd=0), 50.0, CONFIG)
        assert order is None

    def test_none_when_cannot_afford_one_share(self):
        order = build_buy_order("BRK.A", 90, sizing(position_usd=100), current_price=500_000, config=CONFIG)
        assert order is None

    def test_none_when_price_non_positive(self):
        order = build_buy_order("X", 50, sizing(), current_price=0, config=CONFIG)
        assert order is None

    def test_weight_pct_carried_from_sizing(self):
        order = build_buy_order("ANET", 74, sizing(position_pct=3.5), 100, CONFIG)
        assert order.weight_pct == 3.5


class TestBuildExitOrder:
    def evaluation_with(self, *trigger_types):
        return HeldPositionEvaluation(ticker="NBIS", triggers=[ExitTrigger(type=t, detail={}) for t in trigger_types])

    def test_profit_band_trims_configured_fraction(self):
        order = build_exit_order(
            "NBIS", held_qty=8, current_price=222.0, weight_pct=3.6, conviction=61,
            evaluation=self.evaluation_with("PROFIT_BAND"), config=CONFIG,
        )
        assert order.action == "SELL"
        assert order.quantity == 4  # floor(8 * 0.5)
        assert order.is_trim is True
        assert order.trigger_type == "PROFIT_BAND"

    def test_trailing_stop_sells_full_position(self):
        order = build_exit_order(
            "NBIS", held_qty=8, current_price=200.0, weight_pct=3.6, conviction=61,
            evaluation=self.evaluation_with("TRAILING_STOP"), config=CONFIG,
        )
        assert order.quantity == 8
        assert order.is_trim is False

    def test_thesis_decay_sells_full_position(self):
        order = build_exit_order(
            "NBIS", held_qty=5, current_price=200.0, weight_pct=2.0, conviction=40,
            evaluation=self.evaluation_with("THESIS_DECAY"), config=CONFIG,
        )
        assert order.quantity == 5

    def test_limit_price_below_current_for_a_sell(self):
        order = build_exit_order(
            "NBIS", 8, 200.0, 3.6, 61, self.evaluation_with("TRAILING_STOP"), CONFIG,
        )
        assert order.limit_price < 200.0

    def test_none_when_no_trigger(self):
        order = build_exit_order("NBIS", 8, 200.0, 3.6, 61, HeldPositionEvaluation(ticker="NBIS", triggers=[]), CONFIG)
        assert order is None

    def test_trailing_stop_takes_priority_label_when_multiple_trigger(self):
        order = build_exit_order(
            "NBIS", 8, 200.0, 3.6, 61, self.evaluation_with("TRAILING_STOP", "PROFIT_BAND"), CONFIG
        )
        assert order.trigger_type == "TRAILING_STOP"
        assert order.quantity == 8  # full exit, not the profit-band trim fraction

    def test_none_when_held_qty_zero(self):
        order = build_exit_order("NBIS", 0, 200.0, 0, 61, self.evaluation_with("TRAILING_STOP"), CONFIG)
        assert order is None

    def test_runner_trim_sells_down_to_target_pct_of_nav(self):
        # held_qty=100 * price=10 = $1,000 value; nav=$2,000 -> weight=50%.
        # Target 25% of nav = $500 -> target_qty=50 -> sell the other 50.
        order = build_exit_order(
            "NBIS", held_qty=100, current_price=10.0, weight_pct=50.0, conviction=61,
            evaluation=self.evaluation_with("RUNNER_TRIM"), config=CONFIG,
            nav_usd=2000.0, runner_trim_target_pct=25.0,
        )
        assert order.action == "SELL"
        assert order.quantity == 50
        assert order.is_trim is True
        assert order.trigger_type == "RUNNER_TRIM"

    def test_runner_trim_never_sells_more_than_held(self):
        # Degenerate case: target_qty would be negative (nav tiny relative
        # to position) — never sell more than held_qty.
        order = build_exit_order(
            "NBIS", held_qty=10, current_price=10.0, weight_pct=90.0, conviction=61,
            evaluation=self.evaluation_with("RUNNER_TRIM"), config=CONFIG,
            nav_usd=100.0, runner_trim_target_pct=25.0,
        )
        assert order.quantity <= 10

    def test_runner_trim_without_nav_context_falls_back_to_full_exit(self):
        # Defensive default when nav_usd/runner_trim_target_pct aren't
        # wired (shouldn't happen in practice — the orchestrator always
        # passes them) — never leaves a bigger position than intended.
        order = build_exit_order(
            "NBIS", held_qty=8, current_price=200.0, weight_pct=31.0, conviction=61,
            evaluation=self.evaluation_with("RUNNER_TRIM"), config=CONFIG,
        )
        assert order.quantity == 8

    def test_runner_trim_takes_priority_label_over_other_triggers(self):
        order = build_exit_order(
            "NBIS", held_qty=100, current_price=10.0, weight_pct=50.0, conviction=61,
            evaluation=self.evaluation_with("RUNNER_TRIM", "TRAILING_STOP"), config=CONFIG,
            nav_usd=2000.0, runner_trim_target_pct=25.0,
        )
        assert order.trigger_type == "RUNNER_TRIM"
        assert order.quantity == 50  # the runner-trim math, not a full exit
