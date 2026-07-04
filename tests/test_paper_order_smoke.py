from __future__ import annotations

import threading
from decimal import Decimal
from pathlib import Path

import pytest

from trader.config import BrokerKind, TraderConfig, TradingMode
from trader.execution.paper_order_smoke import (
    PAPER_SMOKE_CONFIRMATION,
    IBKRPaperOrderBroker,
    PaperBrokerAccountSummary,
    PaperBrokerOpenOrder,
    PaperBrokerPlacementResult,
    PaperOrderSmokeError,
    run_paper_order_smoke,
)
from trader.models import (
    PaperOrderCallbackEvent,
    PaperOrderQuote,
    PaperOrderSmokeRequest,
    PaperOrderSmokeRunStatus,
    TradeAction,
)
from trader.reporting.reports import markdown_summary


def config(**overrides: object) -> TraderConfig:
    values: dict[str, object] = {
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 7497,
        "ibkr_client_id": 21,
        "broker_kind": BrokerKind.TWS,
        "trading_mode": TradingMode.PAPER,
        "allow_paper_orders": True,
        "allow_live_orders": False,
        "max_trade_notional": Decimal("1000"),
    }
    values.update(overrides)
    return TraderConfig(**values)


def unsafe_config(**overrides: object) -> TraderConfig:
    base = config()
    return base.model_copy(update=overrides)


def request(**overrides: object) -> PaperOrderSmokeRequest:
    values: dict[str, object] = {
        "confirm": PAPER_SMOKE_CONFIRMATION,
        "cancel_after_seconds": 0,
    }
    values.update(overrides)
    return PaperOrderSmokeRequest(**values)


def unsafe_request(**overrides: object) -> PaperOrderSmokeRequest:
    base = request()
    return base.model_copy(update=overrides)


def quote(**overrides: object) -> PaperOrderQuote:
    values: dict[str, object] = {
        "symbol": "SPY",
        "bid": Decimal("500"),
        "ask": Decimal("500.10"),
        "last": Decimal("500.05"),
        "stale": False,
    }
    values.update(overrides)
    return PaperOrderQuote(**values)


def placement(
    *,
    order_id: int | None = 1001,
    status: str | None = "Submitted",
    filled: Decimal = Decimal("0"),
    remaining: Decimal | None = Decimal("1"),
    accepted: bool = True,
    submitted: bool = False,
    canceled: bool = False,
    terminal: bool = False,
    errors: list[str] | None = None,
) -> PaperBrokerPlacementResult:
    return PaperBrokerPlacementResult(
        order_id=order_id,
        perm_id=9001 if order_id is not None else None,
        status=status,
        fill_quantity=filled,
        remaining_quantity=remaining,
        accepted=accepted,
        submitted_to_broker=submitted,
        canceled=canceled,
        terminal=terminal,
        callback_timeline=[
            PaperOrderCallbackEvent(
                event_type="orderStatus",
                order_id=order_id,
                perm_id=9001 if order_id is not None else None,
                status=status,
                filled_quantity=filled,
                remaining_quantity=remaining,
            )
        ],
        warnings=[],
        errors=errors or [],
    )


class FakePaperOrderBroker:
    def __init__(
        self,
        *,
        account: PaperBrokerAccountSummary | None = None,
        open_orders: list[PaperBrokerOpenOrder] | None = None,
        quote_snapshot: PaperOrderQuote | None = None,
        placement_result: PaperBrokerPlacementResult | None = None,
        cancel_result: PaperBrokerPlacementResult | None = None,
    ) -> None:
        self.account = account or PaperBrokerAccountSummary(
            account_ids_masked=["DUQ2****23"],
            verified=True,
            warnings=[],
            errors=[],
        )
        self.open_orders = open_orders or []
        self.quote_snapshot = quote_snapshot or quote()
        self.placement_result = placement_result or placement()
        self.cancel_result = cancel_result or placement(
            status="Cancelled",
            submitted=True,
            canceled=True,
            terminal=True,
        )
        self.connected = False
        self.disconnected = False
        self.place_calls = 0
        self.cancel_calls = 0

    def connect(self, *, timeout: float) -> None:
        del timeout
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def request_account_summary(self, *, timeout: float) -> PaperBrokerAccountSummary:
        del timeout
        return self.account

    def request_open_orders(self, *, timeout: float) -> list[PaperBrokerOpenOrder]:
        del timeout
        return self.open_orders

    def request_quote(
        self,
        symbol: str,
        *,
        timeout: float,
        max_age_seconds: int,
    ) -> PaperOrderQuote:
        del symbol, timeout, max_age_seconds
        return self.quote_snapshot

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
        del symbol, action, quantity, limit_price, time_in_force, transmit, timeout
        self.place_calls += 1
        return self.placement_result

    def cancel_order(
        self,
        order_id: int | None,
        *,
        timeout: float,
    ) -> PaperBrokerPlacementResult:
        del order_id, timeout
        self.cancel_calls += 1
        return self.cancel_result


class DelayedNextValidIdApp:
    def __init__(self) -> None:
        self.connection_ready_event = threading.Event()
        self.next_valid_id_event = threading.Event()
        self.managed_accounts_event = threading.Event()
        self.account_summary_event = threading.Event()
        self.open_order_event = threading.Event()
        self.open_order_end_event = threading.Event()
        self.order_event = threading.Event()
        self.run_started_event = threading.Event()
        self.release_next_valid_id_event = threading.Event()
        self.market_data_events = {}
        self.contract_details_events = {}
        self.next_valid_order_id = None
        self.managed_accounts = []
        self.account_summary = {}
        self.open_orders = {}
        self.order_statuses = {}
        self.order_perm_ids = {}
        self.filled_quantities = {}
        self.remaining_quantities = {}
        self.quote_values = {}
        self.quote_timestamps = {}
        self.callback_events = []
        self.errors = []
        self.warnings = []
        self.connected = False
        self.disconnected = False

    def connect(self, host: str, port: int, clientId: int) -> bool:  # noqa: N803
        del host, port, clientId
        self.connected = True
        self.connection_ready_event.set()
        return True

    def disconnect(self) -> None:
        self.disconnected = True
        self.connected = False
        self.release_next_valid_id_event.set()

    def isConnected(self) -> bool:  # noqa: N802
        return self.connected

    def run(self) -> None:
        self.run_started_event.set()
        if self.release_next_valid_id_event.wait(timeout=1):
            self.next_valid_order_id = 1001
            self.next_valid_id_event.set()

    def reqManagedAccts(self) -> None:  # noqa: N802
        raise AssertionError("connect must wait for nextValidId before requests")

    def reqAccountSummary(self, reqId: int, groupName: str, tags: str) -> None:  # noqa: N802
        del reqId, groupName, tags

    def reqOpenOrders(self) -> None:  # noqa: N802
        return None

    def reqMarketDataType(self, marketDataType: int) -> None:  # noqa: N802
        del marketDataType

    def reqMktData(  # noqa: N802
        self,
        reqId: int,
        contract: object,
        genericTickList: str,
        snapshot: bool,
        regulatorySnapshot: bool,
        mktDataOptions: list[object],
    ) -> None:
        del reqId, contract, genericTickList, snapshot, regulatorySnapshot, mktDataOptions

    def cancelMktData(self, reqId: int) -> None:  # noqa: N802
        del reqId

    def placeOrder(self, orderId: int, contract: object, order: object) -> None:  # noqa: N802
        del orderId, contract, order

    def cancelOrder(self, orderId: int, manualCancelOrderTime: str = "") -> None:  # noqa: N802
        del orderId, manualCancelOrderTime


def test_ibkr_paper_order_broker_waits_for_next_valid_id_before_ready() -> None:
    app = DelayedNextValidIdApp()
    broker = IBKRPaperOrderBroker(
        config(),
        app_factory=lambda: app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )
    errors: list[BaseException] = []
    worker = threading.Thread(
        target=lambda: _connect_for_test(broker, errors),
        daemon=True,
    )

    worker.start()

    assert app.run_started_event.wait(timeout=0.2)
    assert worker.is_alive()

    app.release_next_valid_id_event.set()
    worker.join(timeout=1)

    broker.disconnect()

    assert errors == []
    assert worker.is_alive() is False


def test_ibkr_paper_order_broker_times_out_without_next_valid_id() -> None:
    app = DelayedNextValidIdApp()
    broker = IBKRPaperOrderBroker(
        config(),
        app_factory=lambda: app,
        socket_probe=lambda _host, _port, _timeout: None,
        ibapi_available=True,
    )

    with pytest.raises(PaperOrderSmokeError, match="timed out before nextValidId"):
        broker.connect(timeout=0.01)

    assert app.disconnected is True


def _connect_for_test(
    broker: IBKRPaperOrderBroker,
    errors: list[BaseException],
) -> None:
    try:
        broker.connect(timeout=1)
    except BaseException as exc:  # pragma: no cover - asserted by caller
        errors.append(exc)


def test_untransmitted_paper_order_smoke_rehearsal_records_order_without_submission() -> None:
    fake = FakePaperOrderBroker(
        placement_result=placement(status="PreSubmitted", submitted=False)
    )

    report = run_paper_order_smoke(config(), request(), broker_factory=lambda _config: fake)

    assert report.final_status == PaperOrderSmokeRunStatus.COMPLETED
    assert report.ok is True
    assert report.broker_connected is True
    assert report.account_summary_verified is True
    assert report.limit_price == Decimal("490.00")
    assert report.notional == Decimal("490.00")
    assert report.place_order_invoked is True
    assert report.order_api_invoked is True
    assert report.submitted_orders is False
    assert report.transmitted is False
    assert fake.place_calls == 1
    assert fake.cancel_calls == 0
    assert fake.disconnected is True


def test_transmitted_paper_order_smoke_cancels_unfilled_order() -> None:
    fake = FakePaperOrderBroker(
        placement_result=placement(status="Submitted", submitted=True),
        cancel_result=placement(
            status="Cancelled",
            submitted=True,
            canceled=True,
            terminal=True,
        ),
    )

    report = run_paper_order_smoke(
        config(),
        request(transmit=True),
        broker_factory=lambda _config: fake,
    )

    assert report.ok is True
    assert report.submitted_orders is True
    assert report.cancel_requested is True
    assert report.cancel_order_invoked is True
    assert report.canceled is True
    assert report.order_status == "Cancelled"
    assert fake.cancel_calls == 1


def test_paper_order_smoke_allows_ib_gateway_paper_port() -> None:
    fake = FakePaperOrderBroker(
        placement_result=placement(status="PreSubmitted", submitted=False)
    )

    report = run_paper_order_smoke(
        config(ibkr_port=4002, broker_kind=BrokerKind.IB_GATEWAY),
        request(),
        broker_factory=lambda _config: fake,
    )

    assert report.ok is True
    assert report.port == 4002
    assert report.broker_kind == "ib_gateway"
    assert fake.place_calls == 1


@pytest.mark.parametrize(
    ("bad_config", "expected_error"),
    [
        (unsafe_config(trading_mode="live"), "TRADING_MODE must be paper"),
        (unsafe_config(ibkr_port=7496), "live IBKR ports are rejected"),
        (
            unsafe_config(ibkr_port=1234),
            "IBKR_PORT must be 7497 (TWS paper) or 4002 (IB Gateway paper)",
        ),
        (config(allow_paper_orders=False), "ALLOW_PAPER_ORDERS=true is required"),
        (unsafe_config(allow_live_orders=True), "ALLOW_LIVE_ORDERS=true is rejected"),
        (unsafe_config(ibkr_host="localhost"), "IBKR_HOST must be 127.0.0.1"),
        (unsafe_config(ibkr_client_id=11), "IBKR_CLIENT_ID must be 21"),
    ],
)
def test_paper_order_smoke_rejects_config_gates(
    bad_config: TraderConfig,
    expected_error: str,
) -> None:
    fake = FakePaperOrderBroker()

    report = run_paper_order_smoke(
        bad_config,
        request(),
        broker_factory=lambda _config: fake,
    )

    assert report.final_status == PaperOrderSmokeRunStatus.FAILED
    assert any(expected_error in error for error in report.errors)
    assert fake.connected is False
    assert report.place_order_invoked is False


@pytest.mark.parametrize(
    ("bad_request", "expected_error"),
    [
        (request(confirm=""), "--confirm PAPER_SMOKE_SPY_1 is required"),
    ],
)
def test_paper_order_smoke_rejects_request_gates(
    bad_request: PaperOrderSmokeRequest,
    expected_error: str,
) -> None:
    fake = FakePaperOrderBroker()

    report = run_paper_order_smoke(
        config(),
        bad_request,
        broker_factory=lambda _config: fake,
    )

    assert report.final_status == PaperOrderSmokeRunStatus.FAILED
    assert any(expected_error in error for error in report.errors)
    assert fake.connected is False
    assert report.place_order_invoked is False


def test_paper_order_smoke_model_rejects_unsupported_order_type() -> None:
    with pytest.raises(ValueError, match="Input should be 'LIMIT'"):
        PaperOrderSmokeRequest(confirm=PAPER_SMOKE_CONFIRMATION, order_type="MKT")


def test_paper_order_smoke_model_rejects_short_sale_attempt() -> None:
    with pytest.raises(ValueError, match="BUY only"):
        PaperOrderSmokeRequest(confirm=PAPER_SMOKE_CONFIRMATION, action=TradeAction.SELL)


def test_paper_order_smoke_rejects_duplicate_open_order() -> None:
    fake = FakePaperOrderBroker(
        open_orders=[
            PaperBrokerOpenOrder(
                order_id=99,
                symbol="SPY",
                action="BUY",
                status="Submitted",
            )
        ]
    )

    report = run_paper_order_smoke(config(), request(), broker_factory=lambda _config: fake)

    assert report.final_status == PaperOrderSmokeRunStatus.FAILED
    assert report.duplicate_open_order_detected is True
    assert any("duplicate open SPY BUY order exists" in error for error in report.errors)
    assert fake.place_calls == 0


@pytest.mark.parametrize(
    "bad_quote",
    [
        quote(stale=True),
        PaperOrderQuote(symbol="SPY", stale=False),
    ],
)
def test_paper_order_smoke_rejects_stale_or_missing_quote(
    bad_quote: PaperOrderQuote,
) -> None:
    fake = FakePaperOrderBroker(quote_snapshot=bad_quote)

    report = run_paper_order_smoke(config(), request(), broker_factory=lambda _config: fake)

    assert report.final_status == PaperOrderSmokeRunStatus.FAILED
    assert fake.place_calls == 0


def test_paper_order_smoke_rejects_notional_above_configured_limit() -> None:
    fake = FakePaperOrderBroker(quote_snapshot=quote(bid=Decimal("500")))

    report = run_paper_order_smoke(
        config(max_trade_notional=Decimal("100")),
        request(),
        broker_factory=lambda _config: fake,
    )

    assert report.final_status == PaperOrderSmokeRunStatus.FAILED
    assert any("exceeds configured MAX_TRADE_NOTIONAL" in error for error in report.errors)
    assert fake.place_calls == 0


def test_paper_order_smoke_reports_read_only_order_rejection() -> None:
    fake = FakePaperOrderBroker(
        placement_result=placement(
            status=None,
            accepted=False,
            errors=["IBKR 201: Read-Only API rejects order placement"],
        )
    )

    report = run_paper_order_smoke(config(), request(), broker_factory=lambda _config: fake)

    assert report.final_status == PaperOrderSmokeRunStatus.FAILED
    assert report.place_order_invoked is True
    assert any("Read-Only API" in error for error in report.errors)


def test_paper_order_smoke_reports_unknown_cancel_refusal() -> None:
    fake = FakePaperOrderBroker(
        placement_result=placement(
            order_id=None,
            status="Submitted",
            accepted=True,
            submitted=True,
        ),
        cancel_result=placement(
            order_id=None,
            status=None,
            accepted=False,
            submitted=False,
            errors=["refused to cancel unknown paper smoke order id"],
        ),
    )

    report = run_paper_order_smoke(
        config(),
        request(transmit=True),
        broker_factory=lambda _config: fake,
    )

    assert report.final_status == PaperOrderSmokeRunStatus.FAILED
    assert report.cancel_requested is True
    assert report.cancel_order_invoked is True
    assert any("unknown paper smoke order id" in error for error in report.errors)


def test_paper_order_smoke_markdown_masks_accounts_and_renders_callbacks() -> None:
    report = run_paper_order_smoke(
        config(),
        request(),
        broker_factory=lambda _config: FakePaperOrderBroker(),
    )

    markdown = markdown_summary(report.model_dump(mode="json"))

    assert "# IBKR Paper Order Smoke Run" in markdown
    assert "DUQ2****23" in markdown
    assert "orderStatus" in markdown
    assert "submitted_orders" not in markdown


def test_order_api_calls_are_allowlisted_to_paper_order_smoke_executor() -> None:
    allowed = Path("src/trader/execution/paper_order_smoke.py")
    offenders: list[str] = []

    for path in Path("src").rglob("*.py"):
        source = path.read_text()
        if ("placeOrder" in source or "cancelOrder" in source) and path != allowed:
            offenders.append(path.as_posix())
        if "reqGlobalCancel" in source:
            offenders.append(path.as_posix())

    assert offenders == []
