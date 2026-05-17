"""Convert strategy signals into trade plans."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from trader.config import TraderConfig
from trader.models import MarketQuote, Signal, SignalDirection, TradeAction, TradePlan


def build_trade_plans(
    signals: list[Signal],
    quotes: dict[str, MarketQuote],
    config: TraderConfig,
    *,
    fixed_notional: Decimal = Decimal("50"),
) -> list[TradePlan]:
    """Build proposed trade plans from signals without placing orders."""

    plans: list[TradePlan] = []
    target_notional = min(fixed_notional, config.max_trade_notional)

    for signal in signals:
        if signal.direction == SignalDirection.HOLD:
            continue

        action = TradeAction.BUY if signal.direction == SignalDirection.BUY else TradeAction.SELL
        quote = quotes.get(signal.symbol)
        price = _planning_price(action, quote)
        if price is None:
            continue

        quantity = int((target_notional / price).to_integral_value(rounding=ROUND_DOWN))
        if quantity <= 0:
            quantity = 1

        notional = price * Decimal(quantity)
        plans.append(
            TradePlan(
                symbol=signal.symbol,
                action=action,
                quantity=quantity,
                limit_price=price,
                notional=notional,
                source_signal_id=signal.id,
                strategy=signal.strategy,
                reason_codes=[
                    f"signal:{signal.strategy}",
                    f"direction:{signal.direction}",
                    "fixed_small_notional",
                    "pre_risk_sizing",
                ],
            )
        )

    return plans


def _planning_price(action: TradeAction, quote: MarketQuote | None) -> Decimal | None:
    if quote is None:
        return None
    if action == TradeAction.BUY:
        return quote.ask or quote.last
    return quote.bid or quote.last
