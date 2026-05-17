"""Simple deterministic momentum strategy."""

from __future__ import annotations

from decimal import Decimal

from trader.models import Signal, SignalDirection
from trader.strategy.base import PriceHistory, QuoteMap, Strategy


class MomentumStrategy(Strategy):
    """Rank symbols by two-point return and emit buy signals for leaders."""

    name = "momentum"

    def __init__(self, *, max_signals: int = 2, min_return: Decimal = Decimal("0.001")) -> None:
        self.max_signals = max_signals
        self.min_return = min_return

    def generate_signals(
        self,
        symbols: list[str],
        quotes: QuoteMap,
        history: PriceHistory,
    ) -> list[Signal]:
        ranked: list[tuple[str, Decimal]] = []
        for symbol in symbols:
            normalized = symbol.strip().upper()
            prices = history.get(normalized, [])
            if len(prices) < 2 or prices[0] <= 0:
                continue
            momentum = (prices[-1] - prices[0]) / prices[0]
            if normalized in quotes and momentum >= self.min_return:
                ranked.append((normalized, momentum))

        ranked.sort(key=lambda item: item[1], reverse=True)
        signals: list[Signal] = []
        for symbol, momentum in ranked[: self.max_signals]:
            strength = min(momentum.copy_abs(), Decimal("1"))
            signals.append(
                Signal(
                    symbol=symbol,
                    direction=SignalDirection.BUY,
                    strength=strength,
                    confidence=min(Decimal("0.50") + strength, Decimal("0.95")),
                    strategy=self.name,
                    reason=f"positive deterministic momentum {momentum:.4f}",
                )
            )
        return signals
