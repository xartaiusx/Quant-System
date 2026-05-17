"""Universe selection helpers."""

from __future__ import annotations

from trader.config import TraderConfig
from trader.models import Instrument


def instruments_from_config(config: TraderConfig) -> list[Instrument]:
    """Create instrument descriptors from configured symbols."""

    return [Instrument(symbol=symbol) for symbol in config.universe]


def parse_symbols(symbols: str | list[str]) -> list[str]:
    """Normalize a user-provided symbol list."""

    raw_symbols = symbols.split(",") if isinstance(symbols, str) else symbols
    normalized = [str(symbol).strip().upper() for symbol in raw_symbols if str(symbol).strip()]
    if not normalized:
        raise ValueError("at least one symbol is required")
    return normalized
