"""Deterministic mock data used by tests and dry-run CLI commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trader.models import AccountSnapshot, MarketQuote, PositionSnapshot

BASE_PRICES: dict[str, Decimal] = {
    "SPY": Decimal("500.00"),
    "QQQ": Decimal("425.00"),
    "AAPL": Decimal("190.00"),
    "MSFT": Decimal("420.00"),
    "NVDA": Decimal("900.00"),
}

PREVIOUS_CLOSES: dict[str, Decimal] = {
    "SPY": Decimal("495.00"),
    "QQQ": Decimal("423.00"),
    "AAPL": Decimal("191.00"),
    "MSFT": Decimal("414.00"),
    "NVDA": Decimal("870.00"),
}


def deterministic_quote(
    symbol: str,
    *,
    stale: bool = False,
    missing_bid_ask: bool = False,
) -> MarketQuote:
    """Return a deterministic mock quote for a symbol."""

    normalized = symbol.strip().upper()
    last = BASE_PRICES.get(normalized, Decimal("100.00"))
    spread = max(last * Decimal("0.0002"), Decimal("0.01"))
    timestamp = datetime.now(UTC) - (timedelta(minutes=10) if stale else timedelta(seconds=5))
    if missing_bid_ask:
        return MarketQuote(symbol=normalized, bid=None, ask=None, last=last, timestamp=timestamp)
    return MarketQuote(
        symbol=normalized,
        bid=last - spread / Decimal("2"),
        ask=last + spread / Decimal("2"),
        last=last,
        timestamp=timestamp,
    )


def deterministic_quotes(symbols: list[str]) -> dict[str, MarketQuote]:
    """Return deterministic quotes keyed by symbol."""

    return {symbol.strip().upper(): deterministic_quote(symbol) for symbol in symbols}


def deterministic_history(symbols: list[str]) -> dict[str, list[Decimal]]:
    """Return minimal historical prices for strategy examples."""

    history: dict[str, list[Decimal]] = {}
    for symbol in symbols:
        normalized = symbol.strip().upper()
        previous = PREVIOUS_CLOSES.get(normalized, Decimal("99.00"))
        current = BASE_PRICES.get(normalized, Decimal("100.00"))
        history[normalized] = [previous, current]
    return history


def mock_account_snapshot(account_id: str | None = None) -> AccountSnapshot:
    """Return a safe mock account snapshot."""

    return AccountSnapshot(
        account_id=account_id,
        equity=Decimal("10000"),
        cash=Decimal("10000"),
        buying_power=Decimal("10000"),
        daily_pnl=Decimal("0"),
        is_mock=True,
    )


def mock_positions() -> list[PositionSnapshot]:
    """Return an empty deterministic position book."""

    return []
