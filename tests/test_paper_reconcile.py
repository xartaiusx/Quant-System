from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trader.config import BrokerKind, TraderConfig, TradingMode
from trader.execution.paper_order_smoke import PaperBrokerOpenOrder
from trader.models import (
    AlphaPaperRunReport,
    AlphaPaperRunRequest,
    AlphaPaperRunStatus,
    BrokerDiagnosticReport,
    ManagedAccountInfo,
    PaperOrderSmokeReport,
    PaperOrderSmokeRequest,
    PaperOrderSmokeRunStatus,
    PaperReconcileRequest,
    PaperReconcileStatus,
)
from trader.paper_reconcile import run_paper_reconcile
from trader.reporting.reports import markdown_summary


def now() -> datetime:
    return datetime(2026, 7, 4, 16, tzinfo=UTC)


def config(**overrides: object) -> TraderConfig:
    values: dict[str, object] = {
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 4002,
        "ibkr_client_id": 11,
        "broker_kind": BrokerKind.IB_GATEWAY,
        "trading_mode": TradingMode.PAPER,
        "allow_paper_orders": False,
        "allow_live_orders": False,
        "max_trade_notional": Decimal("1000"),
    }
    values.update(overrides)
    return TraderConfig(**values)


def request(tmp_path: Path) -> PaperReconcileRequest:
    return PaperReconcileRequest(
        timeout_seconds=1,
        paper_smoke_report_path=(tmp_path / "smoke.json").as_posix(),
        alpha_paper_report_path=(tmp_path / "alpha.json").as_posix(),
    )


def broker_report(*, account: bool = True, positions: bool = True) -> BrokerDiagnosticReport:
    return BrokerDiagnosticReport(
        ok=True,
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=11,
        broker_kind="ib_gateway",
        connected=True,
        ibapi_available=True,
        connection_attempted=True,
        managed_accounts_masked=[ManagedAccountInfo(account_id_masked="DUQ2****23")],
        account_snapshot=(
            {
                "DUQ2****23": {
                    "NetLiquidation": {"value": "1000000", "currency": "USD"},
                    "BuyingPower": {"value": "4000000", "currency": "USD"},
                }
            }
            if account
            else None
        ),
        positions_snapshot=(
            [{"account": "DUQ2****23", "symbol": "SPY", "position": "0"}]
            if positions
            else []
        ),
        final_status="connected",
    )


def smoke_report() -> PaperOrderSmokeReport:
    return PaperOrderSmokeReport(
        ok=True,
        commit_sha="abc123",
        request=PaperOrderSmokeRequest(
            confirm="PAPER_SMOKE_SPY_1",
            transmit=True,
            cancel_after_seconds=0,
        ),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=21,
        broker_kind="ib_gateway",
        broker_connected=True,
        account_summary_verified=True,
        submitted_orders=True,
        paper_orders_enabled=True,
        configured_allow_paper_orders=True,
        order_api_invoked=True,
        place_order_invoked=True,
        cancel_order_invoked=True,
        transmitted=True,
        order_id=22,
        perm_id=2200,
        order_status="Cancelled",
        fill_quantity=Decimal("0"),
        cancel_requested=True,
        canceled=True,
        final_status=PaperOrderSmokeRunStatus.COMPLETED,
        timestamp=now(),
    )


def alpha_report() -> AlphaPaperRunReport:
    return AlphaPaperRunReport(
        ok=True,
        commit_sha="abc123",
        request=AlphaPaperRunRequest(
            confirm="ALPHA_PAPER_SPY_1",
            cancel_after_seconds=0,
        ),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=21,
        broker_kind="ib_gateway",
        alpha_shadow_report_verified=True,
        paper_smoke_report_verified=True,
        submitted_orders=True,
        paper_orders_enabled=True,
        configured_allow_paper_orders=True,
        order_api_invoked=True,
        place_order_invoked=True,
        cancel_order_invoked=True,
        order_id=23,
        perm_id=2300,
        order_status="Cancelled",
        fill_quantity=Decimal("0"),
        cancel_requested=True,
        canceled=True,
        final_status=AlphaPaperRunStatus.COMPLETED,
        timestamp=now(),
    )


def write_reports(tmp_path: Path) -> PaperReconcileRequest:
    selected_request = request(tmp_path)
    Path(selected_request.paper_smoke_report_path).write_text(
        json.dumps(smoke_report().model_dump(mode="json"))
    )
    Path(selected_request.alpha_paper_report_path).write_text(
        json.dumps(alpha_report().model_dump(mode="json"))
    )
    return selected_request


class FakeBrokerClient:
    def __init__(self, report: BrokerDiagnosticReport) -> None:
        self.report = report
        self.include_account = False
        self.include_positions = False

    def diagnostic_report(
        self,
        *,
        timeout: float | None = None,
        include_managed_accounts: bool = True,
        include_account: bool = False,
        include_positions: bool = False,
    ) -> BrokerDiagnosticReport:
        del timeout, include_managed_accounts
        self.include_account = include_account
        self.include_positions = include_positions
        return self.report


class FakeOpenOrderBroker:
    def __init__(self, orders: list[PaperBrokerOpenOrder] | None = None) -> None:
        self.orders = orders or []
        self.connected = False
        self.disconnected = False

    def connect(self, *, timeout: float) -> None:
        del timeout
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def request_open_orders(self, *, timeout: float) -> list[PaperBrokerOpenOrder]:
        del timeout
        return self.orders


def test_paper_reconcile_success_serializes_and_keeps_no_order_guarantee(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.paper_reconcile._current_commit_sha", lambda: "abc123")
    selected_request = write_reports(tmp_path)
    client = FakeBrokerClient(broker_report())
    open_broker = FakeOpenOrderBroker()

    report = run_paper_reconcile(
        config(),
        selected_request,
        broker_client_factory=lambda _: client,
        open_order_broker_factory=lambda _: open_broker,
    )

    assert report.ok is True
    assert report.final_status == PaperReconcileStatus.COMPLETED_WITH_WARNINGS
    assert client.include_account is True
    assert client.include_positions is True
    assert open_broker.disconnected is True
    assert report.account_summary_verified is True
    assert report.open_order_count == 0
    assert report.latest_order_ids == [22, 23]
    assert report.latest_perm_ids == [2200, 2300]
    assert report.submitted_orders is False
    assert report.order_routing_enabled is False
    assert report.order_api_invoked is False

    payload = report.model_dump(mode="json")
    assert payload["submitted_orders"] is False
    markdown = markdown_summary(payload)
    assert "IBKR Paper Reconciliation" in markdown
    assert "No order guarantee" in markdown


def test_paper_reconcile_reports_open_order_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.paper_reconcile._current_commit_sha", lambda: "abc123")
    selected_request = write_reports(tmp_path)
    open_order = PaperBrokerOpenOrder(
        order_id=24,
        symbol="SPY",
        action="BUY",
        status="Submitted",
        perm_id=2400,
    )

    report = run_paper_reconcile(
        config(),
        selected_request,
        broker_client_factory=lambda _: FakeBrokerClient(broker_report()),
        open_order_broker_factory=lambda _: FakeOpenOrderBroker([open_order]),
    )

    assert report.ok is True
    assert report.final_status == PaperReconcileStatus.COMPLETED_WITH_WARNINGS
    assert report.open_order_count == 1
    assert "broker reported open orders" in " ".join(report.warnings)


def test_paper_reconcile_rejects_mock_fallback_account(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.paper_reconcile._current_commit_sha", lambda: "abc123")
    selected_request = write_reports(tmp_path)

    report = run_paper_reconcile(
        config(),
        selected_request,
        broker_client_factory=lambda _: FakeBrokerClient(broker_report(account=False)),
        open_order_broker_factory=lambda _: FakeOpenOrderBroker(),
    )

    assert report.ok is False
    assert report.final_status == PaperReconcileStatus.FAILED
    assert report.account_summary_verified is False
    assert "mock fallback is not accepted" in " ".join(report.errors)


def test_paper_reconcile_config_gate_blocks_allow_paper_orders(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.paper_reconcile._current_commit_sha", lambda: "abc123")
    selected_request = write_reports(tmp_path)

    report = run_paper_reconcile(
        config(allow_paper_orders=True),
        selected_request,
        broker_client_factory=lambda _: FakeBrokerClient(broker_report()),
        open_order_broker_factory=lambda _: FakeOpenOrderBroker(),
    )

    assert report.ok is False
    assert report.final_status == PaperReconcileStatus.FAILED
    assert report.configured_allow_paper_orders is True
    assert "ALLOW_PAPER_ORDERS=false" in " ".join(report.errors)


def test_paper_reconcile_does_not_call_order_mutations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.paper_reconcile._current_commit_sha", lambda: "abc123")
    selected_request = write_reports(tmp_path)

    class MutationTrackingOpenOrderBroker(FakeOpenOrderBroker):
        def __init__(self) -> None:
            super().__init__()
            self.place_calls = 0
            self.cancel_calls = 0

        def place_limit_order(self, **_: object) -> None:
            self.place_calls += 1

        def cancel_order(self, *_: object, **__: object) -> None:
            self.cancel_calls += 1

    open_broker = MutationTrackingOpenOrderBroker()
    report = run_paper_reconcile(
        config(),
        selected_request,
        broker_client_factory=lambda _: FakeBrokerClient(broker_report()),
        open_order_broker_factory=lambda _: open_broker,
    )

    assert report.ok is True
    assert open_broker.place_calls == 0
    assert open_broker.cancel_calls == 0
    assert report.place_order_invoked is False
    assert report.cancel_order_invoked is False
