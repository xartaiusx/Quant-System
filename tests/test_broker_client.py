from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

import trader.broker.ibkr_client as ibkr_client
import trader.cli as cli
from trader.broker.ibkr_client import IBKRClient, _ReadOnlyIBKRApp
from trader.config import ENV_TO_FIELD, ConfigError, load_config
from trader.data.historical import (
    build_readiness_report,
    readiness_summary_for_snapshot,
    write_historical_snapshot_result,
)
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    BrokerDiagnosticReport,
    BrokerErrorEvent,
    ExecutionStatus,
    HistoricalBar,
    HistoricalReadinessStatus,
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    HistoricalSnapshotReport,
    HistoricalSnapshotRequest,
    HistoricalSnapshotResult,
    ManagedAccountInfo,
    MarketDataDiagnosticReport,
    MarketDataRequestType,
    MarketDataTick,
    TradeAction,
    TradePlan,
    utc_now,
)


class FakeIBAPIContract:
    """Attribute container used by broker-free unit tests."""


@pytest.fixture(autouse=True)
def use_fake_ibapi_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ibkr_client, "_IBAPI_CONTRACT", FakeIBAPIContract)


class TimeoutFakeApp:
    def __init__(self) -> None:
        self.connection_ready_event = threading.Event()
        self.current_time_event = threading.Event()
        self.managed_accounts_event = threading.Event()
        self.account_summary_event = threading.Event()
        self.positions_event = threading.Event()
        self.market_data_farm_ready_event = threading.Event()
        self.historical_data_farm_ready_event = threading.Event()
        self.security_definition_farm_ready_event = threading.Event()
        self.market_data_farm_ready_event.set()
        self.historical_data_farm_ready_event.set()
        self.security_definition_farm_ready_event.set()
        self.contract_details_events: dict[int, threading.Event] = {}
        self.market_data_events: dict[int, threading.Event] = {}
        self.historical_data_events: dict[int, threading.Event] = {}
        self.server_time = None
        self.raw_server_time = None
        self.managed_accounts: list[str] = []
        self.account_summary: dict[str, dict[str, dict[str, str]]] = {}
        self.positions: list[dict[str, Any]] = []
        self.contract_details: dict[int, list[Any]] = {}
        self.market_data_types: dict[int, int] = {}
        self.quote_ticks: dict[int, list[MarketDataTick]] = {}
        self.quote_values: dict[int, dict[str, Decimal]] = {}
        self.quote_timestamps: dict[int, datetime] = {}
        self.historical_bars: dict[int, list[HistoricalBar]] = {}
        self.historical_ranges: dict[int, tuple[str | None, str | None]] = {}
        self.errors: list[BrokerErrorEvent] = []
        self.warnings: list[str] = []
        self.connected = False
        self.current_time_requested = False
        self.requested_market_data_type: int | None = None
        self.cancelled_market_data: list[int] = []
        self.cancelled_historical_data: list[int] = []

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

    def reqContractDetails(self, reqId: int, _contract: object) -> None:
        self.contract_details_events.setdefault(reqId, threading.Event()).set()

    def reqMarketDataType(self, marketDataType: int) -> None:
        self.requested_market_data_type = marketDataType

    def reqMktData(
        self,
        reqId: int,
        _contract: object,
        _genericTickList: str,
        _snapshot: bool,
        _regulatorySnapshot: bool,
        _mktDataOptions: list[Any],
    ) -> None:
        self.market_data_events.setdefault(reqId, threading.Event()).set()

    def cancelMktData(self, reqId: int) -> None:
        self.cancelled_market_data.append(reqId)

    def reqHistoricalData(
        self,
        reqId: int,
        _contract: object,
        _endDateTime: str,
        _durationStr: str,
        _barSizeSetting: str,
        _whatToShow: str,
        _useRTH: int,
        _formatDate: int,
        _keepUpToDate: bool,
        _chartOptions: list[Any],
    ) -> None:
        self.historical_data_events.setdefault(reqId, threading.Event()).set()

    def cancelHistoricalData(self, reqId: int) -> None:
        self.cancelled_historical_data.append(reqId)


class SuccessFakeApp(TimeoutFakeApp):
    def reqCurrentTime(self) -> None:
        self.current_time_requested = True
        self.raw_server_time = 1_700_000_000
        self.server_time = datetime.fromtimestamp(self.raw_server_time, tz=UTC)
        self.current_time_event.set()

    def reqManagedAccts(self) -> None:
        self.managed_accounts = ["DUXXYYZZ99"]
        self.managed_accounts_event.set()


class FalsyConnectSuccessFakeApp(SuccessFakeApp):
    def connect(self, _host: str, _port: int, _clientId: int) -> Any:
        self.connected = False
        return None

    def run(self) -> None:
        self.connected = True
        self.connection_ready_event.set()


class NextValidIdReadyFakeApp(TimeoutFakeApp):
    def __init__(self) -> None:
        super().__init__()
        self.next_valid_id: int | None = None

    def connect(self, _host: str, _port: int, _clientId: int) -> Any:
        self.connected = False
        return None

    def nextValidId(self, order_id: int) -> None:  # noqa: N802 - mirrors IBKR callback
        self.next_valid_id = order_id
        self.connected = True
        self.connection_ready_event.set()

    def run(self) -> None:
        self.nextValidId(42)


class ConnectionTimeoutFakeApp(TimeoutFakeApp):
    def connect(self, _host: str, _port: int, _clientId: int) -> Any:
        self.connected = False
        return None


class ErrorCallbackFakeApp(SuccessFakeApp):
    def run(self) -> None:
        self.connected = True
        self.connection_ready_event.set()
        self.errors.append(
            BrokerErrorEvent(req_id=-1, code=502, message="test IBKR callback error")
        )


def contract_detail(
    *,
    symbol: str = "SPY",
    con_id: int = 1001,
    primary_exchange: str = "ARCA",
) -> SimpleNamespace:
    return SimpleNamespace(
        contract=SimpleNamespace(
            conId=con_id,
            symbol=symbol,
            secType="STK",
            exchange="SMART",
            currency="USD",
            primaryExchange=primary_exchange,
        )
    )


class MarketDataSuccessFakeApp(TimeoutFakeApp):
    def reqContractDetails(self, reqId: int, contract: object) -> None:
        symbol = str(getattr(contract, "symbol", "SPY"))
        primary = str(getattr(contract, "primaryExchange", "ARCA") or "ARCA")
        self.contract_details[reqId] = [
            contract_detail(symbol=symbol, con_id=1001, primary_exchange=primary)
        ]
        self.contract_details_events.setdefault(reqId, threading.Event()).set()

    def reqMktData(
        self,
        reqId: int,
        contract: object,
        _genericTickList: str,
        _snapshot: bool,
        _regulatorySnapshot: bool,
        _mktDataOptions: list[Any],
    ) -> None:
        symbol = str(getattr(contract, "symbol", "SPY"))
        timestamp = utc_now()
        self.market_data_types[reqId] = self.requested_market_data_type or 3
        self.quote_values[reqId] = {
            "bid": Decimal("500.10"),
            "ask": Decimal("500.20"),
            "last": Decimal("500.15"),
            "close": Decimal("499.50"),
            "bid_size": Decimal("100"),
            "ask_size": Decimal("200"),
            "last_size": Decimal("50"),
        }
        self.quote_timestamps[reqId] = timestamp
        self.quote_ticks[reqId] = [
            MarketDataTick(
                symbol=symbol,
                req_id=reqId,
                tick_type=1,
                field="bid",
                value=Decimal("500.10"),
                timestamp=timestamp,
            )
        ]
        self.market_data_events.setdefault(reqId, threading.Event()).set()

    def reqHistoricalData(
        self,
        reqId: int,
        contract: object,
        _endDateTime: str,
        _durationStr: str,
        _barSizeSetting: str,
        _whatToShow: str,
        _useRTH: int,
        _formatDate: int,
        keepUpToDate: bool,
        _chartOptions: list[Any],
    ) -> None:
        assert keepUpToDate is False
        symbol = str(getattr(contract, "symbol", "SPY"))
        self.historical_bars[reqId] = [
            HistoricalBar(
                symbol=symbol,
                timestamp="20260518  20:00:00",
                open=Decimal("499"),
                high=Decimal("501"),
                low=Decimal("498"),
                close=Decimal("500"),
                volume=Decimal("1000"),
                wap=Decimal("500.5"),
                bar_count=10,
            )
        ]
        self.historical_ranges[reqId] = ("20260518 09:30:00", "20260518 16:00:00")
        self.historical_data_events.setdefault(reqId, threading.Event()).set()


class AmbiguousContractFakeApp(MarketDataSuccessFakeApp):
    def reqContractDetails(self, reqId: int, contract: object) -> None:
        symbol = str(getattr(contract, "symbol", "SPY"))
        self.contract_details[reqId] = [
            contract_detail(symbol=symbol, con_id=1001, primary_exchange="ARCA"),
            contract_detail(symbol=symbol, con_id=1002, primary_exchange="NYSE"),
        ]
        self.contract_details_events.setdefault(reqId, threading.Event()).set()


class MissingContractFakeApp(MarketDataSuccessFakeApp):
    def reqContractDetails(self, reqId: int, _contract: object) -> None:
        self.errors.append(
            BrokerErrorEvent(req_id=reqId, code=200, message="No security definition")
        )
        self.contract_details[reqId] = []
        self.contract_details_events.setdefault(reqId, threading.Event()).set()


class ConnectionClosedContractFakeApp(MarketDataSuccessFakeApp):
    def reqContractDetails(self, reqId: int, _contract: object) -> None:
        self.connected = False
        self.warnings.append("IBKR connection closed")
        self.contract_details[reqId] = []
        self.contract_details_events.setdefault(reqId, threading.Event()).set()


class SecurityDefinitionFarmNotReadyFakeApp(MarketDataSuccessFakeApp):
    def __init__(self) -> None:
        super().__init__()
        self.security_definition_farm_ready_event.clear()
        self.contract_details_requested = False

    def reqContractDetails(self, reqId: int, contract: object) -> None:
        self.contract_details_requested = True
        super().reqContractDetails(reqId, contract)


class MissingBidAskFakeApp(MarketDataSuccessFakeApp):
    def reqMktData(
        self,
        reqId: int,
        _contract: object,
        _genericTickList: str,
        _snapshot: bool,
        _regulatorySnapshot: bool,
        _mktDataOptions: list[Any],
    ) -> None:
        self.market_data_types[reqId] = self.requested_market_data_type or 3
        self.quote_values[reqId] = {"last": Decimal("500.15")}
        self.quote_timestamps[reqId] = utc_now()
        self.market_data_events.setdefault(reqId, threading.Event()).set()


class StaleQuoteFakeApp(MarketDataSuccessFakeApp):
    def reqMktData(
        self,
        reqId: int,
        contract: object,
        genericTickList: str,
        snapshot: bool,
        regulatorySnapshot: bool,
        mktDataOptions: list[Any],
    ) -> None:
        super().reqMktData(
            reqId,
            contract,
            genericTickList,
            snapshot,
            regulatorySnapshot,
            mktDataOptions,
        )
        self.quote_timestamps[reqId] = datetime(2020, 1, 1, tzinfo=UTC)


class PermissionErrorMarketDataFakeApp(MarketDataSuccessFakeApp):
    def reqMktData(
        self,
        reqId: int,
        _contract: object,
        _genericTickList: str,
        _snapshot: bool,
        _regulatorySnapshot: bool,
        _mktDataOptions: list[Any],
    ) -> None:
        self.errors.append(
            BrokerErrorEvent(
                req_id=reqId,
                code=354,
                message="Requested market data is not subscribed",
            )
        )
        self.market_data_events.setdefault(reqId, threading.Event()).set()


class MarketDataTimeoutFakeApp(MarketDataSuccessFakeApp):
    def reqMktData(
        self,
        _reqId: int,
        _contract: object,
        _genericTickList: str,
        _snapshot: bool,
        _regulatorySnapshot: bool,
        _mktDataOptions: list[Any],
    ) -> None:
        return None


class HistoricalSnapshotTimeoutFakeApp(MarketDataSuccessFakeApp):
    def reqHistoricalData(
        self,
        _reqId: int,
        _contract: object,
        _endDateTime: str,
        _durationStr: str,
        _barSizeSetting: str,
        _whatToShow: str,
        _useRTH: int,
        _formatDate: int,
        _keepUpToDate: bool,
        _chartOptions: list[Any],
    ) -> None:
        return None


def snapshot_request(symbol: str = "SPY") -> HistoricalSnapshotRequest:
    return HistoricalSnapshotRequest(
        symbols=[symbol],
        duration="1 D",
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,
        timeout_seconds=30,
    )


def snapshot_bar(
    *,
    symbol: str = "SPY",
    timestamp: str = "20260518  09:30:00",
    open_: Decimal = Decimal("100"),
    high: Decimal = Decimal("101"),
    low: Decimal = Decimal("99"),
    close: Decimal = Decimal("100.5"),
    volume: Decimal | None = Decimal("1000"),
) -> HistoricalSnapshotBar:
    return HistoricalSnapshotBar(
        symbol=symbol,
        contract_id=1001,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        wap=Decimal("100.25"),
        bar_count=10,
        duration="1 D",
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,
    )


def snapshot_manifest(
    bars: list[HistoricalSnapshotBar],
    *,
    symbol: str = "SPY",
) -> HistoricalSnapshotManifest:
    return HistoricalSnapshotManifest(
        symbol=symbol,
        contract_id=1001,
        exchange="SMART",
        currency="USD",
        duration="1 D",
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,
        bar_count=len(bars),
        first_bar_time=bars[0].timestamp if bars else None,
        last_bar_time=bars[-1].timestamp if bars else None,
        request_timeout=30,
    )


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


def test_connect_falsy_return_succeeds_when_readiness_callback_arrives() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = FalsyConnectSuccessFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.diagnostic_report(timeout=0.1)

    assert report.ok is True
    assert report.connected is True
    assert report.server_time == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert report.failure_stage is None


def test_next_valid_id_callback_marks_connection_ready() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = NextValidIdReadyFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    status = client.connect(timeout=0.1)

    assert status.ok is True
    assert status.connected is True
    assert fake_app.next_valid_id == 42
    assert status.failure_stage is None
    client.disconnect()


def test_connection_readiness_timeout_returns_structured_failure() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = ConnectionTimeoutFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    status = client.connect(timeout=0.01)

    assert status.ok is False
    assert status.connected is False
    assert status.connection_attempted is True
    assert status.failure_stage == "timeout"
    assert status.errors
    assert "did not become ready" in status.errors[0].message


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


def test_ibkr_error_callback_is_recorded() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = ErrorCallbackFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.diagnostic_report(timeout=0.1)

    assert report.ok is False
    assert report.errors
    assert report.errors[0].code == 502
    assert report.errors[0].message == "test IBKR callback error"


def test_ibkr_farm_status_codes_are_non_fatal_warnings() -> None:
    app = _ReadOnlyIBKRApp()

    for code in (2103, 2105, 2107, 2108):
        app.error(-1, code, f"farm status {code}")

    assert app.errors == []
    assert app.warnings == [f"IBKR {code}: farm status {code}" for code in (2103, 2105, 2107, 2108)]


def test_ibkr_data_farm_ok_codes_set_readiness_events() -> None:
    app = _ReadOnlyIBKRApp()

    app.error(-1, 2104, "Market data farm connection is OK")
    app.error(-1, 2106, "HMDS data farm connection is OK")
    app.error(-1, 2158, "Sec-def data farm connection is OK")

    assert app.market_data_farm_ready_event.is_set() is True
    assert app.historical_data_farm_ready_event.is_set() is True
    assert app.security_definition_farm_ready_event.is_set() is True
    assert app.errors == []


def test_ibkr_informational_error_does_not_release_pending_request_events() -> None:
    app = _ReadOnlyIBKRApp()
    contract_event = threading.Event()
    app.contract_details_events[101] = contract_event

    app.error(-1, 2104, "Market data farm connection is OK")

    assert contract_event.is_set() is False
    assert app.errors == []
    assert app.warnings == ["IBKR 2104: Market data farm connection is OK"]


def test_ibkr_request_error_releases_matching_pending_request_event() -> None:
    app = _ReadOnlyIBKRApp()
    contract_event = threading.Event()
    market_event = threading.Event()
    app.contract_details_events[101] = contract_event
    app.market_data_events[202] = market_event

    app.error(101, 200, "No security definition has been found")

    assert contract_event.is_set() is True
    assert market_event.is_set() is False
    assert len(app.errors) == 1
    assert app.errors[0].req_id == 101
    assert app.errors[0].code == 200
    assert app.errors[0].message == "No security definition has been found"


def test_ibkr_global_request_error_releases_all_pending_request_events() -> None:
    app = _ReadOnlyIBKRApp()
    contract_event = threading.Event()
    market_event = threading.Event()
    historical_event = threading.Event()
    app.contract_details_events[101] = contract_event
    app.market_data_events[202] = market_event
    app.historical_data_events[303] = historical_event

    app.error(-1, 504, "Not connected")

    assert contract_event.is_set() is True
    assert market_event.is_set() is True
    assert historical_event.is_set() is True
    assert len(app.errors) == 1
    assert app.errors[0].req_id == -1
    assert app.errors[0].code == 504
    assert app.errors[0].message == "Not connected"


def test_ibkr_connection_closed_releases_all_pending_request_events() -> None:
    app = _ReadOnlyIBKRApp()
    contract_event = threading.Event()
    historical_event = threading.Event()
    app.contract_details_events[101] = contract_event
    app.historical_data_events[303] = historical_event

    app.connectionClosed()

    assert contract_event.is_set() is True
    assert historical_event.is_set() is True
    assert app.warnings == ["IBKR connection closed"]


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


def test_contract_resolution_success() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = MarketDataSuccessFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    result = client.resolve_contract("SPY", timeout=0.1)

    assert result.resolved is True
    assert result.contract_id == 1001
    assert result.primary_exchange == "ARCA"
    client.disconnect()


def test_contract_resolution_failure_is_structured() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = MissingContractFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    result = client.resolve_contract("BAD", timeout=0.1)

    assert result.resolved is False
    assert result.errors
    assert result.errors[0].code == 200
    assert "no security definition" in " ".join(result.warnings).lower()
    client.disconnect()


def test_contract_resolution_connection_close_is_structured_error() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = ConnectionClosedContractFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    result = client.resolve_contract("SPY", timeout=0.1)

    assert result.resolved is False
    assert result.errors
    assert result.errors[0].req_id is not None
    assert result.errors[0].req_id > 0
    assert "connection closed before contract details returned" in result.errors[0].message
    assert "no contract details returned" in " ".join(result.warnings).lower()
    client.disconnect()


def test_contract_resolution_requires_security_definition_farm_readiness() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = SecurityDefinitionFarmNotReadyFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    result = client.resolve_contract("SPY", timeout=0.01)

    assert result.resolved is False
    assert fake_app.contract_details_requested is False
    assert result.errors
    assert "security-definition farm readiness was not observed" in result.errors[0].message
    client.disconnect()


def test_multiple_contract_match_records_ambiguity_warning() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = AmbiguousContractFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    result = client.resolve_contract("SPY", timeout=0.1)

    assert result.resolved is True
    assert result.ambiguous is True
    assert result.matching_contracts == 2
    assert result.warnings
    client.disconnect()


def test_market_data_diagnostic_captures_delayed_type_ticks_spread_and_history() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = MarketDataSuccessFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.market_data_diagnostic(
        ["SPY"],
        market_data_type=MarketDataRequestType.DELAYED,
        include_historical=True,
        timeout=0.1,
    )

    assert report.ok is True
    assert report.order_routing_enabled is False
    assert report.no_order_guarantee is True
    assert report.contract_resolutions[0].resolved is True
    quote = report.quote_snapshots[0]
    assert quote.market_data_type.requested_code == 3
    assert quote.market_data_type.received_code == 3
    assert quote.bid == Decimal("500.10")
    assert quote.ask == Decimal("500.20")
    assert quote.last == Decimal("500.15")
    assert quote.close == Decimal("499.50")
    assert quote.bid_size == Decimal("100")
    assert quote.ask_size == Decimal("200")
    assert quote.last_size == Decimal("50")
    assert quote.stale is False
    assert report.spread_diagnostics[0].spread == Decimal("0.10")
    assert report.spread_diagnostics[0].spread_bps is not None
    assert report.historical_data[0].ok is True
    assert report.historical_data[0].historical_bars_count == 1
    assert fake_app.cancelled_market_data
    assert fake_app.cancelled_historical_data == []


def test_market_data_missing_bid_ask_is_warning_not_crash() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = MissingBidAskFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.market_data_diagnostic(
        ["SPY"],
        market_data_type=MarketDataRequestType.DELAYED,
        timeout=0.1,
    )

    assert report.ok is True
    assert report.quote_snapshots[0].last == Decimal("500.15")
    assert report.spread_diagnostics[0].has_bid_ask is False
    assert any("bid/ask unavailable" in warning for warning in report.warnings)


def test_stale_quote_detection() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = StaleQuoteFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.market_data_diagnostic(
        ["SPY"],
        market_data_type=MarketDataRequestType.DELAYED,
        timeout=0.1,
    )

    assert report.quote_snapshots[0].stale is True
    assert report.quote_snapshots[0].quote_age_seconds is not None


def test_market_data_timeout_returns_structured_diagnostic() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = MarketDataTimeoutFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.market_data_diagnostic(
        ["SPY"],
        market_data_type=MarketDataRequestType.DELAYED,
        timeout=0.01,
    )

    assert report.ok is False
    assert report.contract_resolutions[0].resolved is True
    assert "no marketDataType callback" in " ".join(report.warnings)
    assert "no bid/ask/last/close ticks" in " ".join(report.warnings)
    assert fake_app.cancelled_market_data


def test_market_data_permission_error_is_recorded() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = PermissionErrorMarketDataFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.market_data_diagnostic(
        ["SPY"],
        market_data_type=MarketDataRequestType.LIVE,
        timeout=0.1,
    )

    assert report.ok is False
    assert report.errors
    assert report.errors[0].code == 354
    assert any("permission" in warning for warning in report.warnings)


def test_non_fatal_farm_warnings_do_not_fail_market_probe_by_themselves() -> None:
    app = _ReadOnlyIBKRApp()

    for code in (2103, 2104, 2105, 2106, 2107, 2108, 2158, 10167):
        app.error(-1, code, f"status {code}")

    assert app.errors == []
    assert len(app.warnings) == 8


def test_market_data_report_serializes_to_json() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = MarketDataSuccessFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.market_data_diagnostic(
        ["SPY"],
        market_data_type=MarketDataRequestType.DELAYED,
        include_historical=True,
        timeout=0.1,
    )

    payload = report.model_dump(mode="json")
    assert payload["report_type"] == "market_probe"
    assert payload["quote_snapshots"][0]["bid"] == "500.10"


def test_historical_snapshot_models_serialize_to_json() -> None:
    request = snapshot_request()
    bar = snapshot_bar()
    manifest = snapshot_manifest([bar])

    assert request.model_dump(mode="json")["symbols"] == ["SPY"]
    assert bar.model_dump(mode="json")["wap"] == "100.25"
    assert manifest.model_dump(mode="json")["bar_count"] == 1


def test_historical_snapshot_collection_and_completion() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = MarketDataSuccessFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.request_historical_snapshots(["SPY"], timeout=0.1)

    assert report.ok is True
    assert report.order_routing_enabled is False
    assert report.no_order_guarantee is True
    result = report.results[0]
    assert result.ok is True
    assert len(result.bars) == 1
    assert result.bars[0].wap == Decimal("500.5")
    assert result.bars[0].bar_count == 10
    assert result.manifest is not None
    assert result.manifest.bar_count == 1
    assert fake_app.cancelled_historical_data == []


def test_historical_snapshot_timeout_returns_structured_failure_and_cleans_up() -> None:
    config = load_config(env={}, load_dotenv_file=False)
    fake_app = HistoricalSnapshotTimeoutFakeApp()
    client = IBKRClient(
        config,
        app_factory=lambda: fake_app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    report = client.request_historical_snapshots(["SPY"], timeout=0.01)

    assert report.ok is False
    assert report.final_status == "failed"
    assert report.results[0].ok is False
    assert any("timed out" in warning for warning in report.warnings)
    assert fake_app.cancelled_historical_data


def test_historical_snapshot_writer_creates_expected_paths(tmp_path: Path) -> None:
    request = snapshot_request()
    bar = snapshot_bar()
    manifest = snapshot_manifest([bar])
    result = HistoricalSnapshotResult(
        symbol="SPY",
        request=request,
        ok=True,
        bars=[bar],
        manifest=manifest,
    )

    stored = write_historical_snapshot_result(
        result,
        base_dir=tmp_path / "historical",
        timestamp_slug="20260519T010203Z",
    )

    assert stored.snapshot_path is not None
    assert stored.manifest_path is not None
    assert Path(stored.snapshot_path).exists()
    assert Path(stored.manifest_path).exists()
    assert "SPY/5_mins/TRADES/20260519T010203Z_bars.jsonl" in stored.snapshot_path


def test_readiness_detects_sorted_ready_bars() -> None:
    bars = [
        snapshot_bar(timestamp="20260518  09:30:00"),
        snapshot_bar(timestamp="20260518  09:35:00"),
    ]
    manifest = snapshot_manifest(bars)

    summary = readiness_summary_for_snapshot(manifest, bars, now=manifest.generated_at)

    assert summary.readiness_status == HistoricalReadinessStatus.READY
    assert summary.sorted_timestamps is True
    assert summary.duplicate_timestamps_count == 0


def test_readiness_detects_duplicate_timestamps() -> None:
    bars = [
        snapshot_bar(timestamp="20260518  09:30:00"),
        snapshot_bar(timestamp="20260518  09:30:00"),
    ]
    manifest = snapshot_manifest(bars)

    summary = readiness_summary_for_snapshot(manifest, bars, now=manifest.generated_at)

    assert summary.readiness_status == HistoricalReadinessStatus.PARTIAL
    assert summary.duplicate_timestamps_count == 1


def test_readiness_detects_timestamp_gaps() -> None:
    bars = [
        snapshot_bar(timestamp="20260518  09:30:00"),
        snapshot_bar(timestamp="20260518  09:45:00"),
    ]
    manifest = snapshot_manifest(bars)

    summary = readiness_summary_for_snapshot(manifest, bars, now=manifest.generated_at)

    assert summary.readiness_status == HistoricalReadinessStatus.PARTIAL
    assert summary.missing_timestamp_gaps
    assert summary.largest_gap_seconds == 900


def test_readiness_detects_invalid_ohlc() -> None:
    bars = [
        snapshot_bar(
            open_=Decimal("100"),
            high=Decimal("99"),
            low=Decimal("98"),
            close=Decimal("100"),
        )
    ]
    manifest = snapshot_manifest(bars)

    summary = readiness_summary_for_snapshot(manifest, bars, now=manifest.generated_at)

    assert summary.readiness_status == HistoricalReadinessStatus.FAILED
    assert summary.invalid_ohlc_bars == 1


def test_readiness_detects_negative_volume() -> None:
    bars = [snapshot_bar(volume=Decimal("-1"))]
    manifest = snapshot_manifest(bars)

    summary = readiness_summary_for_snapshot(manifest, bars, now=manifest.generated_at)

    assert summary.readiness_status == HistoricalReadinessStatus.FAILED
    assert summary.negative_volume_bars == 1


def test_readiness_reports_zero_volume_sample_timestamps() -> None:
    bars = [
        snapshot_bar(timestamp="20260518  09:30:00"),
        snapshot_bar(timestamp="20260518  09:35:00", volume=Decimal("0")),
    ]
    manifest = snapshot_manifest(bars)

    summary = readiness_summary_for_snapshot(manifest, bars, now=manifest.generated_at)

    assert summary.readiness_status == HistoricalReadinessStatus.PARTIAL
    assert summary.zero_volume_bars == 1
    assert summary.zero_volume_sample_timestamps == ["2026-05-18T09:35:00+00:00"]


def test_readiness_handles_empty_bars() -> None:
    manifest = snapshot_manifest([])

    summary = readiness_summary_for_snapshot(manifest, [], now=manifest.generated_at)

    assert summary.readiness_status == HistoricalReadinessStatus.FAILED
    assert "snapshot contains no bars" in summary.errors


def test_readiness_report_supports_partial_success(tmp_path: Path) -> None:
    config = load_config(env={}, load_dotenv_file=False)
    ready = HistoricalSnapshotResult(
        symbol="SPY",
        request=snapshot_request("SPY"),
        ok=True,
        bars=[snapshot_bar(symbol="SPY")],
        manifest=snapshot_manifest([snapshot_bar(symbol="SPY")], symbol="SPY"),
    )
    failed_manifest = snapshot_manifest([], symbol="BAD")
    failed = HistoricalSnapshotResult(
        symbol="BAD",
        request=snapshot_request("BAD"),
        ok=True,
        bars=[],
        manifest=failed_manifest,
    )
    stored_ready = write_historical_snapshot_result(
        ready,
        base_dir=tmp_path / "historical",
        timestamp_slug="20260519T010203Z",
    )
    failed_path = tmp_path / "historical" / "BAD" / "5_mins" / "trades"
    failed_path.mkdir(parents=True)
    failed_snapshot_path = failed_path / "20260519T010204Z_bars.jsonl"
    failed_manifest_path = failed_path / "20260519T010204Z_manifest.json"
    failed_snapshot_path.write_text("")
    failed_manifest = failed_manifest.model_copy(
        update={
            "snapshot_path": failed_snapshot_path.as_posix(),
            "manifest_path": failed_manifest_path.as_posix(),
        }
    )
    failed_manifest_path.write_text(failed_manifest.model_dump_json())
    failed = failed.model_copy(update={"manifest_path": failed_manifest_path.as_posix()})

    report = build_readiness_report(
        config,
        manifest_paths=[stored_ready.manifest_path, failed.manifest_path],
    )

    assert report.ok is True
    assert report.final_status == "partial"
    assert {summary.readiness_status for summary in report.summaries} == {
        HistoricalReadinessStatus.READY,
        HistoricalReadinessStatus.FAILED,
    }


def test_historical_reports_serialize_to_json() -> None:
    request = snapshot_request()
    bar = snapshot_bar()
    manifest = snapshot_manifest([bar])
    snapshot_report = HistoricalSnapshotReport(
        ok=True,
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=101,
        broker_kind="ib_gateway",
        connected=True,
        ibapi_available=True,
        request=request,
        results=[
            HistoricalSnapshotResult(
                symbol="SPY",
                request=request,
                ok=True,
                bars=[bar],
                manifest=manifest,
            )
        ],
        final_status="connected",
    )

    payload = snapshot_report.model_dump(mode="json")

    assert payload["report_type"] == "history_snapshot"
    assert payload["no_order_guarantee"] is True


def test_cli_preflight_runs_without_tws(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for env_name in ENV_TO_FIELD:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.chdir(tmp_path)
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


def test_market_probe_command_handles_mocked_success(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self, _config: object) -> None:
            return None

        def market_data_diagnostic(
            self,
            symbols: list[str],
            *,
            market_data_type: MarketDataRequestType = MarketDataRequestType.DELAYED,
            include_historical: bool = False,
            timeout: float | None = None,
        ) -> MarketDataDiagnosticReport:
            del timeout
            return MarketDataDiagnosticReport(
                ok=True,
                mode="paper",
                host="127.0.0.1",
                port=4002,
                client_id=101,
                broker_kind="ib_gateway",
                connected=True,
                ibapi_available=True,
                connection_attempted=True,
                symbols_requested=symbols,
                market_data_type_requested=market_data_type,
                market_data_type_requested_code=3,
                include_historical=include_historical,
                final_status="connected",
            )

    monkeypatch.setattr(cli, "IBKRClient", FakeClient)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["market-probe", "--symbols", "SPY,AAPL", "--data-type", "delayed"],
    )

    assert result.exit_code == 0
    assert "Read-only market-data probe" in result.output
    assert "No order APIs invoked" in result.output
    assert (tmp_path / "reports" / "latest_market_probe.json").exists()


def test_history_snapshot_command_handles_mocked_success(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self, _config: object) -> None:
            return None

        def request_historical_snapshots(
            self,
            symbols: list[str],
            *,
            duration: str = "1 D",
            bar_size: str = "5 mins",
            what_to_show: str = "TRADES",
            use_rth: int = 1,
            timeout: float | None = None,
        ) -> HistoricalSnapshotReport:
            del timeout
            request = HistoricalSnapshotRequest(
                symbols=symbols,
                duration=duration,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=use_rth,
                timeout_seconds=30,
            )
            bars = [snapshot_bar(symbol=symbols[0])]
            manifest = snapshot_manifest(bars, symbol=symbols[0])
            result = HistoricalSnapshotResult(
                symbol=symbols[0],
                request=request,
                ok=True,
                bars=bars,
                manifest=manifest,
            )
            return HistoricalSnapshotReport(
                ok=True,
                mode="paper",
                host="127.0.0.1",
                port=4002,
                client_id=101,
                broker_kind="ib_gateway",
                connected=True,
                ibapi_available=True,
                connection_attempted=True,
                request=request,
                symbols_requested=symbols,
                results=[result],
                final_status="connected",
            )

    monkeypatch.setattr(cli, "IBKRClient", FakeClient)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["history-snapshot", "--symbols", "SPY"],
    )

    assert result.exit_code == 0
    assert "Read-only historical snapshot" in result.output
    assert "No order APIs invoked" in result.output
    assert (tmp_path / "reports" / "latest_history_snapshot.json").exists()
    assert (tmp_path / "reports" / "latest_history_readiness.json").exists()


def test_read_only_broker_code_does_not_call_order_apis() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/broker/ibkr_client.py"),
            Path("src/trader/cli.py"),
            Path("src/trader/data/historical.py"),
            Path("scripts/run-market-probe.sh"),
            Path("scripts/run-history-snapshot.sh"),
        ]
        if path.exists()
    )

    assert "placeOrder" not in source
    assert "cancelOrder" not in source
    assert "reqGlobalCancel" not in source
    assert "exerciseOptions" not in source
    assert "replaceFA" not in source


def test_live_ports_still_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "4001"}, load_dotenv_file=False)


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
