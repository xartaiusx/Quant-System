"""Market data adapter skeleton."""

from __future__ import annotations

from trader.data.snapshots import deterministic_quotes
from trader.models import MarketQuote


class MarketDataClient:
    """Read-only market data facade.

    The initial implementation returns deterministic mock quotes. No TWS
    connection is required for tests.
    """

    def get_quotes(self, symbols: list[str]) -> dict[str, MarketQuote]:
        return deterministic_quotes(symbols)
