from __future__ import annotations

import inspect

import trader.strategy.momentum as momentum_module
from trader.data.snapshots import deterministic_history, deterministic_quotes
from trader.models import SignalDirection
from trader.strategy import MomentumStrategy


def test_momentum_strategy_emits_signals_without_broker_dependency() -> None:
    symbols = ["SPY", "QQQ", "AAPL"]
    quotes = deterministic_quotes(symbols)
    history = deterministic_history(symbols)

    signals = MomentumStrategy(max_signals=2).generate_signals(symbols, quotes, history)

    assert signals
    assert all(signal.direction == SignalDirection.BUY for signal in signals)
    assert "trader.broker" not in inspect.getsource(momentum_module)
