"""Offline alpha-shadow-daemon session summary and drift gate."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from datetime import datetime, timedelta
from glob import glob
from pathlib import Path
from typing import Any

from trader.models import (
    AlphaShadowDaemonReport,
    AlphaShadowDaemonReportEvidence,
    AlphaShadowDaemonSummaryReport,
    AlphaShadowDaemonSummaryRequest,
    AlphaShadowDaemonSummaryStatus,
    utc_now,
)


def run_alpha_shadow_daemon_summary(
    request: AlphaShadowDaemonSummaryRequest | None = None,
    *,
    now: datetime | None = None,
) -> AlphaShadowDaemonSummaryReport:
    """Summarize ignored local alpha-shadow-daemon reports without contacting IBKR."""

    summary_request = request or AlphaShadowDaemonSummaryRequest()
    current_time = now or utc_now()
    current_commit = _current_commit_sha()
    warnings = [
        "alpha-shadow-daemon-summary is offline-only and does not contact IBKR.",
        "Paper execution remains out of scope until repeated clean shadow evidence exists.",
        "Commodity execution remains out of scope; commodity proxies are research-only.",
    ]
    errors: list[str] = []
    source_paths = _matching_report_paths(summary_request.report_glob)
    if not source_paths:
        errors.append(f"no alpha-shadow-daemon reports matched {summary_request.report_glob}")

    source_reports: list[AlphaShadowDaemonReportEvidence] = []
    for source_path in source_paths:
        payload, load_errors = _load_mapping(source_path)
        errors.extend(load_errors)
        if payload is None:
            continue

        evidence = _evidence_from_payload(source_path, payload)
        validation_errors = _validate_report_payload(source_path, payload)
        report_errors = _source_report_errors(
            evidence,
            current_commit=current_commit,
            now=current_time,
            request=summary_request,
        )
        heartbeat_warning = _heartbeat_warning(evidence)
        if heartbeat_warning is not None:
            warnings.append(heartbeat_warning)

        source_reports.append(
            evidence.model_copy(
                update={
                    "errors": _unique(
                        [
                            *evidence.errors,
                            *validation_errors,
                            *report_errors,
                        ]
                    )
                }
            )
        )
        errors.extend(validation_errors)
        errors.extend(report_errors)

    clean_session_count = sum(1 for report in source_reports if _clean_session(report))
    graduation_ready = (
        clean_session_count >= summary_request.min_clean_sessions
        and not errors
        and bool(source_reports)
    )
    next_reasons = _next_eligibility_reasons(
        errors=errors,
        clean_session_count=clean_session_count,
        min_clean_sessions=summary_request.min_clean_sessions,
    )
    final_status = _final_status(
        errors=errors,
        warnings=warnings,
        graduation_ready=graduation_ready,
    )
    return AlphaShadowDaemonSummaryReport(
        ok=final_status != AlphaShadowDaemonSummaryStatus.FAILED,
        request=summary_request,
        commit_sha=current_commit,
        source_report_paths=[path.as_posix() for path in source_paths],
        source_reports=source_reports,
        session_count=len(source_reports),
        total_cycles=sum(report.cycle_count for report in source_reports),
        total_clean_cycles=sum(report.clean_cycle_count for report in source_reports),
        clean_session_count=clean_session_count,
        stale_session_count=sum(1 for report in source_reports if report.stale_data_detected),
        stale_cycle_count=sum(report.stale_cycle_count for report in source_reports),
        broker_connected_cycles=sum(
            report.broker_connected_cycles for report in source_reports
        ),
        account_summary_verified_cycles=sum(
            report.account_summary_verified_cycles for report in source_reports
        ),
        broker_connected_sessions=sum(
            1
            for report in source_reports
            if report.cycle_count > 0 and report.broker_connected_cycles >= report.cycle_count
        ),
        account_summary_verified_sessions=sum(
            1
            for report in source_reports
            if report.cycle_count > 0
            and report.account_summary_verified_cycles >= report.cycle_count
        ),
        missing_heartbeat_count=sum(
            1 for report in source_reports if not report.heartbeat_present
        ),
        heartbeat_mismatch_count=sum(
            1 for report in source_reports if report.heartbeat_campaign_matches is False
        ),
        safety_violation_count=sum(1 for report in source_reports if _safety_violation(report)),
        commit_shas=sorted(
            {report.commit_sha for report in source_reports if report.commit_sha}
        ),
        campaign_ids=sorted(
            {report.campaign_id for report in source_reports if report.campaign_id}
        ),
        warning_fingerprints=_fingerprints(
            [warning for report in source_reports for warning in report.warnings]
            + warnings
        ),
        error_fingerprints=_fingerprints(errors),
        graduation_ready=graduation_ready,
        next_eligibility_reason=next_reasons,
        warnings=_unique(warnings),
        errors=_unique(errors),
        final_status=final_status,
    )


def _matching_report_paths(report_glob: str) -> list[Path]:
    return [
        path
        for path in sorted(Path(match) for match in glob(report_glob))
        if path.is_file()
        and not path.name.startswith("latest_")
        and not path.name.startswith("alpha_shadow_daemon_summary_")
    ]


def _load_mapping(path: Path) -> tuple[Mapping[str, Any] | None, list[str]]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{path.as_posix()} could not be read: {exc}"]
    if not isinstance(payload, Mapping):
        return None, [f"{path.as_posix()} did not contain a JSON object"]
    return payload, []


def _validate_report_payload(path: Path, payload: Mapping[str, Any]) -> list[str]:
    try:
        AlphaShadowDaemonReport.model_validate(payload)
    except ValueError as exc:
        return [f"{path.as_posix()} is not a valid alpha-shadow-daemon report: {exc}"]
    return []


def _evidence_from_payload(
    source_path: Path,
    payload: Mapping[str, Any],
) -> AlphaShadowDaemonReportEvidence:
    cycles = payload.get("cycles", [])
    cycle_mappings = [cycle for cycle in cycles if isinstance(cycle, Mapping)]
    cycle_count = _int_value(payload.get("cycle_count"), len(cycle_mappings))
    stale_cycle_count = sum(
        1 for cycle in cycle_mappings if _bool_value(cycle.get("stale_data_detected"))
    )
    campaign_id = _optional_str(payload.get("campaign_id"))
    heartbeat_path = _optional_str(payload.get("heartbeat_path"))
    heartbeat_present, heartbeat_campaign_id = _heartbeat_context(heartbeat_path)
    heartbeat_matches = (
        None
        if not heartbeat_present or campaign_id is None or heartbeat_campaign_id is None
        else heartbeat_campaign_id == campaign_id
    )
    return AlphaShadowDaemonReportEvidence(
        source_report_path=source_path.as_posix(),
        campaign_id=campaign_id,
        commit_sha=_optional_str(payload.get("commit_sha")),
        timestamp=_parse_timestamp(payload.get("timestamp")),
        final_status=_optional_str(payload.get("final_status")) or "unknown",
        ok=_bool_value(payload.get("ok")),
        cycle_count=cycle_count,
        clean_cycle_count=_int_value(payload.get("clean_cycle_count"), 0),
        market_data_policy=_optional_str(payload.get("market_data_policy"))
        or "strict_live",
        delayed_data_mode=_bool_value(payload.get("delayed_data_mode")),
        graduation_eligible=_bool_value(payload.get("graduation_eligible"), True),
        non_graduating_reason=_optional_str(payload.get("non_graduating_reason")),
        stale_data_detected=_bool_value(payload.get("stale_data_detected"))
        or stale_cycle_count > 0,
        stale_cycle_count=stale_cycle_count,
        broker_connected_cycles=_int_value(payload.get("broker_connected_cycles"), 0),
        account_summary_verified_cycles=_int_value(
            payload.get("account_summary_verified_cycles"),
            0,
        ),
        heartbeat_path=heartbeat_path,
        heartbeat_present=heartbeat_present,
        heartbeat_campaign_id=heartbeat_campaign_id,
        heartbeat_campaign_matches=heartbeat_matches,
        submitted_orders=_bool_value(payload.get("submitted_orders")),
        paper_orders_enabled=_bool_value(payload.get("paper_orders_enabled")),
        live_orders_enabled=_bool_value(payload.get("live_orders_enabled")),
        order_routing_enabled=_bool_value(payload.get("order_routing_enabled")),
        order_api_invoked=_bool_value(payload.get("order_api_invoked")),
        broker_contact_read_only=_bool_value(payload.get("broker_contact_read_only"), True),
        warnings=_string_list(payload.get("warnings")),
        errors=_string_list(payload.get("errors")),
    )


def _source_report_errors(
    report: AlphaShadowDaemonReportEvidence,
    *,
    current_commit: str | None,
    now: datetime,
    request: AlphaShadowDaemonSummaryRequest,
) -> list[str]:
    errors: list[str] = []
    label = report.source_report_path
    if not report.ok:
        errors.append(f"{label} did not pass")
    if report.final_status in {"failed", "halted"}:
        errors.append(f"{label} final_status is {report.final_status}")
    if report.cycle_count <= 0:
        errors.append(f"{label} recorded no daemon cycles")
    if report.stale_data_detected or report.stale_cycle_count > 0:
        errors.append(f"{label} detected stale source data")
    if report.broker_connected_cycles < report.cycle_count:
        errors.append(f"{label} lacks broker connection evidence for every cycle")
    if report.account_summary_verified_cycles < report.cycle_count:
        errors.append(f"{label} lacks account-summary evidence for every cycle")
    if not report.heartbeat_present:
        errors.append(f"{label} missing heartbeat evidence")
    if _safety_violation(report):
        errors.append(f"{label} contains an order-routing or execution safety flag")
    if not report.broker_contact_read_only:
        errors.append(f"{label} does not prove read-only broker contact")
    if not report.graduation_eligible or report.delayed_data_mode:
        reason = report.non_graduating_reason or report.market_data_policy
        errors.append(f"{label} is non-graduating shadow evidence: {reason}")
    if report.errors:
        errors.extend(f"{label} source error: {error}" for error in report.errors)
    errors.extend(
        _fresh_commit_errors(
            report,
            current_commit=current_commit,
            now=now,
            request=request,
        )
    )
    return errors


def _fresh_commit_errors(
    report: AlphaShadowDaemonReportEvidence,
    *,
    current_commit: str | None,
    now: datetime,
    request: AlphaShadowDaemonSummaryRequest,
) -> list[str]:
    errors: list[str] = []
    label = report.source_report_path
    if request.require_same_commit:
        if not report.commit_sha:
            errors.append(f"{label} lacks commit_sha; rerun the daemon")
        elif current_commit is None:
            errors.append("current git commit could not be determined")
        elif report.commit_sha != current_commit:
            errors.append(f"{label} was generated from a different commit")
    if report.timestamp is None:
        errors.append(f"{label} lacks a valid timestamp")
    elif now - report.timestamp > timedelta(hours=request.max_report_age_hours):
        errors.append(f"{label} is older than {request.max_report_age_hours} hours")
    return errors


def _heartbeat_context(heartbeat_path: str | None) -> tuple[bool, str | None]:
    if heartbeat_path is None:
        return False, None
    path = Path(heartbeat_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return False, None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return True, None
    if not isinstance(payload, Mapping):
        return True, None
    return True, _optional_str(payload.get("campaign_id"))


def _heartbeat_warning(report: AlphaShadowDaemonReportEvidence) -> str | None:
    if report.heartbeat_campaign_matches is False:
        return (
            f"{report.source_report_path} heartbeat campaign_id differs from source report; "
            "old sessions may share the mutable latest heartbeat path"
        )
    return None


def _clean_session(report: AlphaShadowDaemonReportEvidence) -> bool:
    return (
        report.ok
        and report.cycle_count > 0
        and report.clean_cycle_count >= report.cycle_count
        and not report.stale_data_detected
        and report.broker_connected_cycles >= report.cycle_count
        and report.account_summary_verified_cycles >= report.cycle_count
        and report.heartbeat_present
        and report.graduation_eligible
        and not report.delayed_data_mode
        and not _safety_violation(report)
        and not report.errors
    )


def _safety_violation(report: AlphaShadowDaemonReportEvidence) -> bool:
    return (
        report.submitted_orders
        or report.paper_orders_enabled
        or report.live_orders_enabled
        or report.order_routing_enabled
        or report.order_api_invoked
    )


def _next_eligibility_reasons(
    *,
    errors: list[str],
    clean_session_count: int,
    min_clean_sessions: int,
) -> list[str]:
    if errors:
        return ["daemon summary blockers must be resolved"]
    if clean_session_count < min_clean_sessions:
        remaining = min_clean_sessions - clean_session_count
        return [f"{remaining} more clean daemon session(s) required"]
    return ["graduation_ready_for_spy_paper_daemon_design"]


def _final_status(
    *,
    errors: list[str],
    warnings: list[str],
    graduation_ready: bool,
) -> AlphaShadowDaemonSummaryStatus:
    if errors:
        return AlphaShadowDaemonSummaryStatus.FAILED
    if warnings or not graduation_ready:
        return AlphaShadowDaemonSummaryStatus.COMPLETED_WITH_WARNINGS
    return AlphaShadowDaemonSummaryStatus.COMPLETED


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=utc_now().tzinfo)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=utc_now().tzinfo)


def _int_value(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _bool_value(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_optional_str(item) for item in value) if item is not None]


def _fingerprints(values: list[str]) -> list[str]:
    return _unique([" ".join(value.split()) for value in values if value.strip()])


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
