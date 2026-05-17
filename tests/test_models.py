from __future__ import annotations

from decimal import Decimal

from trader.models import BrokerDiagnosticReport, BrokerErrorEvent, Signal, SignalDirection


def test_signal_serializes_to_json() -> None:
    signal = Signal(
        symbol="spy",
        direction=SignalDirection.BUY,
        strength=Decimal("0.5"),
        confidence=Decimal("0.7"),
        strategy="test",
        reason="unit test",
    )

    payload = signal.model_dump_json()

    assert '"symbol":"SPY"' in payload
    assert '"direction":"buy"' in payload


def test_broker_diagnostic_report_serializes_to_json() -> None:
    report = BrokerDiagnosticReport(
        ok=False,
        mode="paper",
        host="127.0.0.1",
        port=7497,
        client_id=11,
        broker_kind="tws",
        connected=False,
        ibapi_available=False,
        ibapi_import_error="No module named 'ibapi'",
        connection_attempted=False,
        failure_stage="dependency_check",
        errors=[BrokerErrorEvent(message="ibapi missing")],
        final_status="failed",
    )

    payload = report.model_dump_json()

    assert '"order_routing_enabled":false' in payload
    assert '"connection_attempted":false' in payload
    assert '"failure_stage":"dependency_check"' in payload
    assert '"no_order_guarantee":true' in payload
    assert "ibapi missing" in payload
