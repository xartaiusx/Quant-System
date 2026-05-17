"""Strategy abstractions.

Strategies emit signals only. They do not know about brokers, orders, or
execution routing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from trader.models import MarketQuote, Signal

PriceHistory = dict[str, list[Decimal]]
QuoteMap = dict[str, MarketQuote]


class Strategy(ABC):
    """Base class for pure signal-generation strategies."""

    name: str

    @abstractmethod
    def generate_signals(
        self,
        symbols: list[str],
        quotes: QuoteMap,
        history: PriceHistory,
    ) -> list[Signal]:
        """Generate proposal-only signals from market snapshots."""
