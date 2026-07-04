"""Strategy-gated IBKR alpha paper execution orchestration."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trader.config import LIVE_PORTS, PAPER_PORTS, TraderConfig, TradingMode
from trader.execution.paper_order_smoke import (
    PAPER_SMOKE_CONFIRMATION,
    IBKRPaperOrderBroker,
    PaperOrderBroker,
    run_paper_order_smoke,
)
from trader.models import (
    AlphaPaperRunReport,
    AlphaPaperRunRequest,
    AlphaPaperRunStatus,
    AlphaShadowRunReport,
    PaperOrderSmokeReport,
    PaperOrderSmokeRequest,
    SignalDirection,
    utc_now,
)

ALPHA_PAPER_CONFIRMATION = "ALPHA_PAPER_SPY_1"
ALPHA_PAPER_CLIENT_ID = 21

PaperOrderBrokerFactory = Callable[[TraderConfig], PaperOrderBroker]


def run_alpha_paper_run(
    config: TraderConfig,
    request: AlphaPaperRunRequest | None = None,
    *,
    broker_factory: PaperOrderBrokerFactory | None = None,
    now: datetime | None = None,
) -> AlphaPaperRunReport:
    """Run the first strategy-gated paper alpha order workflow."""

    alpha_request = request or AlphaPaperRunRequest()
    current_time = now or utc_now()
    current_commit = _current_commit_sha()
    warnings = [
        "IBKR Read-Only API must be disabled only while running alpha-paper-run.",
        "Re-enable IBKR Read-Only API immediately after the alpha paper run.",
        "This command refuses live ports, live mode, market orders, shorts, and batches.",
    ]
    errors = _config_errors(config, alpha_request)
    source_paths = {
        "alpha_shadow_report": alpha_request.alpha_shadow_report_path,
        "paper_smoke_report": alpha_request.paper_smoke_report_path,
    }

    if errors:
        return _build_report(
            config,
            alpha_request,
            current_commit=current_commit,
            source_report_paths=source_paths,
            warnings=warnings,
            errors=errors,
            final_status=AlphaPaperRunStatus.FAILED,
        )

    shadow_report, shadow_errors = _load_alpha_shadow_report(
        Path(alpha_request.alpha_shadow_report_path)
    )
    smoke_report, smoke_errors = _load_smoke_report(Path(alpha_request.paper_smoke_report_path))
    errors.extend(shadow_errors)
    errors.extend(smoke_errors)

    if shadow_report is not None:
        errors.extend(
            _alpha_shadow_report_errors(
                shadow_report,
                source_path=alpha_request.alpha_shadow_report_path,
                current_commit=current_commit,
                now=current_time,
                max_age_hours=alpha_request.max_report_age_hours,
            )
        )
    if smoke_report is not None:
        errors.extend(
            _paper_smoke_report_errors(
                smoke_report,
                source_path=alpha_request.paper_smoke_report_path,
                current_commit=current_commit,
                now=current_time,
                max_age_hours=alpha_request.max_report_age_hours,
            )
        )

    if errors:
        return _build_report(
            config,
            alpha_request,
            current_commit=current_commit,
            source_report_paths=source_paths,
            shadow_report=shadow_report,
            smoke_report=smoke_report,
            warnings=warnings,
            errors=errors,
            final_status=AlphaPaperRunStatus.FAILED,
        )

    assert shadow_report is not None
    assert smoke_report is not None
    shadow_signal = _shadow_signal_direction(shadow_report)
    risk_approved = shadow_report.risk_approved_count > 0
    if shadow_signal != SignalDirection.BUY.value:
        return _build_report(
            config,
            alpha_request,
            current_commit=current_commit,
            source_report_paths=source_paths,
            shadow_report=shadow_report,
            smoke_report=smoke_report,
            shadow_signal=shadow_signal,
            risk_approved=risk_approved,
            no_trade_reason="shadow_signal_not_buy",
            warnings=warnings,
            errors=[],
            final_status=AlphaPaperRunStatus.NO_TRADE,
        )
    if not risk_approved:
        return _build_report(
            config,
            alpha_request,
            current_commit=current_commit,
            source_report_paths=source_paths,
            shadow_report=shadow_report,
            smoke_report=smoke_report,
            shadow_signal=shadow_signal,
            risk_approved=False,
            no_trade_reason="shadow_risk_not_approved",
            warnings=warnings,
            errors=[],
            final_status=AlphaPaperRunStatus.NO_TRADE,
        )

    order_request = PaperOrderSmokeRequest(
        symbol=alpha_request.symbol,
        quantity=alpha_request.quantity,
        transmit=True,
        allow_fill=alpha_request.allow_fill,
        cancel_after_seconds=alpha_request.cancel_after_seconds,
        confirm=PAPER_SMOKE_CONFIRMATION,
        max_trade_notional=alpha_request.max_trade_notional,
        timeout_seconds=alpha_request.timeout_seconds,
    )
    paper_order_report = run_paper_order_smoke(
        config,
        order_request,
        broker_factory=broker_factory or IBKRPaperOrderBroker,
    )
    final_status = (
        AlphaPaperRunStatus.COMPLETED if paper_order_report.ok else AlphaPaperRunStatus.FAILED
    )
    return _build_report(
        config,
        alpha_request,
        current_commit=current_commit,
        source_report_paths=source_paths,
        shadow_report=shadow_report,
        smoke_report=smoke_report,
        paper_order_report=paper_order_report,
        shadow_signal=shadow_signal,
        risk_approved=risk_approved,
        warnings=warnings,
        errors=list(paper_order_report.errors),
        final_status=final_status,
    )


def _config_errors(config: TraderConfig, request: AlphaPaperRunRequest) -> list[str]:
    errors: list[str] = []
    if _enum_value(config.trading_mode) != TradingMode.PAPER.value:
        errors.append("TRADING_MODE must be paper for alpha-paper-run")
    if not config.allow_paper_orders:
        errors.append("ALLOW_PAPER_ORDERS=true is required for alpha-paper-run")
    if config.allow_live_orders:
        errors.append("ALLOW_LIVE_ORDERS=true is rejected")
    if config.ibkr_host != "127.0.0.1":
        errors.append("IBKR_HOST must be 127.0.0.1 for alpha-paper-run")
    if config.ibkr_port in LIVE_PORTS:
        errors.append("live IBKR ports are rejected")
    elif config.ibkr_port not in PAPER_PORTS:
        errors.append(
            "IBKR_PORT must be 7497 (TWS paper) or 4002 (IB Gateway paper) "
            "for alpha-paper-run"
        )
    if config.ibkr_client_id != ALPHA_PAPER_CLIENT_ID:
        errors.append("IBKR_CLIENT_ID must be 21 for alpha-paper-run")
    if request.confirm != ALPHA_PAPER_CONFIRMATION:
        errors.append(f"--confirm {ALPHA_PAPER_CONFIRMATION} is required")
    return errors


def _load_alpha_shadow_report(path: Path) -> tuple[AlphaShadowRunReport | None, list[str]]:
    payload, errors = _load_mapping(path, label="alpha-shadow report")
    if payload is None:
        return None, errors
    try:
        return AlphaShadowRunReport.model_validate(payload), []
    except ValueError as exc:
        return None, [f"alpha-shadow report is invalid: {exc}"]


def _load_smoke_report(path: Path) -> tuple[PaperOrderSmokeReport | None, list[str]]:
    payload, errors = _load_mapping(path, label="paper-order-smoke report")
    if payload is None:
        return None, errors
    try:
        return PaperOrderSmokeReport.model_validate(payload), []
    except ValueError as exc:
        return None, [f"paper-order-smoke report is invalid: {exc}"]


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


def _alpha_shadow_report_errors(
    report: AlphaShadowRunReport,
    *,
    source_path: str,
    current_commit: str | None,
    now: datetime,
    max_age_hours: int,
) -> list[str]:
    errors = _shared_report_errors(
        report.model_dump(mode="json"),
        source_path=source_path,
        current_commit=current_commit,
        now=now,
        max_age_hours=max_age_hours,
    )
    if not report.ok:
        errors.append("alpha-shadow report did not pass")
    if report.submitted_orders:
        errors.append("alpha-shadow report unexpectedly submitted orders")
    if report.paper_orders_enabled:
        errors.append("alpha-shadow report had paper orders enabled")
    if not report.account_summary_verified:
        errors.append("alpha-shadow report lacks verified account summary")
    if not report.signal_evaluation_completed:
        errors.append("alpha-shadow report lacks completed signal evaluation")
    return errors


def _paper_smoke_report_errors(
    report: PaperOrderSmokeReport,
    *,
    source_path: str,
    current_commit: str | None,
    now: datetime,
    max_age_hours: int,
) -> list[str]:
    errors = _shared_report_errors(
        report.model_dump(mode="json"),
        source_path=source_path,
        current_commit=current_commit,
        now=now,
        max_age_hours=max_age_hours,
    )
    if not report.ok:
        errors.append("paper-order-smoke report did not pass")
    if not report.transmitted:
        errors.append("paper-order-smoke report must be transmitted")
    if not report.submitted_orders:
        errors.append("paper-order-smoke report must prove a submitted paper order")
    if report.live_orders_enabled or report.live_route_possible:
        errors.append("paper-order-smoke report allowed live order risk")
    if report.fill_quantity != 0 and not report.request.allow_fill:
        errors.append("paper-order-smoke report filled while fills were disallowed")
    if report.fill_quantity == 0 and not report.canceled:
        errors.append("paper-order-smoke report did not prove cancel of unfilled order")
    return errors


def _shared_report_errors(
    payload: Mapping[str, Any],
    *,
    source_path: str,
    current_commit: str | None,
    now: datetime,
    max_age_hours: int,
) -> list[str]:
    errors: list[str] = []
    report_commit = payload.get("commit_sha")
    if not report_commit:
        errors.append(f"{source_path} lacks commit_sha; rerun the prerequisite command")
    elif current_commit is None:
        errors.append("current git commit could not be determined")
    elif report_commit != current_commit:
        errors.append(f"{source_path} was generated from a different commit")
    timestamp = _parse_timestamp(payload.get("timestamp"))
    if timestamp is None:
        errors.append(f"{source_path} lacks a valid timestamp")
    elif now - timestamp > timedelta(hours=max_age_hours):
        errors.append(f"{source_path} is older than {max_age_hours} hours")
    return errors


def _shadow_signal_direction(report: AlphaShadowRunReport) -> str | None:
    for signal in report.shadow_signals:
        if signal.symbol == "SPY":
            return _enum_value(signal.direction)
    return None


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=utc_now().tzinfo)
    return parsed


def _build_report(
    config: TraderConfig,
    request: AlphaPaperRunRequest,
    *,
    current_commit: str | None,
    source_report_paths: dict[str, str],
    shadow_report: AlphaShadowRunReport | None = None,
    smoke_report: PaperOrderSmokeReport | None = None,
    paper_order_report: PaperOrderSmokeReport | None = None,
    shadow_signal: str | None = None,
    risk_approved: bool = False,
    no_trade_reason: str | None = None,
    warnings: list[str],
    errors: list[str],
    final_status: AlphaPaperRunStatus,
) -> AlphaPaperRunReport:
    order_report = paper_order_report
    return AlphaPaperRunReport(
        ok=final_status != AlphaPaperRunStatus.FAILED,
        request=request,
        mode=_enum_value(config.trading_mode),
        host=config.ibkr_host,
        port=config.ibkr_port,
        client_id=config.ibkr_client_id,
        broker_kind=config.inferred_broker_kind,
        commit_sha=current_commit,
        source_report_paths=source_report_paths,
        alpha_shadow_report_verified=_prerequisite_verified(shadow_report, current_commit),
        paper_smoke_report_verified=_prerequisite_verified(smoke_report, current_commit),
        alpha_shadow_commit_sha=_model_extra_commit(shadow_report),
        paper_smoke_commit_sha=_model_extra_commit(smoke_report),
        alpha_shadow_timestamp=shadow_report.timestamp if shadow_report else None,
        paper_smoke_timestamp=smoke_report.timestamp if smoke_report else None,
        shadow_signal=shadow_signal,
        risk_approved=risk_approved,
        no_trade_reason=no_trade_reason,
        paper_order_report=order_report,
        account_ids_masked=list(order_report.account_ids_masked if order_report else []),
        submitted_orders=bool(order_report and order_report.submitted_orders),
        paper_orders_enabled=config.allow_paper_orders,
        configured_allow_paper_orders=config.allow_paper_orders,
        live_orders_enabled=config.allow_live_orders,
        order_routing_enabled=bool(order_report and order_report.order_api_invoked),
        paper_execution_enabled=config.allow_paper_orders,
        live_route_possible=bool(order_report and order_report.live_route_possible),
        order_api_invoked=bool(order_report and order_report.order_api_invoked),
        place_order_invoked=bool(order_report and order_report.place_order_invoked),
        cancel_order_invoked=bool(order_report and order_report.cancel_order_invoked),
        order_id=order_report.order_id if order_report else None,
        perm_id=order_report.perm_id if order_report else None,
        order_status=order_report.order_status if order_report else None,
        fill_quantity=order_report.fill_quantity if order_report else Decimal("0"),
        cancel_requested=bool(order_report and order_report.cancel_requested),
        canceled=bool(order_report and order_report.canceled),
        warnings=_unique([*warnings, *list(order_report.warnings if order_report else [])]),
        errors=_unique(errors),
        final_status=final_status,
    )


def _model_extra_commit(model: AlphaShadowRunReport | PaperOrderSmokeReport | None) -> str | None:
    if model is None:
        return None
    return model.commit_sha


def _prerequisite_verified(
    model: AlphaShadowRunReport | PaperOrderSmokeReport | None,
    current_commit: str | None,
) -> bool:
    return bool(model and model.ok and model.commit_sha and model.commit_sha == current_commit)


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


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))
