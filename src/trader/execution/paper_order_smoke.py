"""Gated IBKR paper-order smoke executor.

This module is the only production path allowed to call the IBKR order API in
the paper-order smoke milestone. It is intentionally narrow: one SPY BUY 1 LMT
DAY paper order on localhost paper TWS or IB Gateway.
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
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol, cast

from trader.broker.ibapi_callbacks import normalize_ibkr_error_args
from trader.config import LIVE_PORTS, PAPER_PORTS, TraderConfig, TradingMode, mask_account_id
from trader.models import (
    OrderType,
    PaperOrderCallbackEvent,
    PaperOrderQuote,
    PaperOrderSmokeReport,
    PaperOrderSmokeRequest,
    PaperOrderSmokeRunStatus,
    TradeAction,
    new_campaign_id,
    utc_now,
)

try:
    _client_module = importlib.import_module("ibapi.client")
    _contract_module = importlib.import_module("ibapi.contract")
    _execution_module = importlib.import_module("ibapi.execution")
    _order_module = importlib.import_module("ibapi.order")
    _order_cancel_module = importlib.import_module("ibapi.order_cancel")
    _wrapper_module = importlib.import_module("ibapi.wrapper")
    _IBAPI_IMPORT_ERROR: BaseException | None = None
    _IBAPI_ECLIENT: Any = _client_module.EClient
    _IBAPI_CONTRACT: Any = _contract_module.Contract
    _IBAPI_EXECUTION_FILTER: Any = _execution_module.ExecutionFilter
    _IBAPI_ORDER: Any = _order_module.Order
    _IBAPI_ORDER_CANCEL: Any = _order_cancel_module.OrderCancel
    _IBAPI_EWRAPPER: Any = _wrapper_module.EWrapper
except Exception as exc:  # pragma: no cover - exercised through availability injection
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
    _IBAPI_EXECUTION_FILTER = None
    _IBAPI_ORDER = None
    _IBAPI_ORDER_CANCEL = None
    _IBAPI_EWRAPPER = _MissingEWrapper


PAPER_SMOKE_CONFIRMATION = "PAPER_SMOKE_SPY_1"
PAPER_SMOKE_SYMBOL = "SPY"
PAPER_SMOKE_PORTS = PAPER_PORTS
PAPER_SMOKE_CLIENT_ID = 21
_ACCOUNT_SUMMARY_TAGS = "NetLiquidation,TotalCashValue,BuyingPower"
_INFORMATIONAL_ERROR_CODES = {2103, 2104, 2105, 2106, 2107, 2108, 2158, 2176, 10167}
_TERMINAL_STATUSES = {"Cancelled", "ApiCancelled", "Filled", "Inactive"}
_CANCELED_STATUSES = {"Cancelled", "ApiCancelled"}
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
_NON_MARKETABLE_BUY_DISCOUNT = Decimal("0.98")
_CENT = Decimal("0.01")


class PaperOrderSmokeError(RuntimeError):
    """Raised for broker-layer paper smoke failures."""


@dataclass(frozen=True)
class PaperBrokerAccountSummary:
    """Masked account-summary evidence from the broker."""

    account_ids_masked: list[str]
    verified: bool
    warnings: list[str]
    errors: list[str]


@dataclass(frozen=True)
class PaperBrokerOpenOrder:
    """Open-order snapshot used to block duplicate paper smoke orders."""

    order_id: int
    symbol: str
    action: str | None
    status: str | None
    perm_id: int | None = None


@dataclass(frozen=True)
class PaperBrokerExecution:
    """Read-only execution row returned by broker reconciliation."""

    req_id: int
    order_id: int | None
    perm_id: int | None
    exec_id: str | None
    symbol: str | None
    side: str | None
    shares: Decimal | None
    price: Decimal | None
    time: str | None
    account_id_masked: str | None
    exchange: str | None
    cum_qty: Decimal | None
    avg_price: Decimal | None


@dataclass(frozen=True)
class PaperBrokerCommissionReport:
    """Read-only commission row returned by broker reconciliation."""

    exec_id: str | None
    commission: Decimal | None
    currency: str | None
    realized_pnl: Decimal | None
    yield_value: Decimal | None
    yield_redemption_date: int | None


@dataclass(frozen=True)
class PaperBrokerPlacementResult:
    """Order placement or cancellation evidence returned by the broker adapter."""

    order_id: int | None
    perm_id: int | None
    status: str | None
    fill_quantity: Decimal
    remaining_quantity: Decimal | None
    accepted: bool
    submitted_to_broker: bool
    canceled: bool
    terminal: bool
    callback_timeline: list[PaperOrderCallbackEvent]
    warnings: list[str]
    errors: list[str]


class PaperOrderBroker(Protocol):
    """High-level paper-order broker surface for the smoke orchestrator."""

    def connect(self, *, timeout: float) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def request_account_summary(self, *, timeout: float) -> PaperBrokerAccountSummary:
        raise NotImplementedError

    def request_open_orders(self, *, timeout: float) -> list[PaperBrokerOpenOrder]:
        raise NotImplementedError

    def request_quote(
        self,
        symbol: str,
        *,
        timeout: float,
        max_age_seconds: int,
    ) -> PaperOrderQuote:
        raise NotImplementedError

    def place_limit_order(
        self,
        *,
        symbol: str,
        action: TradeAction,
        quantity: int,
        limit_price: Decimal,
        time_in_force: str,
        transmit: bool,
        timeout: float,
    ) -> PaperBrokerPlacementResult:
        raise NotImplementedError

    def cancel_order(self, order_id: int | None, *, timeout: float) -> PaperBrokerPlacementResult:
        raise NotImplementedError


class PaperOrderAppProtocol(Protocol):
    """Subset of `EClient` and captured state used for paper-order smoke."""

    connection_ready_event: threading.Event
    next_valid_id_event: threading.Event
    managed_accounts_event: threading.Event
    account_summary_event: threading.Event
    open_order_event: threading.Event
    open_order_end_event: threading.Event
    order_event: threading.Event
    execution_details_end_event: threading.Event
    market_data_events: dict[int, threading.Event]
    contract_details_events: dict[int, threading.Event]
    next_valid_order_id: int | None
    managed_accounts: list[str]
    account_summary: dict[str, dict[str, dict[str, str]]]
    open_orders: dict[int, PaperBrokerOpenOrder]
    order_statuses: dict[int, str]
    order_perm_ids: dict[int, int]
    filled_quantities: dict[int, Decimal]
    remaining_quantities: dict[int, Decimal]
    executions: list[PaperBrokerExecution]
    commission_reports: list[PaperBrokerCommissionReport]
    quote_values: dict[int, dict[str, Decimal]]
    quote_timestamps: dict[int, Any]
    callback_events: list[PaperOrderCallbackEvent]
    errors: list[str]
    warnings: list[str]

    def connect(self, host: str, port: int, clientId: int) -> bool:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def isConnected(self) -> bool:
        raise NotImplementedError

    def run(self) -> None:
        raise NotImplementedError

    def reqManagedAccts(self) -> None:
        raise NotImplementedError

    def reqAccountSummary(self, reqId: int, groupName: str, tags: str) -> None:
        raise NotImplementedError

    def reqOpenOrders(self) -> None:
        raise NotImplementedError

    def reqExecutions(self, reqId: int, filter: object) -> None:
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

    def placeOrder(self, orderId: int, contract: object, order: object) -> None:
        raise NotImplementedError

    def cancelOrder(self, orderId: int, orderCancel: object) -> None:
        raise NotImplementedError


class _PaperOrderIBKRApp(_IBAPI_EWRAPPER, _IBAPI_ECLIENT):  # type: ignore[misc]
    """IBKR API app that records only paper-order smoke callbacks."""

    def __init__(self) -> None:
        _IBAPI_EWRAPPER.__init__(self)
        _IBAPI_ECLIENT.__init__(self, self)
        self.connection_ready_event = threading.Event()
        self.next_valid_id_event = threading.Event()
        self.managed_accounts_event = threading.Event()
        self.account_summary_event = threading.Event()
        self.open_order_event = threading.Event()
        self.open_order_end_event = threading.Event()
        self.order_event = threading.Event()
        self.execution_details_end_event = threading.Event()
        self.market_data_events: dict[int, threading.Event] = {}
        self.contract_details_events: dict[int, threading.Event] = {}
        self.next_valid_order_id: int | None = None
        self.managed_accounts: list[str] = []
        self.account_summary: dict[str, dict[str, dict[str, str]]] = {}
        self.open_orders: dict[int, PaperBrokerOpenOrder] = {}
        self.order_statuses: dict[int, str] = {}
        self.order_perm_ids: dict[int, int] = {}
        self.filled_quantities: dict[int, Decimal] = {}
        self.remaining_quantities: dict[int, Decimal] = {}
        self.executions: list[PaperBrokerExecution] = []
        self.commission_reports: list[PaperBrokerCommissionReport] = []
        self.quote_values: dict[int, dict[str, Decimal]] = {}
        self.quote_timestamps: dict[int, Any] = {}
        self.callback_events: list[PaperOrderCallbackEvent] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._lock = threading.Lock()

    def connectAck(self) -> None:  # noqa: N802 - IBKR callback name
        self.connection_ready_event.set()

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IBKR callback name
        with self._lock:
            self.next_valid_order_id = orderId
            self.callback_events.append(
                PaperOrderCallbackEvent(event_type="nextValidId", order_id=orderId)
            )
        self.connection_ready_event.set()
        self.next_valid_id_event.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        accounts = [account.strip() for account in accountsList.split(",") if account.strip()]
        with self._lock:
            self.managed_accounts = accounts
        self.managed_accounts_event.set()

    def accountSummary(  # noqa: N802
        self,
        reqId: int,
        account: str,
        tag: str,
        value: str,
        currency: str,
    ) -> None:
        del currency
        with self._lock:
            account_bucket = self.account_summary.setdefault(account, {})
            account_bucket[tag] = {"value": value, "req_id": str(reqId)}

    def accountSummaryEnd(self, _reqId: int) -> None:  # noqa: N802
        self.account_summary_event.set()

    def openOrder(  # noqa: N802
        self,
        orderId: int,
        contract: object,
        order: object,
        orderState: object,
    ) -> None:
        symbol = str(getattr(contract, "symbol", "") or "").upper()
        action = str(getattr(order, "action", "") or "") or None
        status = str(getattr(orderState, "status", "") or "") or None
        perm_id = _safe_int(getattr(order, "permId", None))
        with self._lock:
            self.open_orders[orderId] = PaperBrokerOpenOrder(
                order_id=orderId,
                symbol=symbol,
                action=action,
                status=status,
                perm_id=perm_id,
            )
            if perm_id is not None:
                self.order_perm_ids[orderId] = perm_id
            self.callback_events.append(
                PaperOrderCallbackEvent(
                    event_type="openOrder",
                    order_id=orderId,
                    perm_id=perm_id,
                    status=status,
                )
            )
        self.open_order_event.set()
        self.order_event.set()

    def openOrderEnd(self) -> None:  # noqa: N802
        self.open_order_end_event.set()

    def orderStatus(  # noqa: N802
        self,
        orderId: int,
        status: str,
        filled: Decimal | float | int,
        remaining: Decimal | float | int,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float = 0.0,
    ) -> None:
        del avgFillPrice, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice
        filled_decimal = Decimal(str(filled))
        remaining_decimal = Decimal(str(remaining))
        with self._lock:
            self.order_statuses[orderId] = status
            self.order_perm_ids[orderId] = permId
            self.filled_quantities[orderId] = filled_decimal
            self.remaining_quantities[orderId] = remaining_decimal
            self.callback_events.append(
                PaperOrderCallbackEvent(
                    event_type="orderStatus",
                    order_id=orderId,
                    perm_id=permId,
                    status=status,
                    filled_quantity=filled_decimal,
                    remaining_quantity=remaining_decimal,
                )
            )
        self.order_event.set()

    def execDetails(self, reqId: int, contract: object, execution: object) -> None:  # noqa: N802
        order_id = _safe_int(getattr(execution, "orderId", None))
        perm_id = _safe_int(getattr(execution, "permId", None))
        exec_id = _safe_str(getattr(execution, "execId", None))
        symbol = _safe_str(getattr(contract, "symbol", None))
        side = _safe_str(getattr(execution, "side", None))
        shares = _safe_decimal(getattr(execution, "shares", None))
        price = _safe_decimal(getattr(execution, "price", None))
        execution_time = _safe_str(getattr(execution, "time", None))
        account = _safe_str(getattr(execution, "acctNumber", None))
        exchange = _safe_str(getattr(execution, "exchange", None))
        cum_qty = _safe_decimal(getattr(execution, "cumQty", None))
        avg_price = _safe_decimal(getattr(execution, "avgPrice", None))
        with self._lock:
            self.executions.append(
                PaperBrokerExecution(
                    req_id=reqId,
                    order_id=order_id,
                    perm_id=perm_id,
                    exec_id=exec_id,
                    symbol=symbol,
                    side=side,
                    shares=shares,
                    price=price,
                    time=execution_time,
                    account_id_masked=mask_account_id(account) if account else None,
                    exchange=exchange,
                    cum_qty=cum_qty,
                    avg_price=avg_price,
                )
            )
            self.callback_events.append(
                PaperOrderCallbackEvent(
                    event_type="execDetails",
                    order_id=order_id,
                    perm_id=perm_id,
                    status="execution",
                    filled_quantity=shares,
                )
            )
        self.order_event.set()

    def execDetailsEnd(self, _reqId: int) -> None:  # noqa: N802
        self.execution_details_end_event.set()

    def commissionReport(self, commissionReport: object) -> None:  # noqa: N802
        self._record_commission_and_fees(commissionReport)

    def commissionAndFeesReport(self, commissionAndFeesReport: object) -> None:  # noqa: N802
        self._record_commission_and_fees(commissionAndFeesReport)

    def _record_commission_and_fees(self, report: object) -> None:
        commission = getattr(report, "commission", None)
        if commission is None:
            commission = getattr(report, "commissionAndFees", None)
        with self._lock:
            self.commission_reports.append(
                PaperBrokerCommissionReport(
                    exec_id=_safe_str(getattr(report, "execId", None)),
                    commission=_safe_decimal(commission),
                    currency=_safe_str(getattr(report, "currency", None)),
                    realized_pnl=_safe_decimal(getattr(report, "realizedPNL", None)),
                    yield_value=_safe_decimal(getattr(report, "yield_", None)),
                    yield_redemption_date=_safe_int(
                        getattr(report, "yieldRedemptionDate", None)
                    ),
                )
            )

    def tickPrice(self, reqId: int, tickType: int, price: float, _attrib: object) -> None:  # noqa: N802
        field = _PRICE_TICK_FIELDS.get(tickType)
        if field is None or price <= 0:
            return
        with self._lock:
            self.quote_values.setdefault(reqId, {})[field] = Decimal(str(price))
            self.quote_timestamps[reqId] = utc_now()
        self.market_data_events.setdefault(reqId, threading.Event()).set()

    def connectionClosed(self) -> None:  # noqa: N802
        with self._lock:
            self.warnings.append("IBKR connection closed")
        self._release_events()

    def error(  # noqa: N802
        self,
        reqId: int,
        *args: object,
    ) -> None:
        try:
            normalized = normalize_ibkr_error_args(args)
        except ValueError as exc:
            with self._lock:
                self.errors.append(str(exc))
            self._release_events(reqId)
            return

        error_code = normalized.error_code
        message = normalized.error_string
        if normalized.advanced_order_reject_json:
            message = f"{message} ({normalized.advanced_order_reject_json})"
        event = PaperOrderCallbackEvent(
            event_type="error",
            order_id=reqId if reqId >= 0 else None,
            status=str(error_code),
            message=message,
        )
        informational_error = error_code in _INFORMATIONAL_ERROR_CODES or (
            error_code == 300
            and reqId in self.market_data_events
            and "tickerId" in message
        ) or (
            error_code == 399
            and message.startswith("Order Message:")
        ) or (
            error_code == 202
            and message.startswith("Order Canceled")
        )
        with self._lock:
            self.callback_events.append(event)
            if informational_error:
                self.warnings.append(f"IBKR {error_code}: {message}")
            else:
                self.errors.append(f"IBKR {error_code}: {message}")
        if not informational_error:
            self._release_events(reqId)

    def _release_events(self, req_id: int | None = None) -> None:
        self.order_event.set()
        self.open_order_event.set()
        self.execution_details_end_event.set()
        if req_id is None or req_id < 0:
            for event in self.market_data_events.values():
                event.set()
            for event in self.contract_details_events.values():
                event.set()
            return
        market_event = self.market_data_events.get(req_id)
        if market_event is not None:
            market_event.set()
        contract_event = self.contract_details_events.get(req_id)
        if contract_event is not None:
            contract_event.set()


class IBKRPaperOrderBroker:
    """Narrow IBKR adapter for the paper-order smoke command."""

    def __init__(
        self,
        config: TraderConfig,
        *,
        app_factory: Callable[[], PaperOrderAppProtocol] | None = None,
        socket_probe: Callable[[str, int, float], None] | None = None,
        ibapi_available: bool | None = None,
    ) -> None:
        self.config = config
        self._app_factory = app_factory or (
            lambda: cast(PaperOrderAppProtocol, _PaperOrderIBKRApp())
        )
        self._socket_probe = socket_probe or _probe_socket
        self._ibapi_available_override = ibapi_available
        self._app: PaperOrderAppProtocol | None = None
        self._thread: threading.Thread | None = None
        self._request_id = 20_000
        self._known_order_ids: set[int] = set()

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

    def connect(self, *, timeout: float) -> None:
        """Connect to the paper broker with the dedicated execution client ID."""

        if not self.ibapi_is_available:
            import_error = self.ibapi_import_error() or "ibapi unavailable"
            raise PaperOrderSmokeError(f"ibapi import failed: {import_error}")
        if self.config.ibkr_port in LIVE_PORTS:
            raise PaperOrderSmokeError("live IBKR ports are rejected before connection")

        try:
            self._socket_probe(self.config.ibkr_host, self.config.ibkr_port, timeout)
        except OSError as exc:
            raise PaperOrderSmokeError(
                f"paper broker socket is unavailable at "
                f"{self.config.ibkr_host}:{self.config.ibkr_port}: {exc}"
            ) from exc

        app = self._app_factory()
        self._app = app
        connected = bool(
            app.connect(
                self.config.ibkr_host,
                self.config.ibkr_port,
                self.config.ibkr_client_id,
            )
        )
        self._thread = threading.Thread(target=app.run, name="ibkr-paper-order-smoke", daemon=True)
        self._thread.start()

        if not connected and not app.isConnected():
            raise PaperOrderSmokeError("IBKR API connect returned false")
        if not app.connection_ready_event.wait(timeout):
            self.disconnect()
            raise PaperOrderSmokeError("IBKR API connection timed out before nextValidId")
        if not app.next_valid_id_event.wait(timeout):
            self.disconnect()
            raise PaperOrderSmokeError("IBKR API connection timed out before nextValidId")

    def disconnect(self) -> None:
        """Disconnect from TWS and stop the background API loop."""

        app = self._app
        if app is not None:
            with suppress(Exception):
                app.disconnect()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        self._app = None
        self._thread = None

    def request_account_summary(self, *, timeout: float) -> PaperBrokerAccountSummary:
        app = self._require_app()
        app.managed_accounts_event.clear()
        app.account_summary_event.clear()
        app.reqManagedAccts()
        if not app.managed_accounts_event.wait(timeout):
            return PaperBrokerAccountSummary(
                account_ids_masked=[],
                verified=False,
                warnings=list(app.warnings),
                errors=["managed-account request timed out"],
            )

        req_id = self._next_request_id()
        app.reqAccountSummary(req_id, "All", _ACCOUNT_SUMMARY_TAGS)
        if not app.account_summary_event.wait(timeout):
            return PaperBrokerAccountSummary(
                account_ids_masked=[
                    mask_account_id(account) or "masked"
                    for account in app.managed_accounts
                ],
                verified=False,
                warnings=list(app.warnings),
                errors=["account-summary request timed out"],
            )

        masked_accounts = [
            mask_account_id(account) or "masked"
            for account in app.account_summary
        ] or [mask_account_id(account) or "masked" for account in app.managed_accounts]
        verified = any(
            {"NetLiquidation", "TotalCashValue", "BuyingPower"}.issubset(tags)
            for tags in app.account_summary.values()
        )
        errors = [] if verified else ["account summary lacks required funding tags"]
        return PaperBrokerAccountSummary(
            account_ids_masked=masked_accounts,
            verified=verified,
            warnings=list(app.warnings),
            errors=errors,
        )

    def request_open_orders(self, *, timeout: float) -> list[PaperBrokerOpenOrder]:
        app = self._require_app()
        app.open_order_end_event.clear()
        app.reqOpenOrders()
        if not app.open_order_end_event.wait(timeout):
            raise PaperOrderSmokeError(
                f"open-order reconciliation timed out after {timeout:g} seconds"
            )
        return list(app.open_orders.values())

    def request_executions(
        self,
        *,
        timeout: float,
    ) -> tuple[list[PaperBrokerExecution], list[PaperBrokerCommissionReport]]:
        """Request read-only current-day execution evidence."""

        app = self._require_app()
        req_id = self._next_request_id()
        app.execution_details_end_event.clear()
        app.reqExecutions(req_id, _make_execution_filter())
        if not app.execution_details_end_event.wait(timeout):
            raise PaperOrderSmokeError(
                f"execution reconciliation timed out after {timeout:g} seconds"
            )
        return list(app.executions), list(app.commission_reports)

    def request_quote(
        self,
        symbol: str,
        *,
        timeout: float,
        max_age_seconds: int,
    ) -> PaperOrderQuote:
        app = self._require_app()
        req_id = self._next_request_id()
        event = threading.Event()
        app.market_data_events[req_id] = event
        contract = _make_stock_contract(symbol)
        app.reqMarketDataType(3)
        app.reqMktData(req_id, contract, "", True, False, [])
        completed = event.wait(timeout)
        with suppress(Exception):
            app.cancelMktData(req_id)

        values = app.quote_values.get(req_id, {})
        timestamp = app.quote_timestamps.get(req_id)
        quote_age = (utc_now() - timestamp).total_seconds() if timestamp is not None else None
        stale = quote_age is None or quote_age > max_age_seconds
        warnings = list(app.warnings)
        errors = list(app.errors)
        if not completed:
            errors.append(f"quote snapshot timed out for {symbol}")
        if not values:
            errors.append(f"quote snapshot returned no usable bid/ask/last/close for {symbol}")
        return PaperOrderQuote(
            symbol=symbol,
            bid=values.get("bid"),
            ask=values.get("ask"),
            last=values.get("last"),
            close=values.get("close"),
            quote_timestamp=timestamp,
            quote_age_seconds=quote_age,
            stale=stale,
            warnings=warnings,
            errors=errors,
        )

    def place_limit_order(
        self,
        *,
        symbol: str,
        action: TradeAction,
        quantity: int,
        limit_price: Decimal,
        time_in_force: str,
        transmit: bool,
        timeout: float,
    ) -> PaperBrokerPlacementResult:
        app = self._require_app()
        order_id = app.next_valid_order_id
        if order_id is None:
            return _placement_failure(["nextValidId was unavailable before place order"])

        app.order_event.clear()
        event_start = len(app.callback_events)
        contract = _make_stock_contract(symbol)
        order = _make_limit_order(
            action=action,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            transmit=transmit,
        )
        app.placeOrder(order_id, contract, order)
        self._known_order_ids.add(order_id)
        app.order_event.wait(timeout)
        events = app.callback_events[event_start:]
        status = app.order_statuses.get(order_id)
        filled = app.filled_quantities.get(order_id, Decimal("0"))
        remaining = app.remaining_quantities.get(order_id)
        perm_id = app.order_perm_ids.get(order_id)
        errors = list(app.errors)
        accepted = (
            bool(status or any(event.event_type == "openOrder" for event in events))
            and not errors
        )
        return PaperBrokerPlacementResult(
            order_id=order_id,
            perm_id=perm_id,
            status=status,
            fill_quantity=filled,
            remaining_quantity=remaining,
            accepted=accepted,
            submitted_to_broker=transmit,
            canceled=status in _CANCELED_STATUSES if status else False,
            terminal=status in _TERMINAL_STATUSES if status else False,
            callback_timeline=events,
            warnings=list(app.warnings),
            errors=errors,
        )

    def cancel_order(self, order_id: int | None, *, timeout: float) -> PaperBrokerPlacementResult:
        if order_id is None or order_id not in self._known_order_ids:
            return _placement_failure(["refused to cancel unknown paper smoke order id"])

        app = self._require_app()
        app.order_event.clear()
        event_start = len(app.callback_events)
        _call_cancel_order(app, order_id)
        app.order_event.wait(timeout)
        events = app.callback_events[event_start:]
        status = app.order_statuses.get(order_id)
        filled = app.filled_quantities.get(order_id, Decimal("0"))
        remaining = app.remaining_quantities.get(order_id)
        perm_id = app.order_perm_ids.get(order_id)
        errors = list(app.errors)
        return PaperBrokerPlacementResult(
            order_id=order_id,
            perm_id=perm_id,
            status=status,
            fill_quantity=filled,
            remaining_quantity=remaining,
            accepted=bool(status) and not errors,
            submitted_to_broker=True,
            canceled=status in _CANCELED_STATUSES if status else False,
            terminal=status in _TERMINAL_STATUSES if status else False,
            callback_timeline=events,
            warnings=list(app.warnings),
            errors=errors,
        )

    def _require_app(self) -> PaperOrderAppProtocol:
        if self._app is None:
            raise PaperOrderSmokeError("IBKR paper-order app is not connected")
        return self._app

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id


def run_paper_order_smoke(
    config: TraderConfig,
    request: PaperOrderSmokeRequest,
    *,
    broker_factory: Callable[[TraderConfig], PaperOrderBroker] | None = None,
) -> PaperOrderSmokeReport:
    """Run the gated paper-only order smoke workflow."""

    request = _request_with_campaign_id(request)
    warnings = [
        "IBKR Read-Only API must be disabled only while running paper-order-smoke.",
        "Re-enable IBKR Read-Only API immediately after the smoke run.",
        "This command refuses live ports, live mode, market orders, shorts, and batches.",
    ]
    errors = _validate_smoke_gates(config, request)
    if errors:
        return _build_report(
            config,
            request,
            warnings=warnings,
            errors=errors,
            final_status=PaperOrderSmokeRunStatus.FAILED,
        )

    broker = (broker_factory or IBKRPaperOrderBroker)(config)
    broker_connected = False
    account_summary_verified = False
    account_ids_masked: list[str] = []
    existing_open_order_count = 0
    duplicate_open_order_detected = False
    quote: PaperOrderQuote | None = None
    limit_price: Decimal | None = None
    notional: Decimal | None = None
    order_id: int | None = None
    perm_id: int | None = None
    order_status: str | None = None
    fill_quantity = Decimal("0")
    remaining_quantity: Decimal | None = None
    cancel_requested = False
    canceled = False
    cancel_status: str | None = None
    callback_timeline: list[PaperOrderCallbackEvent] = []
    order_api_invoked = False
    place_order_invoked = False
    cancel_order_invoked = False
    submitted_orders = False

    try:
        broker.connect(timeout=request.timeout_seconds)
        broker_connected = True

        account_summary = broker.request_account_summary(timeout=request.timeout_seconds)
        account_ids_masked = account_summary.account_ids_masked
        warnings.extend(account_summary.warnings)
        errors.extend(account_summary.errors)
        account_summary_verified = account_summary.verified
        if not account_summary_verified:
            return _build_report(
                config,
                request,
                broker_connected=broker_connected,
                account_summary_verified=account_summary_verified,
                account_ids_masked=account_ids_masked,
                warnings=warnings,
                errors=errors,
                final_status=PaperOrderSmokeRunStatus.FAILED,
            )

        open_orders = broker.request_open_orders(timeout=request.timeout_seconds)
        existing_open_order_count = len(open_orders)
        duplicates = _duplicate_open_orders(open_orders, request)
        duplicate_open_order_detected = bool(duplicates)
        if duplicate_open_order_detected:
            errors.append("duplicate open SPY BUY order exists; refusing smoke order")
            return _build_report(
                config,
                request,
                broker_connected=broker_connected,
                account_summary_verified=account_summary_verified,
                account_ids_masked=account_ids_masked,
                existing_open_order_count=existing_open_order_count,
                duplicate_open_order_detected=duplicate_open_order_detected,
                warnings=warnings,
                errors=errors,
                final_status=PaperOrderSmokeRunStatus.FAILED,
            )

        quote = broker.request_quote(
            request.symbol,
            timeout=request.timeout_seconds,
            max_age_seconds=request.quote_max_age_seconds,
        )
        warnings.extend(quote.warnings)
        errors.extend(_quote_errors(quote))
        if errors:
            return _build_report(
                config,
                request,
                broker_connected=broker_connected,
                account_summary_verified=account_summary_verified,
                account_ids_masked=account_ids_masked,
                existing_open_order_count=existing_open_order_count,
                quote=quote,
                warnings=warnings,
                errors=errors,
                final_status=PaperOrderSmokeRunStatus.FAILED,
            )

        limit_price = _derive_non_marketable_buy_limit(quote)
        notional = limit_price * Decimal(request.quantity)
        errors.extend(_notional_errors(config, request, notional))
        if errors:
            return _build_report(
                config,
                request,
                broker_connected=broker_connected,
                account_summary_verified=account_summary_verified,
                account_ids_masked=account_ids_masked,
                existing_open_order_count=existing_open_order_count,
                quote=quote,
                limit_price=limit_price,
                notional=notional,
                warnings=warnings,
                errors=errors,
                final_status=PaperOrderSmokeRunStatus.FAILED,
            )

        placement = broker.place_limit_order(
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            limit_price=limit_price,
            time_in_force=request.time_in_force,
            transmit=request.transmit,
            timeout=request.timeout_seconds,
        )
        order_api_invoked = True
        place_order_invoked = True
        submitted_orders = bool(request.transmit and placement.submitted_to_broker)
        callback_timeline.extend(placement.callback_timeline)
        warnings.extend(placement.warnings)
        errors.extend(placement.errors)
        order_id = placement.order_id
        perm_id = placement.perm_id
        order_status = placement.status
        fill_quantity = placement.fill_quantity
        remaining_quantity = placement.remaining_quantity

        if _read_only_rejection(errors):
            errors.append("order rejected; confirm IBKR Read-Only API is disabled only for smoke")
        if request.transmit and not request.allow_fill and fill_quantity > 0:
            errors.append("paper smoke order filled even though --allow-fill was false")
        if errors:
            return _build_report(
                config,
                request,
                broker_connected=broker_connected,
                account_summary_verified=account_summary_verified,
                account_ids_masked=account_ids_masked,
                existing_open_order_count=existing_open_order_count,
                quote=quote,
                limit_price=limit_price,
                notional=notional,
                order_id=order_id,
                perm_id=perm_id,
                order_status=order_status,
                fill_quantity=fill_quantity,
                remaining_quantity=remaining_quantity,
                callback_timeline=callback_timeline,
                submitted_orders=submitted_orders,
                order_api_invoked=order_api_invoked,
                place_order_invoked=place_order_invoked,
                warnings=warnings,
                errors=errors,
                final_status=PaperOrderSmokeRunStatus.FAILED,
            )

        if request.transmit and fill_quantity == 0 and not placement.terminal:
            cancel_requested = True
            if request.cancel_after_seconds > 0:
                time.sleep(request.cancel_after_seconds)
            cancellation = broker.cancel_order(order_id, timeout=request.timeout_seconds)
            cancel_order_invoked = True
            order_api_invoked = True
            callback_timeline.extend(cancellation.callback_timeline)
            warnings.extend(cancellation.warnings)
            errors.extend(cancellation.errors)
            cancel_status = cancellation.status
            canceled = cancellation.canceled
            order_status = cancellation.status or order_status
            fill_quantity = cancellation.fill_quantity
            remaining_quantity = cancellation.remaining_quantity
            if not canceled and not cancellation.terminal:
                errors.append("paper smoke cancellation was not confirmed")

        final_status = _final_status(
            errors=errors,
            warnings=warnings,
            request=request,
            placement_status=order_status,
            canceled=canceled,
            fill_quantity=fill_quantity,
        )
        return _build_report(
            config,
            request,
            broker_connected=broker_connected,
            account_summary_verified=account_summary_verified,
            account_ids_masked=account_ids_masked,
            existing_open_order_count=existing_open_order_count,
            duplicate_open_order_detected=duplicate_open_order_detected,
            quote=quote,
            limit_price=limit_price,
            notional=notional,
            order_id=order_id,
            perm_id=perm_id,
            order_status=order_status,
            fill_quantity=fill_quantity,
            remaining_quantity=remaining_quantity,
            cancel_requested=cancel_requested,
            canceled=canceled,
            cancel_status=cancel_status,
            callback_timeline=callback_timeline,
            submitted_orders=submitted_orders,
            order_api_invoked=order_api_invoked,
            place_order_invoked=place_order_invoked,
            cancel_order_invoked=cancel_order_invoked,
            warnings=warnings,
            errors=errors,
            final_status=final_status,
        )
    except PaperOrderSmokeError as exc:
        errors.append(str(exc))
        return _build_report(
            config,
            request,
            broker_connected=broker_connected,
            account_summary_verified=account_summary_verified,
            account_ids_masked=account_ids_masked,
            existing_open_order_count=existing_open_order_count,
            quote=quote,
            limit_price=limit_price,
            notional=notional,
            order_id=order_id,
            perm_id=perm_id,
            order_status=order_status,
            fill_quantity=fill_quantity,
            remaining_quantity=remaining_quantity,
            cancel_requested=cancel_requested,
            canceled=canceled,
            cancel_status=cancel_status,
            callback_timeline=callback_timeline,
            submitted_orders=submitted_orders,
            order_api_invoked=order_api_invoked,
            place_order_invoked=place_order_invoked,
            cancel_order_invoked=cancel_order_invoked,
            warnings=warnings,
            errors=errors,
            final_status=PaperOrderSmokeRunStatus.FAILED,
        )
    finally:
        broker.disconnect()


def _validate_smoke_gates(config: TraderConfig, request: PaperOrderSmokeRequest) -> list[str]:
    errors: list[str] = []
    if _enum_value(config.trading_mode) != TradingMode.PAPER.value:
        errors.append("TRADING_MODE must be paper for paper-order-smoke")
    if not config.allow_paper_orders:
        errors.append("ALLOW_PAPER_ORDERS=true is required for paper-order-smoke")
    if config.allow_live_orders:
        errors.append("ALLOW_LIVE_ORDERS=true is rejected")
    if config.ibkr_host != "127.0.0.1":
        errors.append("IBKR_HOST must be 127.0.0.1 for paper-order-smoke")
    if config.ibkr_port in LIVE_PORTS:
        errors.append("live IBKR ports are rejected")
    elif config.ibkr_port not in PAPER_SMOKE_PORTS:
        errors.append(
            "IBKR_PORT must be 7497 (TWS paper) or 4002 (IB Gateway paper) "
            "for paper-order-smoke"
        )
    if config.ibkr_client_id != PAPER_SMOKE_CLIENT_ID:
        errors.append("IBKR_CLIENT_ID must be 21 for paper-order-smoke")
    if request.confirm != PAPER_SMOKE_CONFIRMATION:
        errors.append(f"--confirm {PAPER_SMOKE_CONFIRMATION} is required")
    if request.symbol != PAPER_SMOKE_SYMBOL:
        errors.append("paper-order-smoke is SPY-only")
    if request.quantity != 1:
        errors.append("paper-order-smoke requires quantity 1")
    if request.action != TradeAction.BUY:
        errors.append("paper-order-smoke is BUY-only; SELL is reserved for reduce-only")
    if request.order_type != OrderType.LIMIT:
        errors.append("paper-order-smoke supports LMT orders only")
    if request.time_in_force != "DAY":
        errors.append("paper-order-smoke supports DAY time-in-force only")
    return errors


def _request_with_campaign_id(request: PaperOrderSmokeRequest) -> PaperOrderSmokeRequest:
    if request.campaign_id:
        return request
    return request.model_copy(update={"campaign_id": new_campaign_id()})


def _duplicate_open_orders(
    open_orders: list[PaperBrokerOpenOrder],
    request: PaperOrderSmokeRequest,
) -> list[PaperBrokerOpenOrder]:
    return [
        order
        for order in open_orders
        if order.symbol == request.symbol
        and (order.action or "").upper() == request.action.value
        and (order.status or "") not in _TERMINAL_STATUSES
    ]


def _quote_errors(quote: PaperOrderQuote) -> list[str]:
    errors = list(quote.errors)
    if quote.stale:
        errors.append("quote is stale or missing a timestamp")
    if quote.bid is None and quote.last is None and quote.close is None:
        errors.append("quote lacks bid, last, and close prices")
    return errors


def _derive_non_marketable_buy_limit(quote: PaperOrderQuote) -> Decimal:
    anchor = quote.bid or quote.last or quote.close
    if anchor is None:
        raise PaperOrderSmokeError("cannot derive limit price without bid, last, or close")
    return (anchor * _NON_MARKETABLE_BUY_DISCOUNT).quantize(_CENT, rounding=ROUND_DOWN)


def _notional_errors(
    config: TraderConfig,
    request: PaperOrderSmokeRequest,
    notional: Decimal,
) -> list[str]:
    errors: list[str] = []
    if notional > request.max_trade_notional:
        errors.append(
            f"paper smoke notional {notional} exceeds request max {request.max_trade_notional}"
        )
    if notional > config.max_trade_notional:
        errors.append(
            f"paper smoke notional {notional} exceeds configured MAX_TRADE_NOTIONAL "
            f"{config.max_trade_notional}"
        )
    return errors


def _final_status(
    *,
    errors: list[str],
    warnings: list[str],
    request: PaperOrderSmokeRequest,
    placement_status: str | None,
    canceled: bool,
    fill_quantity: Decimal,
) -> PaperOrderSmokeRunStatus:
    del warnings
    if errors:
        return PaperOrderSmokeRunStatus.FAILED
    if request.transmit:
        if fill_quantity > 0 and not request.allow_fill:
            return PaperOrderSmokeRunStatus.FAILED
        if fill_quantity == 0 and not canceled and placement_status not in _TERMINAL_STATUSES:
            return PaperOrderSmokeRunStatus.FAILED
    return PaperOrderSmokeRunStatus.COMPLETED


def _build_report(
    config: TraderConfig,
    request: PaperOrderSmokeRequest,
    *,
    broker_connected: bool = False,
    account_summary_verified: bool = False,
    account_ids_masked: list[str] | None = None,
    existing_open_order_count: int = 0,
    duplicate_open_order_detected: bool = False,
    quote: PaperOrderQuote | None = None,
    limit_price: Decimal | None = None,
    notional: Decimal | None = None,
    order_id: int | None = None,
    perm_id: int | None = None,
    order_status: str | None = None,
    fill_quantity: Decimal = Decimal("0"),
    remaining_quantity: Decimal | None = None,
    cancel_requested: bool = False,
    canceled: bool = False,
    cancel_status: str | None = None,
    callback_timeline: list[PaperOrderCallbackEvent] | None = None,
    submitted_orders: bool = False,
    order_api_invoked: bool = False,
    place_order_invoked: bool = False,
    cancel_order_invoked: bool = False,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    final_status: PaperOrderSmokeRunStatus = PaperOrderSmokeRunStatus.FAILED,
) -> PaperOrderSmokeReport:
    report_errors = list(dict.fromkeys(errors or []))
    report_warnings = list(dict.fromkeys(warnings or []))
    gates_open = not _validate_smoke_gates(config, request)
    return PaperOrderSmokeReport(
        ok=final_status != PaperOrderSmokeRunStatus.FAILED and not report_errors,
        request=request,
        campaign_id=request.campaign_id,
        mode=_enum_value(config.trading_mode),
        host=config.ibkr_host,
        port=config.ibkr_port,
        client_id=config.ibkr_client_id,
        broker_kind=config.inferred_broker_kind,
        broker_connected=broker_connected,
        account_summary_verified=account_summary_verified,
        account_ids_masked=account_ids_masked or [],
        existing_open_order_count=existing_open_order_count,
        duplicate_open_order_detected=duplicate_open_order_detected,
        quote=quote,
        limit_price=limit_price,
        notional=notional,
        order_id=order_id,
        perm_id=perm_id,
        order_status=order_status,
        fill_quantity=fill_quantity,
        remaining_quantity=remaining_quantity,
        cancel_requested=cancel_requested,
        canceled=canceled,
        cancel_status=cancel_status,
        callback_timeline=callback_timeline or [],
        warnings=report_warnings,
        errors=report_errors,
        submitted_orders=submitted_orders,
        paper_orders_enabled=config.allow_paper_orders,
        configured_allow_paper_orders=config.allow_paper_orders,
        live_orders_enabled=False,
        read_only_api_expected=False,
        order_routing_enabled=gates_open and place_order_invoked,
        paper_execution_enabled=gates_open,
        live_route_possible=False,
        order_api_invoked=order_api_invoked,
        place_order_invoked=place_order_invoked,
        cancel_order_invoked=cancel_order_invoked,
        transmitted=request.transmit,
        final_status=final_status,
    )


def _placement_failure(errors: list[str]) -> PaperBrokerPlacementResult:
    return PaperBrokerPlacementResult(
        order_id=None,
        perm_id=None,
        status=None,
        fill_quantity=Decimal("0"),
        remaining_quantity=None,
        accepted=False,
        submitted_to_broker=False,
        canceled=False,
        terminal=False,
        callback_timeline=[],
        warnings=[],
        errors=errors,
    )


def _make_stock_contract(symbol: str) -> object:
    if _IBAPI_CONTRACT is None:
        raise PaperOrderSmokeError("ibapi Contract class is unavailable")
    contract = _IBAPI_CONTRACT()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.primaryExchange = "ARCA"
    contract.currency = "USD"
    return contract


def _make_execution_filter() -> object:
    if _IBAPI_EXECUTION_FILTER is None:
        raise PaperOrderSmokeError("ibapi ExecutionFilter class is unavailable")
    return _IBAPI_EXECUTION_FILTER()


def _make_limit_order(
    *,
    action: TradeAction,
    quantity: int,
    limit_price: Decimal,
    time_in_force: str,
    transmit: bool,
) -> object:
    if _IBAPI_ORDER is None:
        raise PaperOrderSmokeError("ibapi Order class is unavailable")
    order = _IBAPI_ORDER()
    order.action = action.value
    order.orderType = "LMT"
    order.totalQuantity = quantity
    order.lmtPrice = float(limit_price)
    order.tif = time_in_force
    order.transmit = transmit
    if hasattr(order, "eTradeOnly"):
        order.eTradeOnly = False
    if hasattr(order, "firmQuoteOnly"):
        order.firmQuoteOnly = False
    return order


def _call_cancel_order(app: PaperOrderAppProtocol, order_id: int) -> None:
    order_cancel = _IBAPI_ORDER_CANCEL() if _IBAPI_ORDER_CANCEL is not None else ""
    app.cancelOrder(order_id, order_cancel)


def _probe_socket(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _read_only_rejection(errors: list[str]) -> bool:
    return any("read-only" in error.lower() or "read only" in error.lower() for error in errors)


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))
