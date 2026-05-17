"""Backtest cost model placeholders."""

from __future__ import annotations

from decimal import Decimal


def flat_commission() -> Decimal:
    """Return zero until a researched cost model is added."""

    return Decimal("0")
