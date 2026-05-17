from __future__ import annotations

from decimal import Decimal

from trader.config import load_config
from trader.data.snapshots import deterministic_quote, mock_account_snapshot
from trader.models import Signal, SignalDirection, TradeAction, TradePlan
from trader.portfolio.construction import build_trade_plans
from trader.risk.rules import RiskEngine


def _paper_enabled_config():
    return load_config(
        env={"ALLOW_PAPER_ORDERS": "true", "MAX_TRADE_NOTIONAL": "1000"},
        load_dotenv_file=False,
    )


def test_portfolio_converts_signals_to_plans() -> None:
    config = _paper_enabled_config()
    signal = Signal(
        symbol="TEST",
        direction=SignalDirection.BUY,
        strength=Decimal("0.5"),
        confidence=Decimal("0.7"),
        strategy="unit",
        reason="unit",
    )
    quote = deterministic_quote("TEST")

    plans = build_trade_plans([signal], {"TEST": quote}, config)

    assert len(plans) == 1
    assert plans[0].symbol == "TEST"
    assert plans[0].action == TradeAction.BUY
    assert plans[0].reason_codes


def test_risk_blocks_oversized_trade() -> None:
    config = load_config(
        env={"ALLOW_PAPER_ORDERS": "true", "MAX_TRADE_NOTIONAL": "10"},
        load_dotenv_file=False,
    )
    plan = TradePlan(
        symbol="TEST",
        action=TradeAction.BUY,
        quantity=2,
        limit_price=Decimal("10"),
        notional=Decimal("20"),
        source_signal_id="sig",
        strategy="unit",
    )

    decision = RiskEngine(config).evaluate_one(
        plan,
        {"TEST": deterministic_quote("TEST")},
        mock_account_snapshot(),
    )

    assert decision.approved is False
    assert decision.blocked_reason == "max_trade_notional_exceeded"


def test_risk_blocks_stale_quotes() -> None:
    config = _paper_enabled_config()
    plan = TradePlan(
        symbol="TEST",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("10"),
        notional=Decimal("10"),
        source_signal_id="sig",
        strategy="unit",
    )

    decision = RiskEngine(config).evaluate_one(
        plan,
        {"TEST": deterministic_quote("TEST", stale=True)},
        mock_account_snapshot(),
    )

    assert decision.approved is False
    assert decision.blocked_reason == "stale_quote"


def test_risk_blocks_when_paper_orders_disabled() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    plan = TradePlan(
        symbol="TEST",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("10"),
        notional=Decimal("10"),
        source_signal_id="sig",
        strategy="unit",
    )

    decision = RiskEngine(config).evaluate_one(
        plan,
        {"TEST": deterministic_quote("TEST")},
        mock_account_snapshot(),
    )

    assert decision.approved is False
    assert decision.blocked_reason == "paper_orders_disabled"
