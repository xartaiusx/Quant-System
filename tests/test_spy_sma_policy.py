from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trader.models import BacktestBar, SPYPolicyTransition, SPYTargetState
from trader.strategy.spy_sma import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    evaluate_spy_sma_policy,
    spy_sma_parameter_fingerprint,
)


def _bars(closes: list[str], *, symbol: str = "SPY") -> list[BacktestBar]:
    start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    return [
        BacktestBar(
            symbol=symbol,
            timestamp=start + timedelta(minutes=5 * index),
            open=Decimal(close),
            high=Decimal(close) + Decimal("1"),
            low=Decimal(close) - Decimal("1"),
            close=Decimal(close),
            volume=Decimal("1000"),
        )
        for index, close in enumerate(closes)
    ]


def test_policy_fails_closed_during_warmup() -> None:
    decision = evaluate_spy_sma_policy(_bars(["10", "11", "12"]), short_window=2, long_window=3)

    assert decision.warmup_complete is False
    assert decision.data_valid is False
    assert decision.target_state == SPYTargetState.FLAT
    assert decision.transition == SPYPolicyTransition.WARMUP


def test_policy_enters_and_holds_long_from_completed_bars() -> None:
    entering = evaluate_spy_sma_policy(
        _bars(["10", "10", "10", "12"]),
        short_window=2,
        long_window=3,
    )
    holding = evaluate_spy_sma_policy(
        _bars(["10", "10", "10", "12", "13"]),
        short_window=2,
        long_window=3,
    )

    assert entering.target_state == SPYTargetState.LONG
    assert entering.transition == SPYPolicyTransition.ENTER_LONG
    assert holding.target_state == SPYTargetState.LONG
    assert holding.transition == SPYPolicyTransition.HOLD_LONG


def test_policy_exits_long() -> None:
    decision = evaluate_spy_sma_policy(
        _bars(["10", "10", "12", "13", "9"]),
        short_window=2,
        long_window=3,
    )

    assert decision.previous_target_state == SPYTargetState.LONG
    assert decision.target_state == SPYTargetState.FLAT
    assert decision.transition == SPYPolicyTransition.EXIT_LONG


def test_policy_fingerprint_is_stable_and_versioned() -> None:
    first = spy_sma_parameter_fingerprint(5, 20)
    second = spy_sma_parameter_fingerprint(5, 20)

    assert first == second
    assert first.startswith("sha256:")
    assert STRATEGY_NAME == "spy_sma_target_state"
    assert STRATEGY_VERSION == "1.0.0"


def test_policy_rejects_invalid_scope_and_windows() -> None:
    with pytest.raises(ValueError, match="short_window"):
        evaluate_spy_sma_policy(_bars(["10"]), short_window=5, long_window=5)

    decision = evaluate_spy_sma_policy(
        _bars(["10", "10", "10", "10"], symbol="GLD"),
        short_window=2,
        long_window=3,
    )
    assert decision.data_valid is False
    assert decision.transition == SPYPolicyTransition.INVALID
