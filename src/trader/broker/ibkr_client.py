"""Read-only IBKR TWS / IB Gateway connectivity probe.

This module uses the official IBKR Python API shape when `ibapi` is installed:
an `EWrapper` subclass captures callbacks while `EClient` sends read-only
requests. It intentionally exposes no order-submission surface.
"""

from __future__ import annotations

import importlib
import importlib.util
import socket
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from trader.config import LIVE_PORTS, TraderConfig, mask_account_id
from trader.models import (
    BrokerConnectionStatus,
    BrokerDiagnosticReport,
    BrokerErrorEvent,
    BrokerTimeProbe,
    ContractResolutionResult,
    HistoricalBar,
    HistoricalDataDiagnostic,
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    HistoricalSnapshotReport,
    HistoricalSnapshotRequest,
    HistoricalSnapshotResult,
    ManagedAccountInfo,
    MarketDataDiagnosticReport,
    MarketDataRequestType,
    MarketDataTick,
    MarketDataTypeInfo,
    QuoteSnapshot,
    SpreadDiagnostic,
    utc_now,
)

try:
    _client_module = importlib.import_module("ibapi.client")
    _contract_module = importlib.import_module("ibapi.contract")
    _wrapper_module = importlib.import_module("ibapi.wrapper")
    _IBAPI_IMPORT_ERROR: BaseException | None = None
    _IBAPI_ECLIENT: Any = _client_module.EClient
    _IBAPI_CONTRACT: Any = _contract_module.Contract
    _IBAPI_EWRAPPER: Any = _wrapper_module.EWrapper
except Exception as exc:  # pragma: no cover - exercised through injected availability tests
    _IBAPI_IMPORT_ERROR = exc

    class _MissingEWrapper:
        """Fallback base that lets this module import without `ibapi`."""

    class _MissingEClient:
        """Fallback client; real use is blocked before this is instantiated."""

        def __init__(self, _wrapper: object) -> None:
            self._connected = False

        def connect(self, _host: str, _port: int, _clientId: int) -> bool:
            return False

        def disconnect(self) -> None:
            self._connected = False

        def isConnected(self) -> bool:
            return self._connected

        def run(self) -> None:
            return None

    _IBAPI_ECLIENT = _MissingEClient
    _IBAPI_CONTRACT = None
    _IBAPI_EWRAPPER = _MissingEWrapper


IBKR_PORT_NOTES = {
    "tws_paper": 7497,
    "tws_live_disabled": 7496,
    "ib_gateway_paper": 4002,
    "ib_gateway_live_disabled": 4001,
}

_INFORMATIONAL_ERROR_CODES = {2103, 2104, 2105, 2106, 2107, 2108, 2158, 10167}
_MARKET_DATA_FARM_READY_CODES = {2104}
_HISTORICAL_DATA_FARM_READY_CODES = {2106}
_SECURITY_DEFINITION_FARM_READY_CODES = {2158}
_CONTRACT_ERROR_CODES = {200}
_MARKET_DATA_PERMISSION_CODES = {354, 10167}
_ACCOUNT_SUMMARY_TAGS = "NetLiquidation,TotalCashValue,BuyingPower,DailyPnL"
_DEFAULT_HISTORICAL_DURATION = "1 D"
_DEFAULT_HISTORICAL_BAR_SIZE = "5 mins"
_DEFAULT_HISTORICAL_WHAT_TO_SHOW = "TRADES"
_HISTORICAL_PACING_DELAY_SECONDS = 0.25
_DATA_FARM_READY_WAIT_SECONDS = 5.0
_MARKET_DATA_TYPE_CODES = {
    "live": 1,
    "frozen": 2,
    "delayed": 3,
    "delayed_frozen": 4,
}
_MARKET_DATA_TYPE_BY_CODE = {
    code: name for name, code in _MARKET_DATA_TYPE_CODES.items()
}
_PRIMARY_EXCHANGE_HINTS = {
    "SPY": "ARCA",
    "QQQ": "NASDAQ",
    "AAPL": "NASDAQ",
    "MSFT": "NASDAQ",
    "NVDA": "NASDAQ",
}
_PRICE_TICK_FIELDS = {
    1: "bid",
    2: "ask",
    4: "last",
    9: "close",
    66: "bid",
    67: "ask",
    68: "last",
    75: "close",
}
_SIZE_TICK_FIELDS = {
    0: "bid_size",
    3: "ask_size",
    5: "last_size",
    69: "bid_size",
    70: "ask_size",
    71: "last_size",
}
_QUOTE_STALE_AFTER_SECONDS = 900
_NO_ORDER_WARNING = "No order APIs invoked; order routing: disabled"


class ReadOnlyAppProtocol(Protocol):
    """Small protocol covering the subset of `EClient` used by this probe."""

    connection_ready_event: threading.Event
    current_time_event: threading.Event
    managed_accounts_event: threading.Event
    account_summary_event: threading.Event
    positions_event: threading.Event
    market_data_farm_ready_event: threading.Event
    historical_data_farm_ready_event: threading.Event
    security_definition_farm_ready_event: threading.Event
    contract_details_events: dict[int, threading.Event]
    market_data_events: dict[int, threading.Event]
    historical_data_events: dict[int, threading.Event]
    server_time: datetime | None
    raw_server_time: int | None
    managed_accounts: list[str]
    account_summary: dict[str, dict[str, dict[str, str]]]
    positions: list[dict[str, Any]]
    contract_details: dict[int, list[Any]]
    market_data_types: dict[int, int]
    quote_ticks: dict[int, list[MarketDataTick]]
    quote_values: dict[int, dict[str, Decimal]]
    quote_timestamps: dict[int, datetime]
    historical_bars: dict[int, list[HistoricalBar]]
    historical_ranges: dict[int, tuple[str | None, str | None]]
    errors: list[BrokerErrorEvent]
    warnings: list[str]

    def connect(self, host: str, port: int, clientId: int) -> bool:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def isConnected(self) -> bool:
        raise NotImplementedError

    def run(self) -> None:
        raise NotImplementedError

    def reqCurrentTime(self) -> None:
        raise NotImplementedError

    def reqManagedAccts(self) -> None:
        raise NotImplementedError

    def reqAccountSummary(self, reqId: int, groupName: str, tags: str) -> None:
        raise NotImplementedError

    def reqPositions(self) -> None:
        raise NotImplementedError

    def reqContractDetails(self, reqId: int, contract: object) -> None:
        raise NotImplementedError

    def reqMarketDataType(self, marketDataType: int) -> None:
        raise NotImplementedError

    def reqMktData(
        self,
        reqId: int,
        contract: object,
        genericTickList: str,
        snapshot: bool,
        regulatorySnapshot: bool,
        mktDataOptions: list[Any],
    ) -> None:
        raise NotImplementedError

    def cancelMktData(self, reqId: int) -> None:
        raise NotImplementedError

    def reqHistoricalData(
        self,
        reqId: int,
        contract: object,
        endDateTime: str,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: int,
        formatDate: int,
        keepUpToDate: bool,
        chartOptions: list[Any],
    ) -> None:
        raise NotImplementedError

    def cancelHistoricalData(self, reqId: int) -> None:
        raise NotImplementedError


class _ReadOnlyIBKRApp(_IBAPI_EWRAPPER, _IBAPI_ECLIENT):  # type: ignore[misc]
    """IBKR API app that records read-only callbacks into thread-safe state."""

    def __init__(self) -> None:
        _IBAPI_EWRAPPER.__init__(self)
        _IBAPI_ECLIENT.__init__(self, self)
        self.connection_ready_event = threading.Event()
        self.current_time_event = threading.Event()
        self.managed_accounts_event = threading.Event()
        self.account_summary_event = threading.Event()
        self.positions_event = threading.Event()
        self.market_data_farm_ready_event = threading.Event()
        self.historical_data_farm_ready_event = threading.Event()
        self.security_definition_farm_ready_event = threading.Event()
        self.server_time: datetime | None = None
        self.raw_server_time: int | None = None
        self.managed_accounts: list[str] = []
        self.account_summary: dict[str, dict[str, dict[str, str]]] = {}
        self.positions: list[dict[str, Any]] = []
        self.contract_details_events: dict[int, threading.Event] = {}
        self.market_data_events: dict[int, threading.Event] = {}
        self.historical_data_events: dict[int, threading.Event] = {}
        self.contract_details: dict[int, list[Any]] = {}
        self.market_data_types: dict[int, int] = {}
        self.quote_ticks: dict[int, list[MarketDataTick]] = {}
        self.quote_values: dict[int, dict[str, Decimal]] = {}
        self.quote_timestamps: dict[int, datetime] = {}
        self.historical_bars: dict[int, list[HistoricalBar]] = {}
        self.historical_ranges: dict[int, tuple[str | None, str | None]] = {}
        self.errors: list[BrokerErrorEvent] = []
        self.warnings: list[str] = []
        self._lock = threading.Lock()

    def connectAck(self) -> None:  # noqa: N802 - IBKR callback name
        self.connection_ready_event.set()

    def nextValidId(self, _orderId: int) -> None:  # noqa: N802 - IBKR callback name
        self.connection_ready_event.set()

    def currentTime(self, time_: int) -> None:  # noqa: N802 - IBKR callback name
        with self._lock:
            self.raw_server_time = time_
            self.server_time = datetime.fromtimestamp(time_, tz=UTC)
        self.current_time_event.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802 - IBKR callback name
        accounts = [account.strip() for account in accountsList.split(",") if account.strip()]
        with self._lock:
            self.managed_accounts = accounts
        self.managed_accounts_event.set()

    def accountSummary(  # noqa: N802 - IBKR callback name
        self,
        reqId: int,
        account: str,
        tag: str,
        value: str,
        currency: str,
    ) -> None:
        with self._lock:
            account_bucket = self.account_summary.setdefault(account, {})
            account_bucket[tag] = {"value": value, "currency": currency, "req_id": str(reqId)}

    def accountSummaryEnd(self, _reqId: int) -> None:  # noqa: N802 - IBKR callback name
        self.account_summary_event.set()

    def position(  # noqa: N802 - IBKR callback name
        self,
        account: str,
        contract: object,
        position: Decimal | float | int,
        avgCost: float,
    ) -> None:
        symbol = str(getattr(contract, "symbol", "") or "")
        with self._lock:
            self.positions.append(
                {
                    "account_id_masked": mask_account_id(account),
                    "symbol": symbol,
                    "position": str(position),
                    "average_cost": str(avgCost),
                }
            )

    def positionEnd(self) -> None:  # noqa: N802 - IBKR callback name
        self.positions_event.set()

    def contractDetails(self, reqId: int, contractDetails: object) -> None:  # noqa: N802
        with self._lock:
            self.contract_details.setdefault(reqId, []).append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.contract_details_events.setdefault(reqId, threading.Event()).set()

    def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802
        with self._lock:
            self.market_data_types[reqId] = marketDataType
        self.market_data_events.setdefault(reqId, threading.Event()).set()

    def tickPrice(  # noqa: N802 - IBKR callback name
        self,
        reqId: int,
        tickType: int,
        price: float,
        _attrib: object,
    ) -> None:
        field = _PRICE_TICK_FIELDS.get(tickType)
        if field is None or price <= 0:
            return
        timestamp = utc_now()
        value = Decimal(str(price))
        with self._lock:
            self.quote_values.setdefault(reqId, {})[field] = value
            self.quote_timestamps[reqId] = timestamp
            self.quote_ticks.setdefault(reqId, []).append(
                MarketDataTick(
                    symbol="",
                    req_id=reqId,
                    tick_type=tickType,
                    field=field,
                    value=value,
                    timestamp=timestamp,
                )
            )
        self.market_data_events.setdefault(reqId, threading.Event()).set()

    def tickSize(self, reqId: int, tickType: int, size: Decimal | float | int) -> None:  # noqa: N802
        field = _SIZE_TICK_FIELDS.get(tickType)
        if field is None:
            return
        timestamp = utc_now()
        value = Decimal(str(size))
        with self._lock:
            self.quote_values.setdefault(reqId, {})[field] = value
            self.quote_timestamps[reqId] = timestamp
            self.quote_ticks.setdefault(reqId, []).append(
                MarketDataTick(
                    symbol="",
                    req_id=reqId,
                    tick_type=tickType,
                    field=field,
                    value=value,
                    timestamp=timestamp,
                )
            )
        self.market_data_events.setdefault(reqId, threading.Event()).set()

    def tickString(self, reqId: int, tickType: int, value: str) -> None:  # noqa: N802
        with self._lock:
            self.quote_ticks.setdefault(reqId, []).append(
                MarketDataTick(
                    symbol="",
                    req_id=reqId,
                    tick_type=tickType,
                    field="string",
                    value=value,
                    timestamp=utc_now(),
                )
            )

    def historicalData(self, reqId: int, bar: object) -> None:  # noqa: N802
        symbol = ""
        volume_raw = getattr(bar, "volume", None)
        wap_raw = getattr(bar, "wap", None)
        bar_count_raw = getattr(bar, "barCount", None)
        with self._lock:
            self.historical_bars.setdefault(reqId, []).append(
                HistoricalBar(
                    symbol=symbol,
                    timestamp=str(getattr(bar, "date", "")),
                    open=Decimal(str(getattr(bar, "open", "0"))),
                    high=Decimal(str(getattr(bar, "high", "0"))),
                    low=Decimal(str(getattr(bar, "low", "0"))),
                    close=Decimal(str(getattr(bar, "close", "0"))),
                    volume=Decimal(str(volume_raw)) if volume_raw is not None else None,
                    wap=Decimal(str(wap_raw)) if wap_raw is not None else None,
                    bar_count=int(bar_count_raw) if bar_count_raw is not None else None,
                )
            )

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        with self._lock:
            self.historical_ranges[reqId] = (start, end)
        self.historical_data_events.setdefault(reqId, threading.Event()).set()

    def connectionClosed(self) -> None:  # noqa: N802
        with self._lock:
            self.warnings.append("IBKR connection closed")
        self._release_pending_request_events()

    def error(  # noqa: N802 - IBKR callback name
        self,
        reqId: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        message = errorString
        if advancedOrderRejectJson:
            message = f"{message} ({advancedOrderRejectJson})"
        event = BrokerErrorEvent(req_id=reqId, code=errorCode, message=message)
        with self._lock:
            if errorCode in _INFORMATIONAL_ERROR_CODES:
                self.warnings.append(f"IBKR {errorCode}: {message}")
                self._mark_data_farm_ready(errorCode)
            else:
                self.errors.append(event)
        if errorCode not in _INFORMATIONAL_ERROR_CODES:
            self._release_pending_request_events(reqId)

    def _mark_data_farm_ready(self, error_code: int) -> None:
        if error_code in _MARKET_DATA_FARM_READY_CODES:
            self.market_data_farm_ready_event.set()
        if error_code in _HISTORICAL_DATA_FARM_READY_CODES:
            self.historical_data_farm_ready_event.set()
        if error_code in _SECURITY_DEFINITION_FARM_READY_CODES:
            self.security_definition_farm_ready_event.set()

    def _release_pending_request_events(self, req_id: int | None = None) -> None:
        with self._lock:
            event_maps = (
                self.contract_details_events,
                self.market_data_events,
                self.historical_data_events,
            )
            if req_id is None or req_id < 0:
                events = [event for event_map in event_maps for event in event_map.values()]
            else:
                events = [
                    event
                    for event_map in event_maps
                    if (event := event_map.get(req_id)) is not None
                ]
        for event in events:
            event.set()


@dataclass(frozen=True)
class IBKRConnectionConfig:
    """Safe connection parameters for the local IBKR desktop API socket."""

    host: str
    port: int
    client_id: int
    mode: str
    broker_kind: str
    connect_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_trader_config(cls, config: TraderConfig) -> IBKRConnectionConfig:
        return cls(
            host=config.ibkr_host,
            port=config.ibkr_port,
            client_id=config.ibkr_client_id,
            mode=config.trading_mode.value,
            broker_kind=config.inferred_broker_kind,
            connect_timeout_seconds=config.ibkr_connect_timeout_seconds,
            request_timeout_seconds=config.ibkr_request_timeout_seconds,
        )


class IBKRClient:
    """Read-only IBKR adapter for diagnostics and harmless broker state reads."""

    def __init__(
        self,
        config: TraderConfig,
        *,
        app_factory: Callable[[], ReadOnlyAppProtocol] | None = None,
        socket_probe: Callable[[str, int, float], None] | None = None,
        ibapi_available: bool | None = None,
    ) -> None:
        self.config = config
        self.connection_config = IBKRConnectionConfig.from_trader_config(config)
        self._app_factory = app_factory or (lambda: cast(ReadOnlyAppProtocol, _ReadOnlyIBKRApp()))
        self._socket_probe = socket_probe or _probe_socket
        self._ibapi_available_override = ibapi_available
        self._app: ReadOnlyAppProtocol | None = None
        self._thread: threading.Thread | None = None
        self._client_errors: list[BrokerErrorEvent] = []
        self._client_warnings: list[str] = []
        self._connection_attempted = False
        self._failure_stage: str | None = None
        self._request_id = 10_000
        self._request_id_lock = threading.Lock()

    @staticmethod
    def ibapi_available() -> bool:
        """Return whether the official `ibapi` package is importable."""

        return _IBAPI_IMPORT_ERROR is None and importlib.util.find_spec("ibapi") is not None

    @staticmethod
    def ibapi_import_error() -> str | None:
        """Return a safe import error string when `ibapi` is unavailable."""

        if _IBAPI_IMPORT_ERROR is not None:
            return str(_IBAPI_IMPORT_ERROR)
        if importlib.util.find_spec("ibapi") is None:
            return "No module named 'ibapi'"
        return None

    @property
    def ibapi_is_available(self) -> bool:
        """Instance-level availability, injectable for tests."""

        if self._ibapi_available_override is not None:
            return self._ibapi_available_override
        return self.ibapi_available()

    def connect(self, *, timeout: float | None = None) -> BrokerConnectionStatus:
        """Connect to TWS or IB Gateway without requesting or submitting orders."""

        connect_timeout = timeout or self.connection_config.connect_timeout_seconds

        if not self.ibapi_is_available:
            self._record_error(
                "ibapi is not installed. Install with "
                '`python -m pip install -e ".[dev,broker]"`.',
                failure_stage="dependency_check",
            )
            return self._status(ok=False, connected=False)

        if self.connection_config.port in LIVE_PORTS:
            self._record_error(
                "configured port is a live IBKR port and is disabled",
                failure_stage="config_validation",
            )
            return self._status(ok=False, connected=False)

        if self.is_connected():
            return self._status(ok=True, connected=True)

        self._connection_attempted = True
        try:
            self._socket_probe(
                self.connection_config.host,
                self.connection_config.port,
                connect_timeout,
            )
        except OSError as exc:
            self._record_error(
                "socket unavailable; confirm TWS/Gateway is running, API socket "
                f"clients are enabled, and port {self.connection_config.port} is correct: {exc}",
                failure_stage="socket_connect",
            )
            return self._status(ok=False, connected=False)

        app = self._app_factory()
        original_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(connect_timeout)
        try:
            connect_result = app.connect(
                self.connection_config.host,
                self.connection_config.port,
                self.connection_config.client_id,
            )
        except (OSError, RuntimeError) as exc:
            with suppress(OSError, RuntimeError):
                app.disconnect()
            self._record_error(
                f"IBKR API connection failed: {exc}",
                failure_stage="socket_connect",
            )
            return self._status(ok=False, connected=False)
        finally:
            socket.setdefaulttimeout(original_timeout)

        self._app = app
        self._thread = threading.Thread(
            target=app.run,
            name="ibkr-read-only-api-loop",
            daemon=True,
        )
        self._thread.start()

        try:
            ready = self._wait_for_connection_ready(app, connect_timeout)
        except KeyboardInterrupt:
            self._record_error(
                "IBKR API connection interrupted by keyboard",
                failure_stage="unknown",
            )
            self.disconnect()
            raise

        if not ready:
            message = (
                "IBKR API connection did not become ready after "
                f"{connect_timeout:g} seconds"
            )
            if connect_result is False:
                message = (
                    "IBKR API connect returned false and no readiness callback "
                    f"arrived after {connect_timeout:g} seconds"
                )
            self._record_error(message, failure_stage="timeout")
            self.disconnect()
            return self._status(ok=False, connected=False)

        return self._status(ok=True, connected=self.is_connected())

    def disconnect(self) -> None:
        """Disconnect the IBKR socket and stop the background loop if present."""

        app = self._app
        if app is None:
            return
        try:
            app.disconnect()
        except (OSError, RuntimeError) as exc:
            self._record_error(f"disconnect failed: {exc}", failure_stage="unknown")
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1)
        self._app = None
        self._thread = None

    def is_connected(self) -> bool:
        """Return whether the IBKR API client currently reports connected."""

        if self._app is None:
            return False
        try:
            return bool(self._app.isConnected())
        except RuntimeError:
            return False

    def request_current_time(self, *, timeout: float | None = None) -> BrokerTimeProbe:
        """Request current server time, a harmless read-only API call."""

        request_timeout = timeout or self.connection_config.request_timeout_seconds
        status = self.connect(timeout=timeout)
        if not status.connected:
            return BrokerTimeProbe(ok=False, error=_first_error(status.errors))

        app = self._require_app()
        app.current_time_event.clear()
        start = time.monotonic()
        try:
            app.reqCurrentTime()
        except RuntimeError as exc:
            message = f"current-time request failed: {exc}"
            self._record_error(message, failure_stage="current_time_request")
            return BrokerTimeProbe(ok=False, error=message)

        if not app.current_time_event.wait(request_timeout):
            message = f"current-time request timed out after {request_timeout:g} seconds"
            self._record_error(message, failure_stage="timeout")
            return BrokerTimeProbe(ok=False, error=message)

        latency_ms = round((time.monotonic() - start) * 1000, 2)
        return BrokerTimeProbe(
            ok=app.server_time is not None,
            server_time=app.server_time,
            raw_server_time=app.raw_server_time,
            latency_ms=latency_ms,
            error=None if app.server_time is not None else "current-time callback had no timestamp",
        )

    def request_managed_accounts(self, *, timeout: float | None = None) -> list[ManagedAccountInfo]:
        """Request managed account IDs and return masked identifiers only."""

        request_timeout = timeout or self.connection_config.request_timeout_seconds
        status = self.connect(timeout=timeout)
        if not status.connected:
            return []

        app = self._require_app()
        app.managed_accounts_event.clear()
        try:
            app.reqManagedAccts()
        except RuntimeError as exc:
            self._record_error(
                f"managed-account request failed: {exc}",
                failure_stage="managed_accounts_request",
            )
            return []

        if not app.managed_accounts_event.wait(request_timeout):
            self._record_error(
                f"managed-account request timed out after {request_timeout:g} seconds",
                failure_stage="timeout",
            )
            return []

        return [
            ManagedAccountInfo(account_id_masked=masked)
            for account in app.managed_accounts
            if (masked := mask_account_id(account)) is not None
        ]

    def request_account_snapshot(self, *, timeout: float | None = None) -> dict[str, Any] | None:
        """Request a small read-only account summary snapshot."""

        request_timeout = timeout or self.connection_config.request_timeout_seconds
        status = self.connect(timeout=timeout)
        if not status.connected:
            return None

        app = self._require_app()
        app.account_summary_event.clear()
        try:
            app.reqAccountSummary(9001, "All", _ACCOUNT_SUMMARY_TAGS)
        except RuntimeError as exc:
            self._record_error(f"account-summary request failed: {exc}", failure_stage="unknown")
            return None

        if not app.account_summary_event.wait(request_timeout):
            self._record_error(
                f"account-summary request timed out after {request_timeout:g} seconds",
                failure_stage="timeout",
            )
            return None

        return {
            mask_account_id(account) or "masked": tags
            for account, tags in app.account_summary.items()
        }

    def request_positions_snapshot(self, *, timeout: float | None = None) -> list[dict[str, Any]]:
        """Request a read-only positions snapshot."""

        request_timeout = timeout or self.connection_config.request_timeout_seconds
        status = self.connect(timeout=timeout)
        if not status.connected:
            return []

        app = self._require_app()
        app.positions_event.clear()
        try:
            app.reqPositions()
        except RuntimeError as exc:
            self._record_error(f"positions request failed: {exc}", failure_stage="unknown")
            return []

        if not app.positions_event.wait(request_timeout):
            self._record_error(
                f"positions request timed out after {request_timeout:g} seconds",
                failure_stage="timeout",
            )
            return []

        return list(app.positions)

    def resolve_contract(
        self,
        symbol: str,
        *,
        timeout: float | None = None,
    ) -> ContractResolutionResult:
        """Resolve a SMART/USD stock contract without requesting orders."""

        status = self.connect(timeout=timeout)
        if not status.connected:
            return ContractResolutionResult(
                symbol=symbol.strip().upper(),
                resolved=False,
                errors=list(status.errors),
                warnings=list(status.warnings),
            )

        app = self._require_app()
        _contract, result = self._resolve_contract_connected(
            app,
            symbol.strip().upper(),
            timeout=timeout,
        )
        return result

    def request_quote_snapshot(
        self,
        symbols: list[str],
        *,
        market_data_type: MarketDataRequestType = MarketDataRequestType.DELAYED,
        timeout: float | None = None,
    ) -> list[QuoteSnapshot]:
        """Request read-only quote snapshots for symbols."""

        status = self.connect(timeout=timeout)
        if not status.connected:
            return []

        app = self._require_app()
        quotes: list[QuoteSnapshot] = []
        for symbol in symbols:
            contract, resolution = self._resolve_contract_connected(
                app,
                symbol.strip().upper(),
                timeout=timeout,
            )
            if contract is None or not resolution.resolved:
                continue
            quote, _spread = self._request_quote_snapshot_connected(
                app,
                symbol.strip().upper(),
                contract,
                market_data_type=market_data_type,
                timeout=timeout,
            )
            quotes.append(quote)
        return quotes

    def request_historical_bars(
        self,
        symbol: str,
        *,
        timeout: float | None = None,
    ) -> HistoricalDataDiagnostic:
        """Request a small read-only historical bars sample for one symbol."""

        status = self.connect(timeout=timeout)
        if not status.connected:
            return HistoricalDataDiagnostic(
                symbol=symbol.strip().upper(),
                requested=False,
                ok=False,
                errors=list(status.errors),
                warnings=list(status.warnings),
            )

        app = self._require_app()
        contract, resolution = self._resolve_contract_connected(
            app,
            symbol.strip().upper(),
            timeout=timeout,
        )
        if contract is None or not resolution.resolved:
            return HistoricalDataDiagnostic(
                symbol=symbol.strip().upper(),
                requested=False,
                ok=False,
                errors=list(resolution.errors),
                warnings=list(resolution.warnings),
            )
        return self._request_historical_bars_connected(
            app,
            symbol.strip().upper(),
            contract,
            timeout=timeout,
        )

    def request_historical_snapshot(
        self,
        symbol: str,
        *,
        duration: str = _DEFAULT_HISTORICAL_DURATION,
        bar_size: str = _DEFAULT_HISTORICAL_BAR_SIZE,
        what_to_show: str = _DEFAULT_HISTORICAL_WHAT_TO_SHOW,
        use_rth: int = 1,
        timeout: float | None = None,
    ) -> HistoricalSnapshotResult:
        """Request one bounded read-only historical snapshot."""

        report = self.request_historical_snapshots(
            [symbol],
            duration=duration,
            bar_size=bar_size,
            what_to_show=what_to_show,
            use_rth=use_rth,
            timeout=timeout,
        )
        if report.results:
            return report.results[0]
        request_timeout = timeout or self.connection_config.request_timeout_seconds
        request = HistoricalSnapshotRequest(
            symbols=[symbol],
            duration=duration,
            bar_size=bar_size,
            what_to_show=what_to_show,
            use_rth=use_rth,
            timeout_seconds=request_timeout,
        )
        return HistoricalSnapshotResult(
            symbol=symbol.strip().upper(),
            request=request,
            ok=False,
            errors=list(report.errors),
            warnings=list(report.warnings),
        )

    def request_historical_snapshots(
        self,
        symbols: list[str],
        *,
        duration: str = _DEFAULT_HISTORICAL_DURATION,
        bar_size: str = _DEFAULT_HISTORICAL_BAR_SIZE,
        what_to_show: str = _DEFAULT_HISTORICAL_WHAT_TO_SHOW,
        use_rth: int = 1,
        timeout: float | None = None,
    ) -> HistoricalSnapshotReport:
        """Request bounded read-only historical snapshots for symbols."""

        self._clear_events()
        request_timeout = timeout or self.connection_config.request_timeout_seconds
        normalized_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        request = HistoricalSnapshotRequest(
            symbols=normalized_symbols,
            duration=duration,
            bar_size=bar_size,
            what_to_show=what_to_show,
            use_rth=use_rth,
            timeout_seconds=request_timeout,
        )
        results: list[HistoricalSnapshotResult] = []
        connected_before_disconnect = False

        try:
            status = self.connect(timeout=timeout)
            if not status.connected:
                return self._historical_snapshot_report(
                    ok=False,
                    connected=False,
                    request=request,
                    results=[],
                    final_status="failed",
                    errors=list(status.errors),
                    warnings=list(status.warnings),
                )

            app = self._require_app()
            for index, symbol in enumerate(normalized_symbols):
                contract, resolution = self._resolve_contract_connected(
                    app,
                    symbol,
                    timeout=timeout,
                )
                if contract is None or not resolution.resolved:
                    results.append(
                        HistoricalSnapshotResult(
                            symbol=symbol,
                            request=request,
                            contract_resolution=resolution,
                            ok=False,
                            errors=list(resolution.errors),
                            warnings=list(resolution.warnings),
                        )
                    )
                else:
                    results.append(
                        self._request_historical_snapshot_connected(
                            app,
                            symbol,
                            contract,
                            resolution,
                            request=request,
                            timeout=timeout,
                        )
                    )
                if index < len(normalized_symbols) - 1:
                    time.sleep(_HISTORICAL_PACING_DELAY_SECONDS)
        except KeyboardInterrupt:
            self._record_error(
                "historical snapshot interrupted by keyboard",
                failure_stage="unknown",
            )
        finally:
            self._collect_app_events()
            connected_before_disconnect = self.is_connected()
            self.disconnect()

        errors = list(self._client_errors)
        warnings = list(
            dict.fromkeys(
                [
                    *self._client_warnings,
                    *[warning for item in results for warning in item.warnings],
                    "IBKR Read-Only API setting is not directly detectable by this probe",
                    _NO_ORDER_WARNING,
                ]
            )
        )
        ok_any = any(result.ok for result in results)
        ok_all = bool(results) and all(result.ok for result in results)
        final_status = "connected" if ok_all and not errors else "partial" if ok_any else "failed"
        return self._historical_snapshot_report(
            ok=ok_any,
            connected=connected_before_disconnect,
            request=request,
            results=results,
            final_status=final_status,
            errors=errors,
            warnings=warnings,
        )

    def market_data_diagnostic(
        self,
        symbols: list[str],
        *,
        market_data_type: MarketDataRequestType = MarketDataRequestType.DELAYED,
        include_historical: bool = False,
        timeout: float | None = None,
    ) -> MarketDataDiagnosticReport:
        """Run a read-only contract, quote, spread, and optional historical diagnostic."""

        self._clear_events()
        normalized_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        contract_resolutions: list[ContractResolutionResult] = []
        quote_snapshots: list[QuoteSnapshot] = []
        spread_diagnostics: list[SpreadDiagnostic] = []
        historical_data: list[HistoricalDataDiagnostic] = []
        connected_before_disconnect = False

        try:
            status = self.connect(timeout=timeout)
            if not status.connected:
                return self._market_data_report(
                    ok=False,
                    connected=False,
                    symbols=normalized_symbols,
                    market_data_type=market_data_type,
                    include_historical=include_historical,
                    final_status="failed",
                    errors=list(status.errors),
                    warnings=list(status.warnings),
                )

            app = self._require_app()
            for symbol in normalized_symbols:
                contract, resolution = self._resolve_contract_connected(
                    app,
                    symbol,
                    timeout=timeout,
                )
                contract_resolutions.append(resolution)
                if contract is None or not resolution.resolved:
                    continue

                quote, spread = self._request_quote_snapshot_connected(
                    app,
                    symbol,
                    contract,
                    market_data_type=market_data_type,
                    timeout=timeout,
                )
                quote_snapshots.append(quote)
                spread_diagnostics.append(spread)

                if include_historical:
                    historical_data.append(
                        self._request_historical_bars_connected(
                            app,
                            symbol,
                            contract,
                            timeout=timeout,
                        )
                    )
        except KeyboardInterrupt:
            self._record_error("market-data probe interrupted by keyboard", failure_stage="unknown")
        finally:
            self._collect_app_events()
            connected_before_disconnect = self.is_connected()
            self.disconnect()

        errors = list(self._client_errors)
        warnings = list(
            dict.fromkeys(
                [
                    *self._client_warnings,
                    *[
                        warning
                        for item in contract_resolutions
                        for warning in item.warnings
                    ],
                    *[warning for item in quote_snapshots for warning in item.warnings],
                    *[warning for item in spread_diagnostics for warning in item.warnings],
                    *[warning for item in historical_data for warning in item.warnings],
                    "IBKR Read-Only API setting is not directly detectable by this probe",
                    _NO_ORDER_WARNING,
                ]
            )
        )
        resolved_any = any(item.resolved for item in contract_resolutions)
        market_data_type_any = any(
            quote.market_data_type.received_code is not None for quote in quote_snapshots
        )
        quote_any = any(
            quote.bid is not None
            or quote.ask is not None
            or quote.last is not None
            or quote.close is not None
            for quote in quote_snapshots
        )
        historical_any = any(item.ok for item in historical_data)
        ok = bool(connected_before_disconnect and resolved_any and (
            market_data_type_any or quote_any or historical_any
        ))
        final_status = "connected" if ok and not errors else "partial" if ok else "failed"

        return MarketDataDiagnosticReport(
            ok=ok,
            mode=self.connection_config.mode,
            host=self.connection_config.host,
            port=self.connection_config.port,
            client_id=self.connection_config.client_id,
            broker_kind=self.connection_config.broker_kind,
            connected=connected_before_disconnect,
            ibapi_available=self.ibapi_is_available,
            ibapi_import_error=self.ibapi_import_error(),
            connection_attempted=self._connection_attempted,
            failure_stage=self._failure_stage,
            symbols_requested=normalized_symbols,
            market_data_type_requested=market_data_type,
            market_data_type_requested_code=_MARKET_DATA_TYPE_CODES[market_data_type.value],
            include_historical=include_historical,
            contract_resolutions=contract_resolutions,
            quote_snapshots=quote_snapshots,
            spread_diagnostics=spread_diagnostics,
            historical_data=historical_data,
            ibkr_messages=[
                *errors,
                *[
                    BrokerErrorEvent(message=warning, source="ibkr_warning")
                    for warning in warnings
                    if warning.startswith("IBKR ")
                ],
            ],
            errors=errors,
            warnings=warnings,
            final_status=final_status,
        )

    def preflight(
        self,
        *,
        attempt_connection: bool = False,
        timeout: float | None = None,
    ) -> BrokerDiagnosticReport:
        """Return config and dependency diagnostics, optionally probing current time."""

        if attempt_connection:
            return self.diagnostic_report(timeout=timeout, include_managed_accounts=False)

        warnings = [
            "preflight did not open a socket; use --connect or broker-probe for a live API probe",
            "IBKR Read-Only API setting is not directly detectable by this probe",
            _NO_ORDER_WARNING,
        ]
        errors: list[BrokerErrorEvent] = []
        failure_stage: str | None = None
        if not self.ibapi_is_available:
            warnings.append(
                "ibapi is not installed. Install with `python -m pip install -e \".[dev,broker]\"`."
            )
        if self.connection_config.port in LIVE_PORTS:
            errors.append(
                BrokerErrorEvent(message="configured port is a live IBKR port and is disabled")
            )
            failure_stage = "config_validation"

        return BrokerDiagnosticReport(
            ok=not errors,
            mode=self.connection_config.mode,
            host=self.connection_config.host,
            port=self.connection_config.port,
            client_id=self.connection_config.client_id,
            broker_kind=self.connection_config.broker_kind,
            connected=False,
            ibapi_available=self.ibapi_is_available,
            ibapi_import_error=self.ibapi_import_error(),
            connection_attempted=False,
            failure_stage=failure_stage,
            errors=errors,
            warnings=warnings,
            final_status="ready_without_connection" if not errors else "blocked",
        )

    def diagnostic_report(
        self,
        *,
        timeout: float | None = None,
        include_managed_accounts: bool = True,
        include_account: bool = False,
        include_positions: bool = False,
    ) -> BrokerDiagnosticReport:
        """Run the read-only broker probe and return a structured report."""

        self._clear_events()
        time_probe: BrokerTimeProbe | None = None
        managed_accounts: list[ManagedAccountInfo] = []
        account_snapshot: dict[str, Any] | None = None
        positions_snapshot: list[dict[str, Any]] = []
        positions_query_completed = False

        try:
            time_probe = self.request_current_time(timeout=timeout)
            if time_probe.ok and include_managed_accounts:
                managed_accounts = self.request_managed_accounts(timeout=timeout)
            if time_probe.ok and include_account:
                account_snapshot = self.request_account_snapshot(timeout=timeout)
            if time_probe.ok and include_positions:
                positions_snapshot = self.request_positions_snapshot(timeout=timeout)
                app = self._app
                positions_query_completed = bool(app and app.positions_event.is_set())
        except KeyboardInterrupt:
            self._record_error("broker probe interrupted by keyboard", failure_stage="unknown")
        finally:
            self._collect_app_events()
            connected_before_disconnect = self.is_connected()
            self.disconnect()

        errors = list(self._client_errors)
        warnings = list(
            dict.fromkeys(
                [
                    *self._client_warnings,
                    "IBKR Read-Only API setting is not directly detectable by this probe",
                    _NO_ORDER_WARNING,
                ]
            )
        )
        ok = bool(time_probe and time_probe.ok and not errors)
        return BrokerDiagnosticReport(
            ok=ok,
            mode=self.connection_config.mode,
            host=self.connection_config.host,
            port=self.connection_config.port,
            client_id=self.connection_config.client_id,
            broker_kind=self.connection_config.broker_kind,
            connected=connected_before_disconnect,
            ibapi_available=self.ibapi_is_available,
            ibapi_import_error=self.ibapi_import_error(),
            connection_attempted=self._connection_attempted,
            failure_stage=self._failure_stage,
            server_time=time_probe.server_time if time_probe else None,
            time_probe=time_probe,
            managed_accounts_masked=managed_accounts,
            account_snapshot=account_snapshot,
            positions_snapshot=positions_snapshot,
            positions_query_completed=positions_query_completed,
            errors=errors,
            warnings=warnings,
            final_status="connected" if ok else "failed",
        )

    def _resolve_contract_connected(
        self,
        app: ReadOnlyAppProtocol,
        symbol: str,
        *,
        timeout: float | None = None,
    ) -> tuple[object | None, ContractResolutionResult]:
        request_timeout = timeout or self.connection_config.request_timeout_seconds
        req_id = self._next_request_id()
        event = threading.Event()
        app.contract_details_events[req_id] = event
        app.contract_details[req_id] = []
        contract = _make_stock_contract(symbol)
        primary_exchange = getattr(contract, "primaryExchange", None) or None

        if not self._wait_for_security_definition_farm_ready(app, request_timeout):
            message = (
                "security-definition farm readiness was not observed before "
                f"contract resolution for {symbol}"
            )
            self._record_error(message, req_id=req_id, failure_stage="contract_resolution")
            return None, ContractResolutionResult(
                symbol=symbol,
                primary_exchange=primary_exchange,
                resolved=False,
                errors=self._errors_for_req(req_id),
                warnings=[message],
            )

        try:
            app.reqContractDetails(req_id, contract)
        except RuntimeError as exc:
            message = f"contract resolution request failed for {symbol}: {exc}"
            self._record_error(message, req_id=req_id, failure_stage="contract_resolution")
            return None, ContractResolutionResult(
                symbol=symbol,
                primary_exchange=primary_exchange,
                resolved=False,
                errors=[BrokerErrorEvent(req_id=req_id, message=message)],
            )

        if not event.wait(request_timeout):
            self._collect_app_events()
            message = (
                f"contract resolution timed out for {symbol} "
                f"after {request_timeout:g} seconds"
            )
            self._record_error(message, req_id=req_id, failure_stage="timeout")
            return None, ContractResolutionResult(
                symbol=symbol,
                primary_exchange=primary_exchange,
                resolved=False,
                errors=self._errors_for_req(req_id),
                warnings=[message],
            )

        self._collect_app_events()
        details = list(app.contract_details.get(req_id, []))
        req_errors = self._errors_for_req(req_id)
        if not details:
            connection_closed = "IBKR connection closed" in self._client_warnings
            if connection_closed and not req_errors:
                self._record_error(
                    f"IBKR connection closed before contract details returned for {symbol}",
                    req_id=req_id,
                    failure_stage="contract_resolution",
                )
                req_errors = self._errors_for_req(req_id)
            if req_errors and self._failure_stage is None:
                self._failure_stage = "contract_resolution"
            missing_warnings = [f"no contract details returned for {symbol}"]
            if any(error.code in _CONTRACT_ERROR_CODES for error in req_errors):
                missing_warnings.append(
                    "IBKR reported no security definition for the requested contract"
                )
            return None, ContractResolutionResult(
                symbol=symbol,
                primary_exchange=primary_exchange,
                resolved=False,
                errors=req_errors,
                warnings=missing_warnings,
            )

        selected = _select_contract_details(details, primary_exchange=primary_exchange)
        selected_contract = getattr(selected, "contract", selected)
        selected_primary = str(getattr(selected_contract, "primaryExchange", "") or "") or None
        selected_exchange = str(getattr(selected_contract, "exchange", "SMART") or "SMART")
        selected_currency = str(getattr(selected_contract, "currency", "USD") or "USD")
        selected_sec_type = str(getattr(selected_contract, "secType", "STK") or "STK")
        resolution_warnings: list[str] = []
        ambiguous = len(details) > 1
        if ambiguous:
            resolution_warnings.append(
                f"{symbol} resolved to {len(details)} contracts; selected "
                f"{_contract_description(selected_contract)}"
            )

        return selected_contract, ContractResolutionResult(
            symbol=symbol,
            sec_type=selected_sec_type,
            exchange=selected_exchange,
            currency=selected_currency,
            primary_exchange=selected_primary,
            contract_id=_contract_id(selected_contract),
            resolved=True,
            ambiguous=ambiguous,
            matching_contracts=len(details),
            selected_contract_description=_contract_description(selected_contract),
            errors=req_errors,
            warnings=resolution_warnings,
        )

    def _request_quote_snapshot_connected(
        self,
        app: ReadOnlyAppProtocol,
        symbol: str,
        contract: object,
        *,
        market_data_type: MarketDataRequestType,
        timeout: float | None = None,
    ) -> tuple[QuoteSnapshot, SpreadDiagnostic]:
        request_timeout = timeout or self.connection_config.request_timeout_seconds
        req_id = self._next_request_id()
        event = threading.Event()
        app.market_data_events[req_id] = event
        app.quote_values[req_id] = {}
        app.quote_ticks[req_id] = []
        requested_code = _MARKET_DATA_TYPE_CODES[market_data_type.value]

        try:
            app.reqMarketDataType(requested_code)
            app.reqMktData(req_id, contract, "", False, False, [])
        except RuntimeError as exc:
            message = f"market-data request failed for {symbol}: {exc}"
            self._record_error(message, req_id=req_id, failure_stage="market_data_request")
            quote = self._quote_snapshot_from_app(
                app,
                symbol,
                req_id,
                market_data_type=market_data_type,
                warning=message,
            )
            return quote, _spread_for_quote(quote)

        try:
            deadline = time.monotonic() + request_timeout
            while time.monotonic() < deadline:
                values = app.quote_values.get(req_id, {})
                received_type = app.market_data_types.get(req_id)
                if received_type is not None and any(
                    key in values for key in ("bid", "ask", "last", "close")
                ):
                    break
                remaining = deadline - time.monotonic()
                event.wait(timeout=min(0.25, max(0, remaining)))
                event.clear()
        finally:
            with suppress(OSError, RuntimeError):
                app.cancelMktData(req_id)

        self._collect_app_events()
        quote = self._quote_snapshot_from_app(
            app,
            symbol,
            req_id,
            market_data_type=market_data_type,
        )
        spread = _spread_for_quote(quote)
        return quote, spread

    def _request_historical_bars_connected(
        self,
        app: ReadOnlyAppProtocol,
        symbol: str,
        contract: object,
        *,
        timeout: float | None = None,
    ) -> HistoricalDataDiagnostic:
        request_timeout = timeout or self.connection_config.request_timeout_seconds
        req_id = self._next_request_id()
        event = threading.Event()
        app.historical_data_events[req_id] = event
        app.historical_bars[req_id] = []

        try:
            app.reqHistoricalData(
                req_id,
                contract,
                "",
                _DEFAULT_HISTORICAL_DURATION,
                _DEFAULT_HISTORICAL_BAR_SIZE,
                _DEFAULT_HISTORICAL_WHAT_TO_SHOW,
                1,
                1,
                False,
                [],
            )
        except RuntimeError as exc:
            message = f"historical-data request failed for {symbol}: {exc}"
            self._record_error(message, req_id=req_id, failure_stage="historical_data_request")
            return HistoricalDataDiagnostic(
                symbol=symbol,
                requested=True,
                ok=False,
                errors=[BrokerErrorEvent(req_id=req_id, message=message)],
            )

        completed = False
        try:
            completed = event.wait(request_timeout)
        finally:
            if not completed:
                with suppress(OSError, RuntimeError):
                    app.cancelHistoricalData(req_id)

        self._collect_app_events()
        bars = [
            bar.model_copy(update={"symbol": symbol})
            for bar in app.historical_bars.get(req_id, [])
        ]
        start, end = app.historical_ranges.get(req_id, (None, None))
        warnings: list[str] = []
        errors = self._errors_for_req(req_id)
        if not completed:
            message = (
                f"historical-data request timed out for {symbol} "
                f"after {request_timeout:g} seconds"
            )
            warnings.append(message)
            self._record_error(message, req_id=req_id, failure_stage="timeout")
            errors = self._errors_for_req(req_id)
        elif not bars:
            warnings.append(f"historical-data request completed for {symbol} with no bars")

        return HistoricalDataDiagnostic(
            symbol=symbol,
            requested=True,
            ok=bool(completed and bars),
            bars=bars,
            historical_bars_count=len(bars),
            historical_start=start,
            historical_end=end,
            errors=errors,
            warnings=warnings,
        )

    def _request_historical_snapshot_connected(
        self,
        app: ReadOnlyAppProtocol,
        symbol: str,
        contract: object,
        resolution: ContractResolutionResult,
        *,
        request: HistoricalSnapshotRequest,
        timeout: float | None = None,
    ) -> HistoricalSnapshotResult:
        request_timeout = timeout or self.connection_config.request_timeout_seconds
        req_id = self._next_request_id()
        event = threading.Event()
        app.historical_data_events[req_id] = event
        app.historical_bars[req_id] = []

        try:
            app.reqHistoricalData(
                req_id,
                contract,
                "",
                request.duration,
                request.bar_size,
                request.what_to_show,
                request.use_rth,
                1,
                False,
                [],
            )
        except RuntimeError as exc:
            message = f"historical snapshot request failed for {symbol}: {exc}"
            self._record_error(message, req_id=req_id, failure_stage="historical_data_request")
            return HistoricalSnapshotResult(
                symbol=symbol,
                request=request,
                contract_resolution=resolution,
                ok=False,
                errors=[BrokerErrorEvent(req_id=req_id, message=message)],
            )

        completed = False
        try:
            completed = event.wait(request_timeout)
        finally:
            if not completed:
                with suppress(OSError, RuntimeError):
                    app.cancelHistoricalData(req_id)

        self._collect_app_events()
        errors = self._errors_for_req(req_id)
        warnings: list[str] = []
        if not completed:
            message = (
                f"historical snapshot request timed out for {symbol} "
                f"after {request_timeout:g} seconds"
            )
            warnings.append(message)
            self._record_error(message, req_id=req_id, failure_stage="timeout")
            errors = self._errors_for_req(req_id)

        source_bars = app.historical_bars.get(req_id, [])
        bars = [
            HistoricalSnapshotBar(
                symbol=symbol,
                contract_id=resolution.contract_id,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                wap=bar.wap,
                bar_count=bar.bar_count,
                duration=request.duration,
                bar_size=request.bar_size,
                what_to_show=request.what_to_show,
                use_rth=request.use_rth,
            )
            for bar in source_bars
        ]
        if completed and not bars:
            warnings.append(f"historical snapshot completed for {symbol} with no bars")

        first_bar_time = bars[0].timestamp if bars else None
        last_bar_time = bars[-1].timestamp if bars else None
        ibkr_messages = [
            *errors,
            *[
                BrokerErrorEvent(message=warning, source="ibkr_warning")
                for warning in self._client_warnings
                if warning.startswith("IBKR ")
            ],
        ]
        manifest = HistoricalSnapshotManifest(
            symbol=symbol,
            contract_id=resolution.contract_id,
            exchange=resolution.exchange,
            currency=resolution.currency,
            duration=request.duration,
            bar_size=request.bar_size,
            what_to_show=request.what_to_show,
            use_rth=request.use_rth,
            bar_count=len(bars),
            first_bar_time=first_bar_time,
            last_bar_time=last_bar_time,
            request_timeout=request_timeout,
            ibkr_messages=ibkr_messages,
            warnings=warnings,
            errors=errors,
        )
        start, end = app.historical_ranges.get(req_id, (None, None))
        return HistoricalSnapshotResult(
            symbol=symbol,
            request=request,
            contract_resolution=resolution,
            ok=bool(completed and bars and not errors),
            bars=bars,
            manifest=manifest,
            historical_start=start,
            historical_end=end,
            errors=errors,
            warnings=warnings,
        )

    def _quote_snapshot_from_app(
        self,
        app: ReadOnlyAppProtocol,
        symbol: str,
        req_id: int,
        *,
        market_data_type: MarketDataRequestType,
        warning: str | None = None,
    ) -> QuoteSnapshot:
        values = app.quote_values.get(req_id, {})
        timestamp = app.quote_timestamps.get(req_id)
        age = round((utc_now() - timestamp).total_seconds(), 2) if timestamp else None
        received_code = app.market_data_types.get(req_id)
        received_name = _MARKET_DATA_TYPE_BY_CODE.get(received_code or -1)
        warnings: list[str] = []
        if warning:
            warnings.append(warning)
        if received_code is None:
            warnings.append(f"no marketDataType callback received for {symbol}")
        if not any(key in values for key in ("bid", "ask", "last", "close")):
            warnings.append(f"no bid/ask/last/close ticks received for {symbol}")
        if "bid" not in values or "ask" not in values:
            warnings.append(f"bid/ask unavailable for {symbol}")
        if market_data_type == MarketDataRequestType.LIVE and not values:
            warnings.append("live data unavailable; retry with --data-type delayed")
        if any(
            error.code in _MARKET_DATA_PERMISSION_CODES
            for error in self._errors_for_req(req_id)
        ):
            warnings.append("IBKR reported market-data permission/subscription issue")

        stale = age is None or age > _QUOTE_STALE_AFTER_SECONDS
        ticks = [
            tick.model_copy(update={"symbol": symbol})
            for tick in app.quote_ticks.get(req_id, [])
        ]
        return QuoteSnapshot(
            symbol=symbol,
            market_data_type=MarketDataTypeInfo(
                requested=market_data_type,
                requested_code=_MARKET_DATA_TYPE_CODES[market_data_type.value],
                received=MarketDataRequestType(received_name) if received_name else None,
                received_code=received_code,
            ),
            bid=values.get("bid"),
            ask=values.get("ask"),
            last=values.get("last"),
            close=values.get("close"),
            bid_size=values.get("bid_size"),
            ask_size=values.get("ask_size"),
            last_size=values.get("last_size"),
            quote_timestamp=timestamp,
            quote_age_seconds=age,
            stale=stale,
            ticks=ticks,
            errors=self._errors_for_req(req_id),
            warnings=warnings,
        )

    def _market_data_report(
        self,
        *,
        ok: bool,
        connected: bool,
        symbols: list[str],
        market_data_type: MarketDataRequestType,
        include_historical: bool,
        final_status: str,
        errors: list[BrokerErrorEvent],
        warnings: list[str],
    ) -> MarketDataDiagnosticReport:
        return MarketDataDiagnosticReport(
            ok=ok,
            mode=self.connection_config.mode,
            host=self.connection_config.host,
            port=self.connection_config.port,
            client_id=self.connection_config.client_id,
            broker_kind=self.connection_config.broker_kind,
            connected=connected,
            ibapi_available=self.ibapi_is_available,
            ibapi_import_error=self.ibapi_import_error(),
            connection_attempted=self._connection_attempted,
            failure_stage=self._failure_stage,
            symbols_requested=symbols,
            market_data_type_requested=market_data_type,
            market_data_type_requested_code=_MARKET_DATA_TYPE_CODES[market_data_type.value],
            include_historical=include_historical,
            ibkr_messages=[
                *errors,
                *[
                    BrokerErrorEvent(message=warning, source="ibkr_warning")
                    for warning in warnings
                    if warning.startswith("IBKR ")
                ],
            ],
            errors=errors,
            warnings=list(
                dict.fromkeys(
                    [
                        *warnings,
                        "IBKR Read-Only API setting is not directly detectable by this probe",
                        _NO_ORDER_WARNING,
                    ]
                )
            ),
            final_status=final_status,
        )

    def _historical_snapshot_report(
        self,
        *,
        ok: bool,
        connected: bool,
        request: HistoricalSnapshotRequest,
        results: list[HistoricalSnapshotResult],
        final_status: str,
        errors: list[BrokerErrorEvent],
        warnings: list[str],
    ) -> HistoricalSnapshotReport:
        snapshot_paths = [
            result.snapshot_path for result in results if result.snapshot_path is not None
        ]
        manifest_paths = [
            result.manifest_path for result in results if result.manifest_path is not None
        ]
        all_warnings = list(
            dict.fromkeys(
                [
                    *warnings,
                    "IBKR Read-Only API setting is not directly detectable by this probe",
                    _NO_ORDER_WARNING,
                ]
            )
        )
        return HistoricalSnapshotReport(
            ok=ok,
            mode=self.connection_config.mode,
            host=self.connection_config.host,
            port=self.connection_config.port,
            client_id=self.connection_config.client_id,
            broker_kind=self.connection_config.broker_kind,
            connected=connected,
            ibapi_available=self.ibapi_is_available,
            ibapi_import_error=self.ibapi_import_error(),
            connection_attempted=self._connection_attempted,
            failure_stage=self._failure_stage,
            request=request,
            symbols_requested=list(request.symbols),
            results=results,
            snapshot_paths=snapshot_paths,
            manifest_paths=manifest_paths,
            ibkr_messages=[
                *errors,
                *[
                    BrokerErrorEvent(message=warning, source="ibkr_warning")
                    for warning in all_warnings
                    if warning.startswith("IBKR ")
                ],
            ],
            errors=errors,
            warnings=all_warnings,
            final_status=final_status,
        )

    def _require_app(self) -> ReadOnlyAppProtocol:
        if self._app is None:
            raise RuntimeError("IBKR app is not connected")
        return self._app

    def _status(self, *, ok: bool, connected: bool) -> BrokerConnectionStatus:
        self._collect_app_events()
        return BrokerConnectionStatus(
            ok=ok,
            mode=self.connection_config.mode,
            host=self.connection_config.host,
            port=self.connection_config.port,
            client_id=self.connection_config.client_id,
            broker_kind=self.connection_config.broker_kind,
            connected=connected,
            ibapi_available=self.ibapi_is_available,
            ibapi_import_error=self.ibapi_import_error(),
            connection_attempted=self._connection_attempted,
            failure_stage=self._failure_stage,
            errors=list(self._client_errors),
            warnings=list(dict.fromkeys(self._client_warnings)),
        )

    def _record_error(
        self,
        message: str,
        *,
        code: int | None = None,
        req_id: int | None = None,
        failure_stage: str | None = None,
    ) -> None:
        if failure_stage is not None and self._failure_stage is None:
            self._failure_stage = failure_stage
        self._client_errors.append(BrokerErrorEvent(message=message, code=code, req_id=req_id))

    def _collect_app_events(self) -> None:
        if self._app is None:
            return
        self._client_errors.extend(self._app.errors)
        self._client_warnings.extend(self._app.warnings)
        self._app.errors.clear()
        self._app.warnings.clear()

    def _clear_events(self) -> None:
        self._client_errors.clear()
        self._client_warnings.clear()
        self._connection_attempted = False
        self._failure_stage = None

    def _next_request_id(self) -> int:
        with self._request_id_lock:
            self._request_id += 1
            return self._request_id

    def _errors_for_req(self, req_id: int) -> list[BrokerErrorEvent]:
        return [error for error in self._client_errors if error.req_id in {req_id, -1}]

    def _wait_for_security_definition_farm_ready(
        self,
        app: ReadOnlyAppProtocol,
        timeout: float,
    ) -> bool:
        if app.security_definition_farm_ready_event.is_set():
            return True

        deadline = time.monotonic() + min(timeout, _DATA_FARM_READY_WAIT_SECONDS)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if app.security_definition_farm_ready_event.wait(
                timeout=min(0.05, max(0, remaining))
            ):
                self._collect_app_events()
                return True
            self._collect_app_events()

        self._collect_app_events()
        return app.security_definition_farm_ready_event.is_set()

    def _wait_for_connection_ready(
        self,
        app: ReadOnlyAppProtocol,
        timeout: float,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if app.connection_ready_event.is_set():
                self._collect_app_events()
                return True
            if self.is_connected():
                self._collect_app_events()
                return True
            remaining = deadline - time.monotonic()
            app.connection_ready_event.wait(timeout=min(0.05, max(0, remaining)))
            self._collect_app_events()

        self._collect_app_events()
        return app.connection_ready_event.is_set() or self.is_connected()


def _probe_socket(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        return None


def _first_error(errors: list[BrokerErrorEvent]) -> str | None:
    if not errors:
        return None
    return errors[0].message


def _make_stock_contract(symbol: str) -> object:
    if _IBAPI_CONTRACT is None:
        raise RuntimeError("ibapi Contract class is unavailable")
    contract = _IBAPI_CONTRACT()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    if primary_exchange := _PRIMARY_EXCHANGE_HINTS.get(symbol):
        contract.primaryExchange = primary_exchange
    return contract


def _select_contract_details(details: list[Any], *, primary_exchange: str | None) -> Any:
    def score(detail: Any) -> tuple[int, int, int, int]:
        contract = getattr(detail, "contract", detail)
        sec_type = str(getattr(contract, "secType", "") or "")
        currency = str(getattr(contract, "currency", "") or "")
        exchange = str(getattr(contract, "exchange", "") or "")
        selected_primary = str(getattr(contract, "primaryExchange", "") or "")
        return (
            1 if sec_type == "STK" else 0,
            1 if currency == "USD" else 0,
            1 if primary_exchange and selected_primary == primary_exchange else 0,
            1 if exchange == "SMART" else 0,
        )

    return sorted(details, key=score, reverse=True)[0]


def _contract_id(contract: object) -> int | None:
    raw_con_id = getattr(contract, "conId", None)
    if raw_con_id is None:
        return None
    try:
        con_id = int(raw_con_id)
    except (TypeError, ValueError):
        return None
    return con_id if con_id > 0 else None


def _contract_description(contract: object) -> str:
    pieces = [
        str(getattr(contract, "symbol", "") or "unknown"),
        str(getattr(contract, "secType", "") or "unknown"),
        str(getattr(contract, "exchange", "") or "unknown"),
        str(getattr(contract, "primaryExchange", "") or ""),
        str(getattr(contract, "currency", "") or "unknown"),
        f"conId={_contract_id(contract) or 'unknown'}",
    ]
    return " ".join(piece for piece in pieces if piece)


def _spread_for_quote(quote: QuoteSnapshot) -> SpreadDiagnostic:
    warnings: list[str] = []
    if quote.bid is None or quote.ask is None:
        warnings.append(f"spread unavailable for {quote.symbol}; bid/ask missing")
        return SpreadDiagnostic(symbol=quote.symbol, has_bid_ask=False, warnings=warnings)

    spread = quote.ask - quote.bid
    mid = (quote.ask + quote.bid) / Decimal("2")
    spread_bps = (spread / mid) * Decimal("10000") if mid > 0 else None
    if spread < 0:
        warnings.append(f"negative spread for {quote.symbol}; ask below bid")
    return SpreadDiagnostic(
        symbol=quote.symbol,
        has_bid_ask=True,
        spread=spread,
        spread_bps=spread_bps,
        warnings=warnings,
    )
