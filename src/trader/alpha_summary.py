"""Offline paper alpha campaign summary."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from trader.models import (
    AlphaPaperRunReport,
    AlphaShadowRunReport,
    AlphaTestSummaryReport,
    AlphaTestSummaryRequest,
    AlphaTestSummaryStatus,
    PaperOrderSmokeReport,
    PaperReconcileReport,
    utc_now,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def run_alpha_test_summary(
    request: AlphaTestSummaryRequest | None = None,
    *,
    now: datetime | None = None,
) -> AlphaTestSummaryReport:
    """Summarize an ignored local paper alpha campaign without contacting IBKR."""

    summary_request = request or AlphaTestSummaryRequest()
    current_time = now or utc_now()
    current_commit = _current_commit_sha()
    source_paths = {
        "alpha_shadow_report": summary_request.alpha_shadow_report_path,
        "paper_smoke_report": summary_request.paper_smoke_report_path,
        "alpha_paper_report": summary_request.alpha_paper_report_path,
        "paper_reconcile_report": summary_request.paper_reconcile_report_path,
    }
    warnings = [
        "alpha-test-summary is offline-only and does not contact IBKR.",
        "Commodity execution remains out of scope; commodity proxies are research-only.",
    ]
    errors: list[str] = []

    shadow_report, shadow_errors = _load_report(
        Path(summary_request.alpha_shadow_report_path),
        AlphaShadowRunReport,
        label="alpha-shadow report",
    )
    smoke_report, smoke_errors = _load_report(
        Path(summary_request.paper_smoke_report_path),
        PaperOrderSmokeReport,
        label="paper-order-smoke report",
    )
    alpha_report, alpha_errors = _load_report(
        Path(summary_request.alpha_paper_report_path),
        AlphaPaperRunReport,
        label="alpha-paper report",
    )
    reconcile_report, reconcile_errors = _load_report(
        Path(summary_request.paper_reconcile_report_path),
        PaperReconcileReport,
        label="paper-reconcile report",
    )
    errors.extend(shadow_errors)
    errors.extend(smoke_errors)
    errors.extend(alpha_errors)
    errors.extend(reconcile_errors)
    selected_campaign_id, campaign_errors = _source_campaign_context(
        summary_request.campaign_id,
        {
            "alpha-shadow report": shadow_report,
            "paper-order-smoke report": smoke_report,
            "alpha-paper report": alpha_report,
            "paper-reconcile report": reconcile_report,
        },
    )
    errors.extend(campaign_errors)

    if shadow_report is not None:
        errors.extend(
            _alpha_shadow_errors(
                shadow_report,
                source_path=summary_request.alpha_shadow_report_path,
                current_commit=current_commit,
                now=current_time,
                max_age_hours=summary_request.max_report_age_hours,
            )
        )
    if smoke_report is not None:
        errors.extend(
            _paper_smoke_errors(
                smoke_report,
                source_path=summary_request.paper_smoke_report_path,
                current_commit=current_commit,
                now=current_time,
                max_age_hours=summary_request.max_report_age_hours,
            )
        )
    if alpha_report is not None:
        errors.extend(
            _alpha_paper_errors(
                alpha_report,
                source_path=summary_request.alpha_paper_report_path,
                current_commit=current_commit,
                now=current_time,
                max_age_hours=summary_request.max_report_age_hours,
            )
        )
    if reconcile_report is not None:
        errors.extend(
            _reconcile_errors(
                reconcile_report,
                source_path=summary_request.paper_reconcile_report_path,
                current_commit=current_commit,
                now=current_time,
                max_age_hours=summary_request.max_report_age_hours,
            )
        )
        if reconcile_report.open_order_count > 0:
            warnings.append("paper-reconcile reported open broker orders")
        if not reconcile_report.broker_positions_available:
            warnings.append("broker positions were unavailable or empty in reconciliation")

    errors.extend(
        _post_execution_reconcile_errors(
            smoke_report=smoke_report,
            alpha_report=alpha_report,
            reconcile_report=reconcile_report,
        )
    )

    next_reasons = _next_eligibility_reasons(
        errors=errors,
        shadow_report=shadow_report,
        smoke_report=smoke_report,
        alpha_report=alpha_report,
        reconcile_report=reconcile_report,
    )
    final_status = _final_status(
        errors=errors,
        warnings=warnings,
        next_reasons=next_reasons,
    )
    return _build_report(
        summary_request,
        current_commit=current_commit,
        campaign_id=selected_campaign_id,
        source_paths=source_paths,
        shadow_report=shadow_report,
        smoke_report=smoke_report,
        alpha_report=alpha_report,
        reconcile_report=reconcile_report,
        warnings=warnings,
        errors=errors,
        next_reasons=next_reasons,
        final_status=final_status,
    )


def _load_report(
    path: Path,
    model: type[ModelT],
    *,
    label: str,
) -> tuple[ModelT | None, list[str]]:
    payload, errors = _load_mapping(path, label=label)
    if payload is None:
        return None, errors
    try:
        return model.model_validate(payload), []
    except ValueError as exc:
        return None, [f"{label} is invalid: {exc}"]


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


def _alpha_shadow_errors(
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


def _paper_smoke_errors(
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


def _alpha_paper_errors(
    report: AlphaPaperRunReport,
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
        errors.append("alpha-paper report did not pass")
    if not report.alpha_shadow_report_verified:
        errors.append("alpha-paper report did not verify alpha-shadow prerequisite")
    if not report.paper_smoke_report_verified:
        errors.append("alpha-paper report did not verify paper-smoke prerequisite")
    if not report.submitted_orders:
        errors.append("alpha-paper report did not submit a paper order")
    if report.live_orders_enabled or report.live_route_possible:
        errors.append("alpha-paper report allowed live order risk")
    if report.fill_quantity != 0 and not report.request.allow_fill:
        errors.append("alpha-paper report filled while fills were disallowed")
    if report.fill_quantity == 0 and not report.canceled:
        errors.append("alpha-paper report did not prove cancel of unfilled order")
    return errors


def _reconcile_errors(
    report: PaperReconcileReport,
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
        errors.append("paper-reconcile report did not pass")
    if report.submitted_orders or report.order_api_invoked:
        errors.append("paper-reconcile unexpectedly invoked order routing")
    if report.live_orders_enabled or report.live_route_possible:
        errors.append("paper-reconcile report allowed live order risk")
    if not report.account_summary_verified:
        errors.append("paper-reconcile lacks verified account summary")
    return errors


def _post_execution_reconcile_errors(
    *,
    smoke_report: PaperOrderSmokeReport | None,
    alpha_report: AlphaPaperRunReport | None,
    reconcile_report: PaperReconcileReport | None,
) -> list[str]:
    """Require reconciliation evidence after the latest paper execution report."""

    if reconcile_report is None:
        return []
    execution_timestamps = [
        report.timestamp
        for report in (smoke_report, alpha_report)
        if report is not None and report.submitted_orders
    ]
    if not execution_timestamps:
        return []
    latest_execution_timestamp = max(execution_timestamps)
    if reconcile_report.timestamp < latest_execution_timestamp:
        return [
            "paper-reconcile report is older than the latest submitted paper order report"
        ]
    return []


def _source_campaign_context(
    request_campaign_id: str | None,
    reports: Mapping[
        str,
        AlphaShadowRunReport
        | PaperOrderSmokeReport
        | AlphaPaperRunReport
        | PaperReconcileReport
        | None,
    ],
) -> tuple[str | None, list[str]]:
    campaign_ids = {
        label: report.campaign_id
        for label, report in reports.items()
        if report is not None
    }
    present_ids = {campaign_id for campaign_id in campaign_ids.values() if campaign_id}
    selected_campaign_id = request_campaign_id
    if selected_campaign_id is None and len(present_ids) == 1:
        selected_campaign_id = next(iter(present_ids))

    errors: list[str] = []
    if len(present_ids) > 1:
        errors.append("source reports have mismatched campaign_id values")
    if selected_campaign_id is None:
        return None, errors
    for label, campaign_id in campaign_ids.items():
        if campaign_id is None:
            errors.append(f"{label} lacks campaign_id")
        elif campaign_id != selected_campaign_id:
            errors.append(f"{label} campaign_id does not match {selected_campaign_id}")
    return selected_campaign_id, errors


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
        errors.append(f"{source_path} lacks commit_sha; rerun the source command")
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


def _next_eligibility_reasons(
    *,
    errors: list[str],
    shadow_report: AlphaShadowRunReport | None,
    smoke_report: PaperOrderSmokeReport | None,
    alpha_report: AlphaPaperRunReport | None,
    reconcile_report: PaperReconcileReport | None,
) -> list[str]:
    reasons: list[str] = []
    if errors:
        reasons.append("source report errors must be resolved")
    if shadow_report is None or not shadow_report.ok:
        reasons.append("passing alpha-shadow report is required")
    if smoke_report is None or not smoke_report.ok:
        reasons.append("passing transmitted paper-smoke report is required")
    if alpha_report is None or not alpha_report.ok:
        reasons.append("passing alpha-paper report is required")
    if reconcile_report is None or not reconcile_report.ok:
        reasons.append("passing paper-reconcile report is required")
    elif reconcile_report.open_order_count > 0:
        reasons.append("open broker orders must be cleared before the next alpha window")
    if not reasons:
        reasons.append("ready_for_next_read_only_shadow")
    return _unique(reasons)


def _final_status(
    *,
    errors: list[str],
    warnings: list[str],
    next_reasons: list[str],
) -> AlphaTestSummaryStatus:
    if errors:
        return AlphaTestSummaryStatus.FAILED
    if warnings or next_reasons != ["ready_for_next_read_only_shadow"]:
        return AlphaTestSummaryStatus.COMPLETED_WITH_WARNINGS
    return AlphaTestSummaryStatus.COMPLETED


def _build_report(
    request: AlphaTestSummaryRequest,
    *,
    current_commit: str | None,
    campaign_id: str | None,
    source_paths: dict[str, str],
    shadow_report: AlphaShadowRunReport | None,
    smoke_report: PaperOrderSmokeReport | None,
    alpha_report: AlphaPaperRunReport | None,
    reconcile_report: PaperReconcileReport | None,
    warnings: list[str],
    errors: list[str],
    next_reasons: list[str],
    final_status: AlphaTestSummaryStatus,
) -> AlphaTestSummaryReport:
    account_ids = _unique(
        [
            *list(alpha_report.account_ids_masked if alpha_report else []),
            *list(reconcile_report.account_ids_masked if reconcile_report else []),
        ]
    )
    latest_order_ids = list(reconcile_report.latest_order_ids if reconcile_report else [])
    latest_perm_ids = list(reconcile_report.latest_perm_ids if reconcile_report else [])
    if alpha_report and alpha_report.order_id is not None:
        latest_order_ids.append(alpha_report.order_id)
    if smoke_report and smoke_report.order_id is not None:
        latest_order_ids.append(smoke_report.order_id)
    if alpha_report and alpha_report.perm_id is not None:
        latest_perm_ids.append(alpha_report.perm_id)
    if smoke_report and smoke_report.perm_id is not None:
        latest_perm_ids.append(smoke_report.perm_id)

    statuses = {
        "alpha_shadow_report": _status_text(shadow_report),
        "paper_smoke_report": _status_text(smoke_report),
        "alpha_paper_report": _status_text(alpha_report),
        "paper_reconcile_report": _status_text(reconcile_report),
    }
    commits = {
        "alpha_shadow_report": shadow_report.commit_sha if shadow_report else None,
        "paper_smoke_report": smoke_report.commit_sha if smoke_report else None,
        "alpha_paper_report": alpha_report.commit_sha if alpha_report else None,
        "paper_reconcile_report": reconcile_report.commit_sha if reconcile_report else None,
    }
    timestamps = {
        "alpha_shadow_report": shadow_report.timestamp if shadow_report else None,
        "paper_smoke_report": smoke_report.timestamp if smoke_report else None,
        "alpha_paper_report": alpha_report.timestamp if alpha_report else None,
        "paper_reconcile_report": reconcile_report.timestamp if reconcile_report else None,
    }
    report_request = (
        request
        if request.campaign_id == campaign_id
        else request.model_copy(update={"campaign_id": campaign_id})
    )
    return AlphaTestSummaryReport(
        ok=final_status != AlphaTestSummaryStatus.FAILED,
        request=report_request,
        commit_sha=current_commit,
        campaign_id=campaign_id,
        source_report_paths=source_paths,
        source_report_campaign_ids={
            "alpha_shadow_report": shadow_report.campaign_id if shadow_report else None,
            "paper_smoke_report": smoke_report.campaign_id if smoke_report else None,
            "alpha_paper_report": alpha_report.campaign_id if alpha_report else None,
            "paper_reconcile_report": (
                reconcile_report.campaign_id if reconcile_report else None
            ),
        },
        source_report_statuses=statuses,
        source_report_commits=commits,
        source_report_timestamps=timestamps,
        alpha_shadow_verified=bool(shadow_report and shadow_report.ok),
        paper_smoke_verified=bool(smoke_report and smoke_report.ok and smoke_report.transmitted),
        alpha_paper_verified=bool(alpha_report and alpha_report.ok),
        paper_reconcile_verified=bool(reconcile_report and reconcile_report.ok),
        account_ids_masked=account_ids,
        account_summary_verified=bool(
            reconcile_report and reconcile_report.account_summary_verified
        ),
        open_order_count=reconcile_report.open_order_count if reconcile_report else None,
        latest_order_ids=sorted(set(latest_order_ids)),
        latest_perm_ids=sorted(set(latest_perm_ids)),
        paper_smoke_order_status=smoke_report.order_status if smoke_report else None,
        paper_smoke_fill_quantity=smoke_report.fill_quantity if smoke_report else None,
        paper_smoke_canceled=smoke_report.canceled if smoke_report else None,
        alpha_paper_order_status=alpha_report.order_status if alpha_report else None,
        alpha_paper_fill_quantity=alpha_report.fill_quantity if alpha_report else None,
        alpha_paper_canceled=alpha_report.canceled if alpha_report else None,
        next_eligible_for_alpha_window=next_reasons == ["ready_for_next_read_only_shadow"]
        and not errors,
        next_eligibility_reason=next_reasons,
        warnings=_unique(warnings),
        errors=_unique(errors),
        submitted_orders=bool(
            (smoke_report and smoke_report.submitted_orders)
            or (alpha_report and alpha_report.submitted_orders)
        ),
        final_status=final_status,
    )


def _status_text(report: object | None) -> str:
    if report is None:
        return "missing"
    return _enum_value(getattr(report, "final_status", "unknown"))


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
