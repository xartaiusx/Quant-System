"""Sizing helpers."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def integer_quantity_for_notional(notional: Decimal, price: Decimal) -> int:
    """Return a positive integer quantity for a notional and price."""

    if notional <= 0 or price <= 0:
        raise ValueError("notional and price must be positive")
    quantity = int((notional / price).to_integral_value(rounding=ROUND_DOWN))
    return max(quantity, 1)
