"""Risk rules for proposed trade plans."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from trader.config import TraderConfig, TradingMode
from trader.models import AccountSnapshot, MarketQuote, PositionSnapshot, RiskDecision, TradePlan
from trader.risk.guards import config_has_live_order_risk

DEFAULT_MAX_QUOTE_AGE_SECONDS = 300


class RiskEngine:
    """Evaluate trade plans before any execution routing."""

    def __init__(
        self,
        config: TraderConfig,
        *,
        max_quote_age_seconds: int = DEFAULT_MAX_QUOTE_AGE_SECONDS,
    ) -> None:
        self.config = config
        self.max_quote_age_seconds = max_quote_age_seconds

    def evaluate(
        self,
        plans: list[TradePlan],
        quotes: dict[str, MarketQuote],
        account: AccountSnapshot,
        positions: list[PositionSnapshot],
    ) -> list[RiskDecision]:
        """Return one explicit risk decision per plan."""

        duplicates = Counter((plan.symbol, plan.action) for plan in plans)
        open_symbols = {position.symbol for position in positions if position.quantity != 0}
        planned_symbols = open_symbols | {plan.symbol for plan in plans}
        max_open_exceeded = len(planned_symbols) > self.config.max_open_positions

        return [
            self.evaluate_one(
                plan,
                quotes,
                account,
                open_symbols=open_symbols,
                duplicate_count=duplicates[(plan.symbol, plan.action)],
                max_open_exceeded=max_open_exceeded,
            )
            for plan in plans
        ]

    def evaluate_one(
        self,
        plan: TradePlan,
        quotes: dict[str, MarketQuote],
        account: AccountSnapshot,
        *,
        open_symbols: set[str] | None = None,
        duplicate_count: int = 1,
        max_open_exceeded: bool = False,
    ) -> RiskDecision:
        """Evaluate a single plan."""

        open_symbols = open_symbols or set()
        blocked_reason = self._first_blocker(
            plan,
            quotes,
            account,
            open_symbols=open_symbols,
            duplicate_count=duplicate_count,
            max_open_exceeded=max_open_exceeded,
        )
        if blocked_reason:
            return RiskDecision(
                plan_id=plan.id,
                symbol=plan.symbol,
                approved=False,
                blocked_reason=blocked_reason,
                warnings=[],
            )

        warnings = []
        if self.config.trading_mode in {TradingMode.DRY_RUN, TradingMode.BACKTEST}:
            warnings.append(f"mode:{self.config.trading_mode.value}")

        return RiskDecision(
            plan_id=plan.id,
            symbol=plan.symbol,
            approved=True,
            warnings=warnings,
            adjusted_plan=plan,
        )

    def _first_blocker(
        self,
        plan: TradePlan,
        quotes: dict[str, MarketQuote],
        account: AccountSnapshot,
        *,
        open_symbols: set[str],
        duplicate_count: int,
        max_open_exceeded: bool,
    ) -> str | None:
        if config_has_live_order_risk(self.config):
            return "live_order_configuration_rejected"
        if self.config.trading_mode == TradingMode.PAPER and not self.config.allow_paper_orders:
            return "paper_orders_disabled"
        if duplicate_count > 1:
            return "duplicate_symbol_action_in_cycle"
        if plan.notional > self.config.max_trade_notional:
            return "max_trade_notional_exceeded"
        if account.daily_pnl <= -self.config.max_daily_loss:
            return "max_daily_loss_exceeded"
        if max_open_exceeded and plan.symbol not in open_symbols:
            return "max_open_positions_exceeded"

        equity_limit = account.equity * (self.config.max_position_pct_equity / Decimal("100"))
        if plan.notional > equity_limit:
            return "max_position_pct_equity_exceeded"

        quote = quotes.get(plan.symbol)
        if quote is None:
            return "missing_quote"
        if quote.is_stale(max_age_seconds=self.max_quote_age_seconds):
            return "stale_quote"
        if not quote.has_bid_ask:
            return "missing_bid_ask"
        return None


def evaluate_trade_plans(
    plans: list[TradePlan],
    quotes: dict[str, MarketQuote],
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    config: TraderConfig,
) -> list[RiskDecision]:
    """Convenience wrapper for the default risk engine."""

    return RiskEngine(config).evaluate(plans, quotes, account, positions)
