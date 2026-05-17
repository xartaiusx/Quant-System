"""Pure signal-generation strategies."""

from __future__ import annotations

from trader.strategy.base import Strategy
from trader.strategy.mean_reversion import MeanReversionStrategy
from trader.strategy.momentum import MomentumStrategy


def get_strategy(name: str) -> Strategy:
    """Return a strategy by CLI name."""

    normalized = name.strip().lower().replace("-", "_")
    if normalized == "momentum":
        return MomentumStrategy()
    if normalized == "mean_reversion":
        return MeanReversionStrategy()
    raise ValueError(f"unknown strategy: {name}")


__all__ = ["MeanReversionStrategy", "MomentumStrategy", "Strategy", "get_strategy"]
