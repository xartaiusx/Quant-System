"""Order construction helpers constrained to safe order types."""

from __future__ import annotations

from trader.models import OrderIntent, OrderType, TradePlan


def order_intent_from_plan(plan: TradePlan) -> OrderIntent:
    """Create a limit-order intent from a risk-approved trade plan."""

    return OrderIntent(
        plan_id=plan.id,
        symbol=plan.symbol,
        action=plan.action,
        quantity=plan.quantity,
        order_type=OrderType.LIMIT,
        limit_price=plan.limit_price,
    )
