"""Shared broker-free SPY SMA target-state policy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from trader.models import (
    SPYPolicyTransition,
    SPYSmaDecision,
    SPYTargetState,
)

STRATEGY_NAME = "spy_sma_target_state"
STRATEGY_VERSION = "1.0.0"


class CompletedBar(Protocol):
    """Minimum completed-bar surface required by the policy."""

    symbol: str
    timestamp: datetime
    close: Decimal


def spy_sma_parameter_fingerprint(short_window: int, long_window: int) -> str:
    """Return a stable fingerprint for the versioned strategy parameters."""

    payload = {
        "long_window": long_window,
        "short_window": short_window,
        "strategy_name": STRATEGY_NAME,
        "strategy_version": STRATEGY_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def evaluate_spy_sma_policy(
    bars: Sequence[CompletedBar],
    *,
    short_window: int,
    long_window: int,
) -> SPYSmaDecision:
    """Evaluate desired SPY exposure from completed bars only."""

    if short_window <= 0 or long_window <= 1 or short_window >= long_window:
        raise ValueError("SPY SMA policy requires 0 < short_window < long_window")

    fingerprint = spy_sma_parameter_fingerprint(short_window, long_window)
    required = long_window + 1
    available = len(bars)
    as_of = bars[-1].timestamp if bars else None
    invalid_reason = _invalid_bar_reason(bars)
    if invalid_reason is not None:
        return SPYSmaDecision(
            parameter_fingerprint=fingerprint,
            short_window=short_window,
            long_window=long_window,
            as_of=as_of,
            available_bars=available,
            required_bars=required,
            warmup_complete=False,
            data_valid=False,
            transition=SPYPolicyTransition.INVALID,
            reason=invalid_reason,
        )
    if available < required:
        return SPYSmaDecision(
            parameter_fingerprint=fingerprint,
            short_window=short_window,
            long_window=long_window,
            as_of=as_of,
            available_bars=available,
            required_bars=required,
            reason=f"warmup requires {required} completed bars; observed {available}",
        )

    closes = [bar.close for bar in bars]
    previous_fast = _average(closes[-short_window - 1 : -1])
    previous_slow = _average(closes[-long_window - 1 : -1])
    current_fast = _average(closes[-short_window:])
    current_slow = _average(closes[-long_window:])
    previous_state = (
        SPYTargetState.LONG if previous_fast > previous_slow else SPYTargetState.FLAT
    )
    target_state = SPYTargetState.LONG if current_fast > current_slow else SPYTargetState.FLAT
    transition = _transition(previous_state, target_state)
    return SPYSmaDecision(
        parameter_fingerprint=fingerprint,
        short_window=short_window,
        long_window=long_window,
        as_of=as_of,
        available_bars=available,
        required_bars=required,
        warmup_complete=True,
        data_valid=True,
        previous_target_state=previous_state,
        target_state=target_state,
        transition=transition,
        previous_fast_average=previous_fast,
        previous_slow_average=previous_slow,
        fast_average=current_fast,
        slow_average=current_slow,
        reason=f"completed-bar SMA target is {target_state.value}",
    )


def _invalid_bar_reason(bars: Sequence[CompletedBar]) -> str | None:
    for bar in bars:
        if str(bar.symbol).strip().upper() != "SPY":
            return "policy input contains a non-SPY bar"
        if not bar.close.is_finite() or bar.close <= 0:
            return "policy input contains an invalid close"
    return None


def _transition(
    previous_state: SPYTargetState,
    target_state: SPYTargetState,
) -> SPYPolicyTransition:
    if previous_state == SPYTargetState.FLAT and target_state == SPYTargetState.LONG:
        return SPYPolicyTransition.ENTER_LONG
    if previous_state == SPYTargetState.LONG and target_state == SPYTargetState.FLAT:
        return SPYPolicyTransition.EXIT_LONG
    if target_state == SPYTargetState.LONG:
        return SPYPolicyTransition.HOLD_LONG
    return SPYPolicyTransition.HOLD_FLAT


def _average(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


__all__ = [
    "STRATEGY_NAME",
    "STRATEGY_VERSION",
    "evaluate_spy_sma_policy",
    "spy_sma_parameter_fingerprint",
]
