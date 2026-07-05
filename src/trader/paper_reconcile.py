"""Read-only post-paper-run broker reconciliation."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast

from trader.config import LIVE_PORTS, PAPER_PORTS, TraderConfig, TradingMode
from trader.execution.paper_order_smoke import (
    IBKRPaperOrderBroker,
    PaperBrokerCommissionReport,
    PaperBrokerExecution,
    PaperBrokerOpenOrder,
)
from trader.models import (
    AlphaPaperRunReport,
    BrokerDiagnosticReport,
    BrokerOpenOrderSnapshot,
    PaperOrderEvidence,
    PaperOrderSmokeReport,
    PaperReconcileReport,
    PaperReconcileRequest,
    PaperReconcileStatus,
)


class ReconcileBrokerClient(Protocol):
    """Read-only broker surface required for reconciliation."""

    def diagnostic_report(
        self,
        *,
        timeout: float | None = None,
        include_managed_accounts: bool = True,
        include_account: bool = False,
        include_positions: bool = False,
    ) -> BrokerDiagnosticReport:
        """Return broker diagnostics without order routing."""


class ReconcileOrderBroker(Protocol):
    """Read-only order-state surface required for reconciliation."""

    def connect(self, *, timeout: float) -> None:
        """Connect to the broker."""

    def disconnect(self) -> None:
        """Disconnect from the broker."""

    def request_open_orders(self, *, timeout: float) -> list[PaperBrokerOpenOrder]:
        """Return current open orders without modifying them."""

    def request_executions(
        self,
        *,
        timeout: float,
    ) -> tuple[list[PaperBrokerExecution], list[PaperBrokerCommissionReport]]:
        """Return current-day execution and commission evidence."""


BrokerClientFactory = Callable[[TraderConfig], ReconcileBrokerClient]
OpenOrderBrokerFactory = Callable[[TraderConfig], ReconcileOrderBroker]


def default_broker_client_factory(config: TraderConfig) -> ReconcileBrokerClient:
    """Create the read-only IBKR client lazily."""

    from trader.broker.ibkr_client import IBKRClient

    return cast(ReconcileBrokerClient, IBKRClient(config))


def run_paper_reconcile(
    config: TraderConfig,
    request: PaperReconcileRequest | None = None,
    *,
    broker_client_factory: BrokerClientFactory = default_broker_client_factory,
    open_order_broker_factory: OpenOrderBrokerFactory = IBKRPaperOrderBroker,
) -> PaperReconcileReport:
    """Collect read-only broker state after a paper execution window."""

    reconcile_request = request or PaperReconcileRequest()
    current_commit = _current_commit_sha()
    warnings = [
        "IBKR Read-Only API is expected to be re-enabled before paper-reconcile.",
        "No order APIs are invoked by paper-reconcile.",
    ]
    errors = _config_errors(config)
    source_report_paths = {
        "paper_smoke_report": reconcile_request.paper_smoke_report_path,
        "alpha_paper_report": reconcile_request.alpha_paper_report_path,
    }

    if errors:
        return _build_report(
            config,
            reconcile_request,
            current_commit=current_commit,
            source_report_paths=source_report_paths,
            warnings=warnings,
            errors=errors,
            final_status=PaperReconcileStatus.FAILED,
        )

    broker_report: BrokerDiagnosticReport | None = None
    open_orders: list[BrokerOpenOrderSnapshot] = []
    executions: list[PaperBrokerExecution] = []
    commission_reports: list[PaperBrokerCommissionReport] = []
    open_order_query_failed = False
    execution_query_failed = False

    try:
        broker_report = broker_client_factory(config).diagnostic_report(
            timeout=reconcile_request.timeout_seconds,
            include_managed_accounts=True,
            include_account=True,
            include_positions=True,
        )
    except Exception as exc:  # pragma: no cover - defensive real-broker boundary
        errors.append(f"broker reconciliation diagnostic failed: {exc}")

    if broker_report is not None:
        warnings.extend(broker_report.warnings)
        broker_error_messages = _broker_error_messages(broker_report)
        if broker_report.account_snapshot:
            warnings.extend(broker_error_messages)
        else:
            errors.extend(broker_error_messages)

    open_order_broker = open_order_broker_factory(config)
    try:
        open_order_broker.connect(timeout=reconcile_request.timeout_seconds)
        try:
            open_orders = [
                _open_order_snapshot(order)
                for order in open_order_broker.request_open_orders(
                    timeout=reconcile_request.timeout_seconds
                )
            ]
        except Exception as exc:
            open_order_query_failed = True
            errors.append(f"open-order reconciliation failed: {exc}")
        try:
            executions, commission_reports = open_order_broker.request_executions(
                timeout=reconcile_request.timeout_seconds
            )
        except Exception as exc:
            execution_query_failed = True
            errors.append(f"execution-history reconciliation failed: {exc}")
    except Exception as exc:
        open_order_query_failed = True
        execution_query_failed = True
        errors.append(f"broker order-state reconciliation failed: {exc}")
    finally:
        with suppress(Exception):
            open_order_broker.disconnect()

    order_evidence, evidence_warnings = _load_order_evidence(source_report_paths)
    warnings.extend(evidence_warnings)
    if open_orders:
        warnings.append("broker reported open orders after the paper execution window")

    account_verified = bool(broker_report and broker_report.account_snapshot)
    if not account_verified:
        errors.append("broker account summary is unavailable; mock fallback is not accepted")
    if open_order_query_failed:
        errors.append("broker open-order query is unavailable")
    if execution_query_failed:
        errors.append("broker execution-history query is unavailable")
    missing_filled_execution_ids = _missing_filled_execution_ids(order_evidence, executions)
    if missing_filled_execution_ids:
        errors.append(
            "filled paper order evidence is missing broker execution rows for order IDs "
            f"{','.join(str(order_id) for order_id in missing_filled_execution_ids)}"
        )

    final_status = _final_status(errors=errors, warnings=warnings, open_orders=open_orders)
    return _build_report(
        config,
        reconcile_request,
        current_commit=current_commit,
        source_report_paths=source_report_paths,
        broker_report=broker_report,
        open_orders=open_orders,
        executions=executions,
        commission_reports=commission_reports,
        order_evidence=order_evidence,
        warnings=warnings,
        errors=errors,
        final_status=final_status,
    )


def _config_errors(config: TraderConfig) -> list[str]:
    errors: list[str] = []
    if _enum_value(config.trading_mode) != TradingMode.PAPER.value:
        errors.append("TRADING_MODE must be paper for paper-reconcile")
    if config.allow_paper_orders:
        errors.append("ALLOW_PAPER_ORDERS=false is required for paper-reconcile")
    if config.allow_live_orders:
        errors.append("ALLOW_LIVE_ORDERS=true is rejected")
    if config.ibkr_host != "127.0.0.1":
        errors.append("IBKR_HOST must be 127.0.0.1 for paper-reconcile")
    if config.ibkr_port in LIVE_PORTS:
        errors.append("live IBKR ports are rejected")
    elif config.ibkr_port not in PAPER_PORTS:
        errors.append(
            "IBKR_PORT must be 7497 (TWS paper) or 4002 (IB Gateway paper) "
            "for paper-reconcile"
        )
    return errors


def _open_order_snapshot(order: PaperBrokerOpenOrder) -> BrokerOpenOrderSnapshot:
    return BrokerOpenOrderSnapshot(
        order_id=order.order_id,
        symbol=order.symbol,
        action=order.action,
        status=order.status,
        perm_id=order.perm_id,
    )


def _load_order_evidence(paths: Mapping[str, str]) -> tuple[list[PaperOrderEvidence], list[str]]:
    evidence: list[PaperOrderEvidence] = []
    warnings: list[str] = []
    for label, raw_path in paths.items():
        path = Path(raw_path)
        payload, errors = _load_mapping(path, label=label)
        if payload is None:
            warnings.extend(errors)
            continue
        try:
            if label == "paper_smoke_report":
                smoke_report = PaperOrderSmokeReport.model_validate(payload)
                evidence.append(_smoke_evidence(label, raw_path, smoke_report))
            elif label == "alpha_paper_report":
                alpha_report = AlphaPaperRunReport.model_validate(payload)
                evidence.append(_alpha_evidence(label, raw_path, alpha_report))
        except ValueError as exc:
            warnings.append(f"{label} is invalid: {exc}")
    return evidence, warnings


def _smoke_evidence(
    source: str,
    path: str,
    report: PaperOrderSmokeReport,
) -> PaperOrderEvidence:
    return PaperOrderEvidence(
        source=source,
        report_path=path,
        report_type=report.report_type,
        ok=report.ok,
        final_status=_enum_value(report.final_status),
        commit_sha=report.commit_sha,
        timestamp=report.timestamp,
        submitted_orders=report.submitted_orders,
        order_id=report.order_id,
        perm_id=report.perm_id,
        order_status=report.order_status,
        fill_quantity=report.fill_quantity,
        canceled=report.canceled,
        cancel_requested=report.cancel_requested,
        live_orders_enabled=report.live_orders_enabled,
        live_route_possible=report.live_route_possible,
    )


def _alpha_evidence(
    source: str,
    path: str,
    report: AlphaPaperRunReport,
) -> PaperOrderEvidence:
    return PaperOrderEvidence(
        source=source,
        report_path=path,
        report_type=report.report_type,
        ok=report.ok,
        final_status=_enum_value(report.final_status),
        commit_sha=report.commit_sha,
        timestamp=report.timestamp,
        submitted_orders=report.submitted_orders,
        order_id=report.order_id,
        perm_id=report.perm_id,
        order_status=report.order_status,
        fill_quantity=report.fill_quantity,
        canceled=report.canceled,
        cancel_requested=report.cancel_requested,
        live_orders_enabled=report.live_orders_enabled,
        live_route_possible=report.live_route_possible,
    )


def _load_mapping(path: Path, *, label: str) -> tuple[Mapping[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [f"{label} not found at {path.as_posix()}"]
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{label} could not be read: {exc}"]
    if not isinstance(payload, Mapping):
        return None, [f"{label} did not contain a JSON object"]
    return payload, []


def _final_status(
    *,
    errors: list[str],
    warnings: list[str],
    open_orders: list[BrokerOpenOrderSnapshot],
) -> PaperReconcileStatus:
    if errors:
        return PaperReconcileStatus.FAILED
    if warnings or open_orders:
        return PaperReconcileStatus.COMPLETED_WITH_WARNINGS
    return PaperReconcileStatus.COMPLETED


def _build_report(
    config: TraderConfig,
    request: PaperReconcileRequest,
    *,
    current_commit: str | None,
    source_report_paths: dict[str, str],
    warnings: list[str],
    errors: list[str],
    final_status: PaperReconcileStatus,
    broker_report: BrokerDiagnosticReport | None = None,
    open_orders: list[BrokerOpenOrderSnapshot] | None = None,
    executions: list[PaperBrokerExecution] | None = None,
    commission_reports: list[PaperBrokerCommissionReport] | None = None,
    order_evidence: list[PaperOrderEvidence] | None = None,
) -> PaperReconcileReport:
    selected_open_orders = open_orders or []
    selected_executions = executions or []
    selected_commissions = commission_reports or []
    selected_evidence = order_evidence or []
    account_snapshot = (
        broker_report.account_snapshot
        if broker_report and broker_report.account_snapshot
        else {}
    )
    positions = list(broker_report.positions_snapshot if broker_report else [])
    positions_query_completed = bool(broker_report and broker_report.positions_query_completed)
    zero_positions_confirmed = positions_query_completed and not positions
    positions_unavailable_reason = (
        None
        if positions_query_completed
        else "positions request did not complete or broker diagnostic was unavailable"
    )
    account_ids = sorted(account_snapshot) if account_snapshot else []
    evidence_order_ids = [
        evidence.order_id for evidence in selected_evidence if evidence.order_id is not None
    ]
    evidence_perm_ids = [
        evidence.perm_id for evidence in selected_evidence if evidence.perm_id is not None
    ]
    execution_rows = [_execution_snapshot(execution) for execution in selected_executions]
    commission_rows = [_commission_snapshot(report) for report in selected_commissions]
    execution_order_ids = sorted(
        {
            execution.order_id
            for execution in selected_executions
            if execution.order_id is not None
        }
    )
    fingerprint = _broker_state_fingerprint(
        account_ids=account_ids,
        positions=positions,
        open_orders=[order.model_dump(mode="json") for order in selected_open_orders],
        executions=execution_rows,
        latest_order_ids=sorted(set(evidence_order_ids)),
        latest_perm_ids=sorted(set(evidence_perm_ids)),
    )
    return PaperReconcileReport(
        ok=final_status != PaperReconcileStatus.FAILED,
        request=request,
        mode=_enum_value(config.trading_mode),
        host=config.ibkr_host,
        port=config.ibkr_port,
        client_id=config.ibkr_client_id,
        broker_kind=config.inferred_broker_kind,
        commit_sha=current_commit,
        broker_connected=bool(broker_report and broker_report.connected),
        account_summary_verified=bool(account_snapshot),
        account_summary_source=(
            "broker_read_only_account_summary"
            if account_snapshot
            else "unavailable_or_mock_fallback_rejected"
        ),
        account_ids_masked=account_ids,
        account_snapshot=dict(account_snapshot),
        positions_snapshot=positions,
        positions_source=(
            "broker_read_only_positions"
            if positions_query_completed
            else "unavailable_or_mock_fallback_rejected"
        ),
        broker_positions_available=positions_query_completed,
        positions_query_completed=positions_query_completed,
        zero_positions_confirmed=zero_positions_confirmed,
        positions_unavailable_reason=positions_unavailable_reason,
        open_orders=selected_open_orders,
        open_order_count=len(selected_open_orders),
        executions_snapshot=execution_rows,
        executions_available=bool(execution_rows),
        executions_source="broker_read_only_current_day_executions",
        execution_order_ids=execution_order_ids,
        commission_reports=commission_rows,
        broker_state_fingerprint=fingerprint,
        source_report_paths=source_report_paths,
        latest_order_evidence=selected_evidence,
        latest_order_ids=sorted(set(evidence_order_ids)),
        latest_perm_ids=sorted(set(evidence_perm_ids)),
        warnings=_unique(warnings),
        errors=_unique(errors),
        paper_orders_enabled=False,
        configured_allow_paper_orders=config.allow_paper_orders,
        live_orders_enabled=config.allow_live_orders,
        final_status=final_status,
    )


def _broker_error_messages(report: BrokerDiagnosticReport) -> list[str]:
    return [
        f"IBKR {error.code}: {error.message}" if error.code is not None else error.message
        for error in report.errors
    ]


def _execution_snapshot(execution: PaperBrokerExecution) -> dict[str, Any]:
    row = asdict(execution)
    return {key: _json_scalar(value) for key, value in row.items()}


def _commission_snapshot(report: PaperBrokerCommissionReport) -> dict[str, Any]:
    row = asdict(report)
    return {key: _json_scalar(value) for key, value in row.items()}


def _missing_filled_execution_ids(
    evidence: list[PaperOrderEvidence],
    executions: list[PaperBrokerExecution],
) -> list[int]:
    execution_order_ids = {
        execution.order_id for execution in executions if execution.order_id is not None
    }
    return sorted(
        {
            evidence_row.order_id
            for evidence_row in evidence
            if evidence_row.order_id is not None
            and evidence_row.fill_quantity is not None
            and evidence_row.fill_quantity > 0
            and evidence_row.order_id not in execution_order_ids
        }
    )


def _broker_state_fingerprint(
    *,
    account_ids: list[str],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    latest_order_ids: list[int],
    latest_perm_ids: list[int],
) -> str:
    payload = {
        "account_ids": account_ids,
        "positions": positions,
        "open_orders": open_orders,
        "executions": executions,
        "latest_order_ids": latest_order_ids,
        "latest_perm_ids": latest_perm_ids,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return sha256(encoded).hexdigest()


def _json_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _current_commit_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit_sha = result.stdout.strip()
    return commit_sha or None


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
