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
    ManagedAccountInfo,
)

try:
    _client_module = importlib.import_module("ibapi.client")
    _wrapper_module = importlib.import_module("ibapi.wrapper")
    _IBAPI_IMPORT_ERROR: BaseException | None = None
    _IBAPI_ECLIENT: Any = _client_module.EClient
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
    _IBAPI_EWRAPPER = _MissingEWrapper


IBKR_PORT_NOTES = {
    "tws_paper": 7497,
    "tws_live_disabled": 7496,
    "ib_gateway_paper": 4002,
    "ib_gateway_live_disabled": 4001,
}

_INFORMATIONAL_ERROR_CODES = {2104, 2106, 2158}
_ACCOUNT_SUMMARY_TAGS = "NetLiquidation,TotalCashValue,BuyingPower,DailyPnL"
_NO_ORDER_WARNING = "No order APIs invoked; order routing: disabled"


class ReadOnlyAppProtocol(Protocol):
    """Small protocol covering the subset of `EClient` used by this probe."""

    current_time_event: threading.Event
    managed_accounts_event: threading.Event
    account_summary_event: threading.Event
    positions_event: threading.Event
    server_time: datetime | None
    raw_server_time: int | None
    managed_accounts: list[str]
    account_summary: dict[str, dict[str, dict[str, str]]]
    positions: list[dict[str, Any]]
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


class _ReadOnlyIBKRApp(_IBAPI_EWRAPPER, _IBAPI_ECLIENT):  # type: ignore[misc]
    """IBKR API app that records read-only callbacks into thread-safe state."""

    def __init__(self) -> None:
        _IBAPI_EWRAPPER.__init__(self)
        _IBAPI_ECLIENT.__init__(self, self)
        self.current_time_event = threading.Event()
        self.managed_accounts_event = threading.Event()
        self.account_summary_event = threading.Event()
        self.positions_event = threading.Event()
        self.server_time: datetime | None = None
        self.raw_server_time: int | None = None
        self.managed_accounts: list[str] = []
        self.account_summary: dict[str, dict[str, dict[str, str]]] = {}
        self.positions: list[dict[str, Any]] = []
        self.errors: list[BrokerErrorEvent] = []
        self.warnings: list[str] = []
        self._lock = threading.Lock()

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
            else:
                self.errors.append(event)


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
            connected = bool(
                app.connect(
                    self.connection_config.host,
                    self.connection_config.port,
                    self.connection_config.client_id,
                )
            )
        except (OSError, RuntimeError) as exc:
            self._record_error(
                f"IBKR API connection failed: {exc}",
                failure_stage="socket_connect",
            )
            return self._status(ok=False, connected=False)
        finally:
            socket.setdefaulttimeout(original_timeout)

        if not connected:
            self._record_error(
                "IBKR API connection returned false",
                failure_stage="socket_connect",
            )
            return self._status(ok=False, connected=False)

        self._app = app
        self._thread = threading.Thread(
            target=app.run,
            name="ibkr-read-only-api-loop",
            daemon=True,
        )
        self._thread.start()
        time.sleep(0.05)
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
            "TWS Read-Only API setting is not directly detectable by this probe",
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

        try:
            time_probe = self.request_current_time(timeout=timeout)
            if time_probe.ok and include_managed_accounts:
                managed_accounts = self.request_managed_accounts(timeout=timeout)
            if time_probe.ok and include_account:
                account_snapshot = self.request_account_snapshot(timeout=timeout)
            if time_probe.ok and include_positions:
                positions_snapshot = self.request_positions_snapshot(timeout=timeout)
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
                    "TWS Read-Only API setting is not directly detectable by this probe",
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
            errors=errors,
            warnings=warnings,
            final_status="connected" if ok else "failed",
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


def _probe_socket(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        return None


def _first_error(errors: list[BrokerErrorEvent]) -> str | None:
    if not errors:
        return None
    return errors[0].message
