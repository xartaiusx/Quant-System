"""Authoritative offline validation for supported vendor-rights evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from trader.data.research_bakeoff import (
    load_research_data_bakeoff_manifest,
    run_research_data_bakeoff,
)
from trader.data.research_vendor_decision import run_research_vendor_decision
from trader.models import (
    ResearchDataBakeoffReport,
    ResearchSampleKind,
    ResearchVendorDecisionManifest,
    ResearchVendorDecisionReport,
)


class VendorRightsGateError(ValueError):
    """Written-rights evidence does not authorize the expected vendor."""


class AlpacaRightsGateError(VendorRightsGateError):
    """Written rights evidence does not authorize Alpaca acquisition."""


@dataclass(frozen=True)
class PassingVendorRightsEvidence:
    report_path: Path
    report_sha256: str
    selected_vendor: str
    report_timestamp: str


@dataclass(frozen=True)
class PassingAlpacaRightsEvidence:
    report_path: Path
    report_sha256: str
    selected_vendor: str
    report_timestamp: str


def load_passing_alpaca_rights_decision(
    report_path: Path,
) -> PassingAlpacaRightsEvidence:
    """Compatibility wrapper for the exact Alpaca hard gates."""

    try:
        evidence = load_passing_vendor_rights_decision(
            report_path,
            expected_vendor="alpaca_sip",
            required_data_kind=ResearchSampleKind.MINUTE_BARS,
        )
    except VendorRightsGateError as exc:
        raise AlpacaRightsGateError(str(exc)) from exc
    return PassingAlpacaRightsEvidence(
        report_path=evidence.report_path,
        report_sha256=evidence.report_sha256,
        selected_vendor=evidence.selected_vendor,
        report_timestamp=evidence.report_timestamp,
    )


def load_passing_vendor_rights_decision(
    report_path: Path,
    *,
    expected_vendor: str,
    required_data_kind: ResearchSampleKind | str,
) -> PassingVendorRightsEvidence:
    """Recompute the full decision chain and apply the expected vendor gates."""

    vendor = _normalize_expected_vendor(expected_vendor)
    data_kind = _normalize_data_kind(required_data_kind)
    resolved = report_path.expanduser().resolve()
    try:
        raw = resolved.read_bytes()
        report = ResearchVendorDecisionReport.model_validate_json(raw)
        _validate_authoritative_provenance(
            report,
            report_path=resolved,
            expected_vendor=vendor,
            required_data_kind=data_kind,
        )
    except (OSError, ValueError) as exc:
        raise VendorRightsGateError(
            f"{vendor} vendor-decision report failed authoritative validation"
        ) from exc
    selected = next(
        (
            item
            for item in report.candidate_results
            if item.selected and item.vendor.strip().lower() == vendor
        ),
        None,
    )
    if (
        not report.ok
        or report.procurement_blocked
        or report.errors
        or report.final_status != "selected"
        or (report.selected_vendor or "").strip().lower() != vendor
        or selected is None
        or not selected.rights_gate_passed
        or not selected.bakeoff_gate_passed
        or not selected.budget_gate_passed
        or not selected.eligible
    ):
        raise VendorRightsGateError(
            f"{vendor} use remains blocked by rights, bake-off, or budget gates"
        )
    return PassingVendorRightsEvidence(
        report_path=resolved,
        report_sha256=hashlib.sha256(raw).hexdigest(),
        selected_vendor=vendor,
        report_timestamp=report.timestamp.isoformat(),
    )


def _validate_authoritative_provenance(
    report: ResearchVendorDecisionReport,
    *,
    report_path: Path,
    expected_vendor: str,
    required_data_kind: str,
) -> None:
    """Rebuild the decision chain and bind its written-rights hashes."""

    if report.manifest is None:
        raise ValueError("vendor-decision report has no embedded manifest")
    manifest_path = _resolve_evidence_path(
        report.manifest_path,
        base_path=report_path.parent,
    )
    decision_manifest = ResearchVendorDecisionManifest.model_validate_json(
        manifest_path.read_bytes()
    )
    if decision_manifest != report.manifest:
        raise ValueError("vendor-decision manifest provenance mismatch")

    canonical_decision = run_research_vendor_decision(manifest_path).model_copy(
        update={"timestamp": report.timestamp}
    )
    if canonical_decision != report:
        raise ValueError("vendor-decision report does not match canonical recomputation")

    candidate = next(
        (
            item
            for item in decision_manifest.candidates
            if item.vendor.strip().lower() == expected_vendor
        ),
        None,
    )
    result = next(
        (
            item
            for item in report.candidate_results
            if item.selected and item.vendor.strip().lower() == expected_vendor
        ),
        None,
    )
    if candidate is None or result is None:
        raise ValueError(f"selected {expected_vendor} evidence is missing")
    if (
        not candidate.written_evidence_sha256
        or result.written_evidence_sha256 != candidate.written_evidence_sha256
    ):
        raise ValueError("written-rights evidence hashes are missing or mismatched")

    bakeoff_report_path = _resolve_evidence_path(
        candidate.bakeoff_report_path,
        base_path=manifest_path.parent,
    )
    bakeoff_report = ResearchDataBakeoffReport.model_validate_json(
        bakeoff_report_path.read_bytes()
    )
    if bakeoff_report.manifest is None:
        raise ValueError("bake-off report has no embedded manifest")
    bakeoff_manifest_path = _resolve_evidence_path(
        bakeoff_report.manifest_path,
        base_path=bakeoff_report_path.parent,
    )
    bakeoff_manifest = load_research_data_bakeoff_manifest(bakeoff_manifest_path)
    if bakeoff_manifest != bakeoff_report.manifest:
        raise ValueError("bake-off manifest provenance mismatch")
    canonical_bakeoff = run_research_data_bakeoff(bakeoff_manifest_path).model_copy(
        update={"timestamp": bakeoff_report.timestamp}
    )
    if canonical_bakeoff != bakeoff_report:
        raise ValueError("bake-off report does not match canonical recomputation")

    rights = next(
        (
            item
            for item in bakeoff_manifest.rights
            if item.vendor.strip().lower() == expected_vendor
        ),
        None,
    )
    if rights is None or not rights.passed:
        raise ValueError(f"passing {expected_vendor} written-rights evidence is missing")
    evidence_hash = _normalize_sha256_reference(rights.evidence_reference)
    if evidence_hash not in candidate.written_evidence_sha256:
        raise ValueError("bake-off rights reference does not match written evidence")
    _validate_required_bakeoff_scope(
        bakeoff_report,
        expected_vendor=expected_vendor,
        required_data_kind=required_data_kind,
    )


def _validate_required_bakeoff_scope(
    report: ResearchDataBakeoffReport,
    *,
    expected_vendor: str,
    required_data_kind: str,
) -> None:
    own_results = [
        item
        for item in report.sample_results
        if item.ok
        and item.vendor.strip().lower() == expected_vendor
        and str(item.kind) == required_data_kind
    ]
    if not own_results:
        raise ValueError(
            f"{expected_vendor} has no passing {required_data_kind} bake-off sample"
        )
    own_ids = {item.sample_id for item in own_results}
    result_vendors = {
        item.sample_id: item.vendor.strip().lower() for item in report.sample_results
    }
    observed_tags = {tag for item in own_results for tag in item.case_tags}

    if required_data_kind == ResearchSampleKind.DAILY_BARS.value:
        if "daily_overlap" not in observed_tags:
            raise ValueError(
                f"{expected_vendor} daily bake-off is missing its own daily_overlap case"
            )
        if not _passing_cross_vendor_comparison(
            report,
            comparison_type="daily_overlap",
            own_ids=own_ids,
            result_vendors=result_vendors,
            expected_vendor=expected_vendor,
        ):
            raise ValueError(
                f"{expected_vendor} daily bake-off lacks a passing cross-vendor "
                "daily overlap"
            )
        return

    if required_data_kind == ResearchSampleKind.CORPORATE_ACTIONS.value:
        missing_action_tags = sorted(
            {"ex_dividend", "synthetic_split"} - observed_tags
        )
        if missing_action_tags:
            raise ValueError(
                f"{expected_vendor} corporate-action bake-off is missing its own cases: "
                f"{', '.join(missing_action_tags)}"
            )
        return

    if required_data_kind != ResearchSampleKind.MINUTE_BARS.value:
        return

    required_tags = {
        "normal_session",
        "early_close",
        "dst_transition",
        "correction_before",
        "correction_after",
        "intraday_overlap",
    }
    missing_tags = sorted(required_tags - observed_tags)
    if missing_tags:
        raise ValueError(
            f"{expected_vendor} minute bake-off is missing its own cases: "
            f"{', '.join(missing_tags)}"
        )

    dst_results = [
        item
        for item in own_results
        if "dst_transition" in item.case_tags and item.first_timestamp is not None
    ]
    utc_open_signatures = {
        (
            item.first_timestamp.astimezone(UTC).hour,
            item.first_timestamp.astimezone(UTC).minute,
        )
        for item in dst_results
        if item.first_timestamp is not None
    }
    if len(dst_results) < 2 or len(utc_open_signatures) < 2:
        raise ValueError(
            f"{expected_vendor} minute bake-off needs pre/post-DST session evidence"
        )

    correction_passed = any(
        item.ok
        and item.comparison_type == "correction_revision"
        and item.left_sample_id in own_ids
        and item.right_sample_id in own_ids
        for item in report.comparisons
    )
    if not correction_passed:
        raise ValueError(
            f"{expected_vendor} minute bake-off lacks its own passing correction comparison"
        )

    overlap_passed = _passing_cross_vendor_comparison(
        report,
        comparison_type="intraday_overlap",
        own_ids=own_ids,
        result_vendors=result_vendors,
        expected_vendor=expected_vendor,
    )
    if not overlap_passed:
        raise ValueError(
            f"{expected_vendor} minute bake-off lacks a passing cross-vendor "
            "intraday overlap"
        )


def _passing_cross_vendor_comparison(
    report: ResearchDataBakeoffReport,
    *,
    comparison_type: str,
    own_ids: set[str],
    result_vendors: dict[str, str],
    expected_vendor: str,
) -> bool:
    return any(
        item.ok
        and item.comparison_type == comparison_type
        and (
            (
                item.left_sample_id in own_ids
                and result_vendors.get(item.right_sample_id) not in {None, expected_vendor}
            )
            or (
                item.right_sample_id in own_ids
                and result_vendors.get(item.left_sample_id) not in {None, expected_vendor}
            )
        )
        for item in report.comparisons
    )


def _resolve_evidence_path(value: str, *, base_path: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_path / path
    return path.resolve()


def _normalize_sha256_reference(value: str) -> str:
    candidate = value.strip().lower()
    digest = candidate.removeprefix("sha256:")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("written-rights reference must be a SHA-256")
    return f"sha256:{digest}"


def _normalize_expected_vendor(value: str) -> str:
    vendor = value.strip().lower()
    if vendor not in {
        "alpaca_sip",
        "massive",
        "algoseek",
        "databento",
        "norgate",
    }:
        raise VendorRightsGateError(f"unsupported vendor-rights gate: {vendor or 'empty'}")
    return vendor


def _normalize_data_kind(value: ResearchSampleKind | str) -> str:
    candidate = str(value).strip().lower()
    allowed = {item.value for item in ResearchSampleKind}
    if candidate not in allowed:
        raise VendorRightsGateError(
            f"unsupported vendor-rights data kind: {candidate or 'empty'}"
        )
    return candidate


__all__ = [
    "AlpacaRightsGateError",
    "PassingAlpacaRightsEvidence",
    "PassingVendorRightsEvidence",
    "VendorRightsGateError",
    "load_passing_alpaca_rights_decision",
    "load_passing_vendor_rights_decision",
]
