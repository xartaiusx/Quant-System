"""Execution router."""

from __future__ import annotations

from trader.config import TraderConfig
from trader.execution.paper_executor import PaperExecutor
from trader.execution.simulator import ExecutionSimulator
from trader.models import ExecutionResult, ExecutionStatus, MarketQuote, RiskDecision


class ExecutionRouter:
    """Route only risk-approved plans to a simulator or refusing paper stub."""

    def __init__(self, config: TraderConfig) -> None:
        self.config = config
        self.simulator = ExecutionSimulator()
        self.paper_executor = PaperExecutor(config)

    def route(
        self,
        decisions: list[RiskDecision],
        quotes: dict[str, MarketQuote],
        *,
        destination: str = "simulator",
    ) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for decision in decisions:
            if not decision.approved or decision.adjusted_plan is None:
                results.append(
                    ExecutionResult(
                        plan_id=decision.plan_id,
                        symbol=decision.symbol,
                        status=ExecutionStatus.BLOCKED,
                        message=decision.blocked_reason or "risk decision not approved",
                        submitted_to_broker=False,
                        warnings=decision.warnings,
                    )
                )
                continue

            if destination == "simulator":
                results.append(
                    self.simulator.simulate(
                        decision.adjusted_plan,
                        quotes.get(decision.adjusted_plan.symbol),
                    )
                )
            elif destination == "paper":
                results.append(self.paper_executor.submit(decision.adjusted_plan))
            else:
                results.append(
                    ExecutionResult(
                        plan_id=decision.plan_id,
                        symbol=decision.symbol,
                        status=ExecutionStatus.BLOCKED,
                        message=f"unsupported execution destination: {destination}",
                        submitted_to_broker=False,
                        warnings=["unsupported_destination"],
                    )
                )
        return results
