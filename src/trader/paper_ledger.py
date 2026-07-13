"""Offline ignored local ledger for completed IBKR paper campaigns."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from trader.models import (
    AlphaTestSummaryReport,
    PaperLedgerEntry,
    PaperLedgerUpdateReport,
    PaperLedgerUpdateRequest,
    PaperLedgerUpdateStatus,
    PaperReconcileReport,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def run_paper_ledger_update(
    request: PaperLedgerUpdateRequest | None = None,
) -> PaperLedgerUpdateReport:
    """Upsert one masked campaign row into an ignored local JSONL ledger."""

    ledger_request = request or PaperLedgerUpdateRequest()
    current_commit = _current_commit_sha()
    source_paths = {
        "alpha_test_summary_report": ledger_request.alpha_test_summary_report_path,
        "paper_reconcile_report": ledger_request.paper_reconcile_report_path,
    }
    warnings = [
        "paper-ledger-update is offline-only and does not contact IBKR.",
        "Ledger rows are ignored local artifacts and must not be committed.",
    ]
    errors: list[str] = []

    summary_report, summary_errors = _load_report(
        Path(ledger_request.alpha_test_summary_report_path),
        AlphaTestSummaryReport,
        label="alpha-test-summary report",
    )
    reconcile_report, reconcile_errors = _load_report(
        Path(ledger_request.paper_reconcile_report_path),
        PaperReconcileReport,
        label="paper-reconcile report",
    )
    errors.extend(summary_errors)
    errors.extend(reconcile_errors)

    campaign_id, campaign_errors = _campaign_context(
        ledger_request.campaign_id,
        summary_report=summary_report,
        reconcile_report=reconcile_report,
    )
    errors.extend(campaign_errors)

    if summary_report is not None:
        errors.extend(
            _summary_errors(
                summary_report,
                current_commit=current_commit,
            )
        )
    if reconcile_report is not None:
        errors.extend(
            _reconcile_errors(
                reconcile_report,
                current_commit=current_commit,
            )
        )
    if summary_report is not None and reconcile_report is not None:
        errors.extend(
            _cross_report_errors(
                summary_report=summary_report,
                reconcile_report=reconcile_report,
            )
        )

    ledger_path = Path(ledger_request.ledger_path)
    ledger_entry: PaperLedgerEntry | None = None
    ledger_entry_written = False
    ledger_record_count = 0
    replaced_existing_entry = False

    if not errors and summary_report is not None and reconcile_report is not None:
        ledger_entry = _ledger_entry_from_reports(
            campaign_id=campaign_id,
            current_commit=current_commit,
            request=ledger_request,
            summary_report=summary_report,
            reconcile_report=reconcile_report,
        )
        existing_entries, ledger_errors = _load_existing_ledger(ledger_path)
        errors.extend(ledger_errors)
        if not ledger_errors:
            updated_entries, replaced_existing_entry = _upsert_entry(
                existing_entries,
                ledger_entry,
            )
            try:
                _write_ledger(ledger_path, updated_entries)
            except OSError as exc:
                errors.append(f"paper ledger could not be written: {exc}")
            else:
                ledger_entry_written = True
                ledger_record_count = len(updated_entries)

    final_status = _final_status(errors=errors, warnings=warnings)
    return PaperLedgerUpdateReport(
        ok=final_status != PaperLedgerUpdateStatus.FAILED,
        request=ledger_request,
        commit_sha=current_commit,
        campaign_id=campaign_id,
        ledger_path=ledger_path.as_posix(),
        ledger_entry=ledger_entry,
        ledger_entry_written=ledger_entry_written,
        ledger_record_count=ledger_record_count,
        replaced_existing_entry=replaced_existing_entry,
        source_report_paths=source_paths,
        warnings=_unique(warnings),
        errors=_unique(errors),
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


def _campaign_context(
    request_campaign_id: str | None,
    *,
    summary_report: AlphaTestSummaryReport | None,
    reconcile_report: PaperReconcileReport | None,
) -> tuple[str | None, list[str]]:
    campaign_ids = {
        "alpha-test-summary report": summary_report.campaign_id
        if summary_report is not None
        else None,
        "paper-reconcile report": reconcile_report.campaign_id
        if reconcile_report is not None
        else None,
    }
    present_ids = {campaign_id for campaign_id in campaign_ids.values() if campaign_id}
    selected_campaign_id = request_campaign_id
    if selected_campaign_id is None and len(present_ids) == 1:
        selected_campaign_id = next(iter(present_ids))

    errors: list[str] = []
    if len(present_ids) > 1:
        errors.append("source reports have mismatched campaign_id values")
    if selected_campaign_id is None:
        errors.append("paper ledger campaign_id is required")
        return None, errors
    for label, campaign_id in campaign_ids.items():
        if campaign_id is None:
            errors.append(f"{label} lacks campaign_id")
        elif campaign_id != selected_campaign_id:
            errors.append(f"{label} campaign_id does not match {selected_campaign_id}")
    return selected_campaign_id, errors


def _summary_errors(
    report: AlphaTestSummaryReport,
    *,
    current_commit: str | None,
) -> list[str]:
    errors = _current_commit_errors(report.commit_sha, current_commit, "alpha-test-summary")
    if not report.ok:
        errors.append("alpha-test-summary report did not pass")
    if not report.paper_reconcile_verified:
        errors.append("alpha-test-summary did not verify paper-reconcile")
    if not report.account_summary_verified:
        errors.append("alpha-test-summary lacks verified account summary")
    if report.open_order_count != 0:
        errors.append("alpha-test-summary reports open broker orders")
    if not report.next_eligible_for_alpha_window:
        errors.append("alpha-test-summary is not next-window eligible")
    if report.order_routing_enabled or report.order_api_invoked:
        errors.append("alpha-test-summary unexpectedly invoked order routing")
    if report.live_orders_enabled or report.live_route_possible:
        errors.append("alpha-test-summary allowed live order risk")
    return errors


def _reconcile_errors(
    report: PaperReconcileReport,
    *,
    current_commit: str | None,
) -> list[str]:
    errors = _current_commit_errors(report.commit_sha, current_commit, "paper-reconcile")
    if not report.ok:
        errors.append("paper-reconcile report did not pass")
    if not report.account_summary_verified:
        errors.append("paper-reconcile lacks verified account summary")
    if report.open_order_count != 0:
        errors.append("paper-reconcile reports open broker orders")
    if not report.open_orders_query_completed:
        errors.append("paper-reconcile did not complete the broker open-orders query")
    if not report.executions_query_completed:
        errors.append("paper-reconcile did not complete the broker executions query")
    if not report.positions_query_completed:
        errors.append("paper-reconcile did not complete the broker positions query")
    expected_sources = {"paper_smoke_report", "alpha_paper_report"}
    missing_compatibility = sorted(
        expected_sources - set(report.source_report_compatibility)
    )
    if missing_compatibility:
        errors.append(
            "paper-reconcile lacks source compatibility evidence: "
            + ", ".join(missing_compatibility)
        )
    incompatible_sources = sorted(
        label
        for label, status in report.source_report_compatibility.items()
        if str(status) != "current"
    )
    if incompatible_sources:
        errors.append(
            "paper-reconcile contains non-current source evidence: "
            + ", ".join(incompatible_sources)
        )
    if not report.broker_state_fingerprint:
        errors.append("paper-reconcile lacks broker_state_fingerprint")
    if report.submitted_orders or report.order_api_invoked:
        errors.append("paper-reconcile unexpectedly invoked order routing")
    if report.paper_orders_enabled or report.order_routing_enabled:
        errors.append("paper-reconcile enabled order routing")
    if report.live_orders_enabled or report.live_route_possible:
        errors.append("paper-reconcile allowed live order risk")
    return errors


def _cross_report_errors(
    *,
    summary_report: AlphaTestSummaryReport,
    reconcile_report: PaperReconcileReport,
) -> list[str]:
    errors: list[str] = []
    if summary_report.account_ids_masked and reconcile_report.account_ids_masked:
        summary_accounts = set(summary_report.account_ids_masked)
        reconcile_accounts = set(reconcile_report.account_ids_masked)
        if summary_accounts.isdisjoint(reconcile_accounts):
            errors.append("summary and reconciliation masked account IDs do not overlap")

    broker_order_ids = set(reconcile_report.latest_order_ids)
    broker_order_ids.update(reconcile_report.execution_order_ids)
    broker_order_ids.update(
        order.order_id for order in reconcile_report.open_orders if order.order_id is not None
    )
    missing_order_ids = [
        order_id
        for order_id in summary_report.latest_order_ids
        if order_id not in broker_order_ids
    ]
    if missing_order_ids:
        errors.append(
            "summary order IDs missing from broker-state evidence: "
            + ", ".join(str(order_id) for order_id in missing_order_ids)
        )

    broker_perm_ids = set(reconcile_report.latest_perm_ids)
    broker_perm_ids.update(
        order.perm_id for order in reconcile_report.open_orders if order.perm_id is not None
    )
    missing_perm_ids = [
        perm_id for perm_id in summary_report.latest_perm_ids if perm_id not in broker_perm_ids
    ]
    if missing_perm_ids:
        errors.append(
            "summary perm IDs missing from broker-state evidence: "
            + ", ".join(str(perm_id) for perm_id in missing_perm_ids)
        )
    return errors


def _ledger_entry_from_reports(
    *,
    campaign_id: str | None,
    current_commit: str | None,
    request: PaperLedgerUpdateRequest,
    summary_report: AlphaTestSummaryReport,
    reconcile_report: PaperReconcileReport,
) -> PaperLedgerEntry:
    if campaign_id is None:
        raise ValueError("paper ledger campaign_id is required")
    return PaperLedgerEntry(
        campaign_id=campaign_id,
        commit_sha=current_commit,
        source_report_paths={
            "alpha_test_summary_report": request.alpha_test_summary_report_path,
            "paper_reconcile_report": request.paper_reconcile_report_path,
            **summary_report.source_report_paths,
        },
        account_ids_masked=_unique(
            [
                *summary_report.account_ids_masked,
                *reconcile_report.account_ids_masked,
            ]
        ),
        account_summary_verified=summary_report.account_summary_verified
        and reconcile_report.account_summary_verified,
        open_order_count=reconcile_report.open_order_count,
        zero_positions_confirmed=reconcile_report.zero_positions_confirmed,
        positions_query_completed=reconcile_report.positions_query_completed,
        latest_order_ids=sorted(
            set([*summary_report.latest_order_ids, *reconcile_report.latest_order_ids])
        ),
        latest_perm_ids=sorted(
            set([*summary_report.latest_perm_ids, *reconcile_report.latest_perm_ids])
        ),
        paper_smoke_order_status=summary_report.paper_smoke_order_status,
        paper_smoke_fill_quantity=summary_report.paper_smoke_fill_quantity,
        paper_smoke_canceled=summary_report.paper_smoke_canceled,
        alpha_paper_order_status=summary_report.alpha_paper_order_status,
        alpha_paper_fill_quantity=summary_report.alpha_paper_fill_quantity,
        alpha_paper_canceled=summary_report.alpha_paper_canceled,
        broker_state_fingerprint=reconcile_report.broker_state_fingerprint,
        next_eligible_for_alpha_window=summary_report.next_eligible_for_alpha_window,
        next_eligibility_reason=summary_report.next_eligibility_reason,
    )


def _load_existing_ledger(path: Path) -> tuple[list[PaperLedgerEntry], list[str]]:
    if not path.exists():
        return [], []
    entries: list[PaperLedgerEntry] = []
    errors: list[str] = []
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        return [], [f"paper ledger could not be read: {exc}"]

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"paper ledger line {line_number} is invalid JSON: {exc}")
            continue
        if not isinstance(payload, Mapping):
            errors.append(f"paper ledger line {line_number} is not a JSON object")
            continue
        try:
            entries.append(PaperLedgerEntry.model_validate(payload))
        except ValueError as exc:
            errors.append(f"paper ledger line {line_number} is invalid: {exc}")
    return entries, errors


def _upsert_entry(
    entries: list[PaperLedgerEntry],
    entry: PaperLedgerEntry,
) -> tuple[list[PaperLedgerEntry], bool]:
    replaced = False
    updated_entries: list[PaperLedgerEntry] = []
    for existing_entry in entries:
        if existing_entry.campaign_id == entry.campaign_id:
            if not replaced:
                updated_entries.append(entry)
                replaced = True
            continue
        updated_entries.append(existing_entry)
    if not replaced:
        updated_entries.append(entry)
    return updated_entries, replaced


def _write_ledger(path: Path, entries: list[PaperLedgerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(entry.model_dump_json() for entry in entries)
    path.write_text(payload + ("\n" if payload else ""))


def _current_commit_errors(
    report_commit: str | None,
    current_commit: str | None,
    label: str,
) -> list[str]:
    if not report_commit:
        return [f"{label} report lacks commit_sha; rerun the source command"]
    if current_commit is None:
        return ["current git commit could not be determined"]
    if report_commit != current_commit:
        return [f"{label} report was generated from a different commit"]
    return []


def _final_status(
    *,
    errors: list[str],
    warnings: list[str],
) -> PaperLedgerUpdateStatus:
    if errors:
        return PaperLedgerUpdateStatus.FAILED
    if warnings:
        return PaperLedgerUpdateStatus.COMPLETED_WITH_WARNINGS
    return PaperLedgerUpdateStatus.COMPLETED


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
