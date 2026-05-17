from __future__ import annotations

from decimal import Decimal

from trader.data.snapshots import deterministic_quote
from trader.execution.simulator import ExecutionSimulator
from trader.models import ExecutionStatus, TradeAction, TradePlan


def test_simulator_returns_structured_execution_result() -> None:
    plan = TradePlan(
        symbol="TEST",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("100"),
        notional=Decimal("100"),
        source_signal_id="sig",
        strategy="unit",
    )

    result = ExecutionSimulator().simulate(plan, deterministic_quote("TEST"))

    assert result.status == ExecutionStatus.FILLED
    assert result.fills
    assert result.submitted_to_broker is False


def test_simulator_models_partial_and_missing_quote() -> None:
    plan = TradePlan(
        symbol="TEST",
        action=TradeAction.BUY,
        quantity=4,
        limit_price=Decimal("100"),
        notional=Decimal("400"),
        source_signal_id="sig",
        strategy="unit",
    )
    simulator = ExecutionSimulator()

    partial = simulator.simulate(plan, deterministic_quote("TEST"), scenario="partial")
    missing = simulator.simulate(plan, None)

    assert partial.status == ExecutionStatus.PARTIAL
    assert partial.fills[0].quantity == 2
    assert missing.status == ExecutionStatus.REJECTED
