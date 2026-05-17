"""Paper executor stub.

Future phases may enable paper order submission deliberately. This phase refuses
all broker submissions.
"""

from __future__ import annotations

from trader.config import TraderConfig
from trader.models import ExecutionResult, ExecutionStatus, TradePlan


class PaperExecutor:
    """Refusing paper executor stub."""

    def __init__(self, config: TraderConfig) -> None:
        self.config = config

    def submit(self, plan: TradePlan) -> ExecutionResult:
        return ExecutionResult(
            plan_id=plan.id,
            symbol=plan.symbol,
            status=ExecutionStatus.BLOCKED,
            message="paper executor is disabled in this initial version",
            submitted_to_broker=False,
            warnings=["paper_executor_stub"],
        )
