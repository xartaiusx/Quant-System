from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

import trader.cli as cli
from trader.broker.ibkr_client import IBKRClient
from trader.config import load_config
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    BrokerDiagnosticReport,
    BrokerErrorEvent,
    ExecutionStatus,
    ManagedAccountInfo,
    TradeAction,
    TradePlan,
)


class TimeoutFakeApp:
    def __init__(self) -> None:
        self.current_time_event = threading.Event()
        self.managed_accounts_event = threading.Event()
        self.account_summary_event = threading.Event()
        self.positions_event = threading.Event()
        self.server_time = None
        self.raw_server_time = None
        self.managed_accounts: list[str] = []
        self.account_summary: dict[str, dict[str, dict[str, str]]] = {}
        self.positions: list[dict[str, Any]] = []
        self.errors: list[BrokerErrorEvent] = []
        self.warnings: list[str] = []
        self.connected = False
        self.current_time_requested = False

    def connect(self, _host: str, _port: int, _clientId: int) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    def run(self) -> None:
        return None

    def reqCurrentTime(self) -> None:
        self.current_time_requested = True

    def reqManagedAccts(self) -> None:
        return None

    def reqAccountSummary(self, _reqId: int, _groupName: str, _tags: str) -> None:
        return None

    def reqPositions(self) -> None:
        return None


class SuccessFakeApp(TimeoutFakeApp):
    def reqCurrentTime(self) -> None:
        self.current_time_requested = True
        self.raw_server_time = 1_700_000_000
        self.server_time = datetime.fromtimestamp(self.raw_server_time, tz=UTC)
        self.current_time_event.set()

    def reqManagedAccts(self) -> None:
        self.managed_accounts = ["DUXXYYZZ99"]
        self.managed_accounts_event.set()


def test_ibapi_missing_path_fails_gracefully() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    client = IBKRClient(config, ibapi_available=False)

    report = client.diagnostic_report(timeout=0.01)

    assert report.ok is False
    assert report.ibapi_available is False
    assert report.final_status == "failed"
    assert report.connection_attempted is False
    assert report.failure_stage == "dependency_check"
    assert report.no_order_guarantee is True
    assert report.errors
    assert "ibapi is not installed" in report.errors[0].message


def test_broker_probe_timeout_returns_structured_failure() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = TimeoutFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.diagnostic_report(timeout=0.01)

    assert fake_app.current_time_requested is True
    assert report.ok is False
    assert report.connected is True
    assert report.connection_attempted is True
    assert report.failure_stage == "timeout"
    assert report.errors
    assert "timed out" in report.errors[0].message
    assert report.order_routing_enabled is False


def test_broker_probe_success_with_mocked_read_only_callbacks() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = SuccessFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.diagnostic_report(timeout=0.01)

    assert report.ok is True
    assert report.connection_attempted is True
    assert report.connected is True
    assert report.failure_stage is None
    assert report.server_time == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert [account.account_id_masked for account in report.managed_accounts_masked] == [
        "DUXX****99"
    ]
    assert report.order_routing_enabled is False
    assert report.no_order_guarantee is True


def test_cli_preflight_runs_without_tws() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.app, ["preflight"])

    assert result.exit_code == 0
    assert "Broker preflight" in result.output
    assert "Order routing: disabled" in result.output


def test_broker_probe_command_handles_unavailable_tws_cleanly(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self, _config: object) -> None:
            return None

        def diagnostic_report(self, *, timeout: float | None = None) -> BrokerDiagnosticReport:
            return BrokerDiagnosticReport(
                ok=False,
                mode="paper",
                host="127.0.0.1",
                port=7497,
                client_id=11,
                broker_kind="tws",
                connected=False,
                ibapi_available=True,
                connection_attempted=True,
                failure_stage="socket_connect",
                errors=[BrokerErrorEvent(message="socket unavailable")],
                final_status="failed",
            )

    monkeypatch.setattr(cli, "IBKRClient", FakeClient)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["broker-probe", "--timeout", "0.01"])

    assert result.exit_code == 1
    assert "socket unavailable" in result.output
    assert "Diagnostic stage: socket_connect" in result.output
    assert "Traceback" not in result.output
    assert (tmp_path / "reports" / "latest_broker_probe.json").exists()


def test_broker_probe_command_handles_mocked_success(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self, _config: object) -> None:
            return None

        def diagnostic_report(self, *, timeout: float | None = None) -> BrokerDiagnosticReport:
            return BrokerDiagnosticReport(
                ok=True,
                mode="paper",
                host="127.0.0.1",
                port=7497,
                client_id=11,
                broker_kind="tws",
                connected=True,
                ibapi_available=True,
                connection_attempted=True,
                server_time=datetime.fromtimestamp(1_700_000_000, tz=UTC),
                managed_accounts_masked=[ManagedAccountInfo(account_id_masked="DUXX****99")],
                final_status="connected",
            )

    monkeypatch.setattr(cli, "IBKRClient", FakeClient)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["broker-probe", "--timeout", "0.01"])

    assert result.exit_code == 0
    assert "ibapi import" in result.output
    assert "No order APIs invoked" in result.output
    assert "Managed accounts: DUXX****99" in result.output
    assert (tmp_path / "reports" / "latest_broker_probe.json").exists()


def test_read_only_broker_code_does_not_call_place_order() -> None:
    source = Path("src/trader/broker/ibkr_client.py").read_text()

    assert "placeOrder" not in source


def test_paper_executor_still_refuses_submission() -> None:
    config = load_config(env={"ALLOW_PAPER_ORDERS": "true"}, load_dotenv_file=False)
    plan = TradePlan(
        symbol="SPY",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("10"),
        notional=Decimal("10"),
        source_signal_id="sig",
        strategy="unit",
    )

    result = PaperExecutor(config).submit(plan)

    assert result.status == ExecutionStatus.BLOCKED
    assert result.submitted_to_broker is False
