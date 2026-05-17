"""Deterministic execution simulator."""

from __future__ import annotations

from decimal import Decimal

from trader.models import (
    ExecutionResult,
    ExecutionStatus,
    MarketQuote,
    SimulatedFill,
    TradeAction,
    TradePlan,
)


class ExecutionSimulator:
    """Model simple spread, slippage, rejection, partial fill, and missing quote cases."""

    def __init__(self, *, slippage_bps: Decimal = Decimal("1")) -> None:
        self.slippage_bps = slippage_bps

    def simulate(
        self,
        plan: TradePlan,
        quote: MarketQuote | None,
        *,
        scenario: str = "normal",
    ) -> ExecutionResult:
        if quote is None or not quote.has_bid_ask:
            return ExecutionResult(
                plan_id=plan.id,
                symbol=plan.symbol,
                status=ExecutionStatus.REJECTED,
                message="missing quote or bid/ask prevented simulated fill",
                warnings=["missing_quote"],
            )

        if scenario == "reject":
            return ExecutionResult(
                plan_id=plan.id,
                symbol=plan.symbol,
                status=ExecutionStatus.REJECTED,
                message="simulated venue rejection",
                warnings=["simulated_rejection"],
            )

        fill_quantity = plan.quantity
        status = ExecutionStatus.FILLED
        message = "simulated fill"
        if scenario == "partial":
            fill_quantity = max(1, plan.quantity // 2)
            status = ExecutionStatus.PARTIAL
            message = "simulated partial fill"

        fill_price = self._fill_price(plan, quote)
        fill = SimulatedFill(
            plan_id=plan.id,
            symbol=plan.symbol,
            action=plan.action,
            quantity=fill_quantity,
            fill_price=fill_price,
        )
        return ExecutionResult(
            plan_id=plan.id,
            symbol=plan.symbol,
            status=status,
            message=message,
            fills=[fill],
            submitted_to_broker=False,
            warnings=[] if scenario == "normal" else [f"scenario:{scenario}"],
        )

    def _fill_price(self, plan: TradePlan, quote: MarketQuote) -> Decimal:
        slippage_multiplier = self.slippage_bps / Decimal("10000")
        if plan.action == TradeAction.BUY:
            assert quote.ask is not None
            return quote.ask * (Decimal("1") + slippage_multiplier)
        assert quote.bid is not None
        return quote.bid * (Decimal("1") - slippage_multiplier)
