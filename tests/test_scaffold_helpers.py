from decimal import Decimal

from trader.backtest.costs import flat_commission
from trader.backtest.metrics import empty_metrics
from trader.broker.contracts import stock_contract_descriptor
from trader.models import Instrument


def test_legacy_scaffold_helpers_remain_explicit_and_serializable() -> None:
    instrument = Instrument(symbol="SPY", exchange="SMART", currency="USD")

    assert flat_commission() == Decimal("0")
    assert empty_metrics() == {"status": "not_implemented"}
    assert stock_contract_descriptor(instrument) == {
        "symbol": "SPY",
        "secType": "STK",
        "exchange": "SMART",
        "currency": "USD",
    }
