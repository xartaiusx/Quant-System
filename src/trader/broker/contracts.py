"""Contract descriptors for future IBKR integration."""

from __future__ import annotations

from trader.models import Instrument


def stock_contract_descriptor(instrument: Instrument) -> dict[str, str]:
    """Return a serializable stock contract descriptor.

    Future phases can translate this into `ibapi.contract.Contract`.
    """

    return {
        "symbol": instrument.symbol,
        "secType": "STK",
        "exchange": instrument.exchange,
        "currency": instrument.currency,
    }
