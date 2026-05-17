"""Mean-reversion strategy placeholder."""

from __future__ import annotations

from decimal import Decimal

from trader.models import Signal, SignalDirection
from trader.strategy.base import PriceHistory, QuoteMap, Strategy


class MeanReversionStrategy(Strategy):
    """Minimal placeholder that emits small buy signals after deterministic dips."""

    name = "mean_reversion"

    def __init__(self, *, dip_threshold: Decimal = Decimal("-0.01")) -> None:
        self.dip_threshold = dip_threshold

    def generate_signals(
        self,
        symbols: list[str],
        quotes: QuoteMap,
        history: PriceHistory,
    ) -> list[Signal]:
        # TODO: Replace this two-point placeholder with researched indicators and tests.
        signals: list[Signal] = []
        for symbol in symbols:
            normalized = symbol.strip().upper()
            prices = history.get(normalized, [])
            if len(prices) < 2 or prices[0] <= 0 or normalized not in quotes:
                continue
            move = (prices[-1] - prices[0]) / prices[0]
            if move <= self.dip_threshold:
                signals.append(
                    Signal(
                        symbol=normalized,
                        direction=SignalDirection.BUY,
                        strength=min(abs(move), Decimal("1")),
                        confidence=Decimal("0.50"),
                        strategy=self.name,
                        reason=f"placeholder dip below threshold {move:.4f}",
                    )
                )
        return signals
