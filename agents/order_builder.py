"""Order Builder — §5.4. Not itself a numbered §10 build-order step, but
built alongside step 8 (Briefing assembler) because §3's briefing mockup
("BUY ANET 3 shares LIMIT $142.50 ~$427") can't be rendered without a fully-
specified order, and nothing upstream of this module produces one.

"Takes an approved-by-risk proposal and produces a complete order: action,
quantity (whole shares — no fractional...), order type, limit price (from
recent price action and spread), and estimated total cost... Never submits.
There is no submit function in this codebase." (§5.4)

The limit-price formula isn't specified — see OrderBuilderConfig's docstring
in core/config.py. Every function here is pure: given a sized/triggered
position and a current price, produce an OrderProposal. Fetching the price,
deciding whether to trade, and actually placing the order (you, manually, in
IBKR) are all someone else's job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from core.config import OrderBuilderConfig
from core.risk_rules import HeldPositionEvaluation, SizingResult

OrderAction = Literal["BUY", "SELL"]


@dataclass
class OrderProposal:
    ticker: str
    action: OrderAction
    quantity: int
    order_type: Literal["LIMIT"]
    limit_price: float
    estimated_cost_usd: float
    weight_pct: float
    conviction: float
    trigger_type: str | None  # None for a new BUY; TRAILING_STOP/PROFIT_BAND/THESIS_DECAY for an exit
    is_trim: bool


def build_buy_order(
    ticker: str,
    conviction: float,
    sizing: SizingResult,
    current_price: float,
    config: OrderBuilderConfig,
) -> OrderProposal | None:
    """None if risk didn't approve the position, or if the sized dollar
    amount can't buy even one whole share at the current price."""
    if not sizing.approved or current_price <= 0:
        return None
    quantity = int(sizing.position_usd // current_price)
    if quantity <= 0:
        return None
    limit_price = round(current_price * (1 + config.limit_buffer_pct / 100), 2)
    return OrderProposal(
        ticker=ticker,
        action="BUY",
        quantity=quantity,
        order_type="LIMIT",
        limit_price=limit_price,
        estimated_cost_usd=round(quantity * limit_price, 2),
        weight_pct=sizing.position_pct,
        conviction=conviction,
        trigger_type=None,
        is_trim=False,
    )


def build_exit_order(
    ticker: str,
    held_qty: float,
    current_price: float,
    weight_pct: float,
    conviction: float,
    evaluation: HeldPositionEvaluation,
    config: OrderBuilderConfig,
) -> OrderProposal | None:
    """§3's NBIS example: a PROFIT_BAND trigger is a partial trim ("trim
    50%"), while §5.3's trailing-stop/thesis-decay triggers are framed as
    exits — this module reads that as: PROFIT_BAND sells
    `profit_trim_fraction` of the position, TRAILING_STOP and THESIS_DECAY
    sell all of it. Not stated explicitly in the spec; a judgment call like
    step 4/6's ranking rules."""
    if not evaluation.has_exit_signal or held_qty <= 0 or current_price <= 0:
        return None

    primary = evaluation.primary_trigger
    if primary.type == "PROFIT_BAND":
        quantity = max(1, math.floor(held_qty * config.profit_trim_fraction))
    else:
        quantity = math.floor(held_qty)
    quantity = min(quantity, math.floor(held_qty))
    if quantity <= 0:
        return None

    limit_price = round(current_price * (1 - config.limit_buffer_pct / 100), 2)
    return OrderProposal(
        ticker=ticker,
        action="SELL",
        quantity=quantity,
        order_type="LIMIT",
        limit_price=limit_price,
        estimated_cost_usd=round(quantity * limit_price, 2),
        weight_pct=weight_pct,
        conviction=conviction,
        trigger_type=primary.type,
        is_trim=quantity < held_qty,
    )
