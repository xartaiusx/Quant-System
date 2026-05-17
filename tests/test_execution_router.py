from __future__ import annotations

from trader.config import load_config
from trader.execution.router import ExecutionRouter
from trader.models import ExecutionStatus, RiskDecision


def test_execution_router_refuses_unapproved_plans() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    decision = RiskDecision(
        plan_id="plan-1",
        symbol="SPY",
        approved=False,
        blocked_reason="unit_block",
    )

    results = ExecutionRouter(config).route([decision], {})

    assert results[0].status == ExecutionStatus.BLOCKED
    assert results[0].submitted_to_broker is False
    assert results[0].message == "unit_block"
