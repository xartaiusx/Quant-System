"""Authoritative offline validation for Alpaca acquisition rights evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from trader.data.research_bakeoff import (
    load_research_data_bakeoff_manifest,
    run_research_data_bakeoff,
)
from trader.data.research_vendor_decision import run_research_vendor_decision
from trader.models import (
    ResearchDataBakeoffReport,
    ResearchVendorDecisionManifest,
    ResearchVendorDecisionReport,
)


class AlpacaRightsGateError(ValueError):
    """Written rights evidence does not authorize Alpaca acquisition."""


@dataclass(frozen=True)
class PassingAlpacaRightsEvidence:
    report_path: Path
    report_sha256: str
    selected_vendor: str
    report_timestamp: str


def load_passing_alpaca_rights_decision(
    report_path: Path,
) -> PassingAlpacaRightsEvidence:
    """Apply the catalog's Pydantic contract and exact Alpaca hard gates."""

    resolved = report_path.expanduser().resolve()
    try:
        raw = resolved.read_bytes()
        report = ResearchVendorDecisionReport.model_validate_json(raw)
        _validate_authoritative_provenance(report, report_path=resolved)
    except (OSError, ValueError) as exc:
        raise AlpacaRightsGateError(
            "Alpaca vendor-decision report failed authoritative validation"
        ) from exc
    selected = next(
        (
            item
            for item in report.candidate_results
            if item.selected and item.vendor.strip().lower() == "alpaca_sip"
        ),
        None,
    )
    if (
        not report.ok
        or report.procurement_blocked
        or report.errors
        or report.final_status != "selected"
        or (report.selected_vendor or "").strip().lower() != "alpaca_sip"
        or selected is None
        or not selected.rights_gate_passed
        or not selected.bakeoff_gate_passed
        or not selected.budget_gate_passed
        or not selected.eligible
    ):
        raise AlpacaRightsGateError(
            "Alpaca acquisition remains blocked by rights, bake-off, or budget gates"
        )
    return PassingAlpacaRightsEvidence(
        report_path=resolved,
        report_sha256=hashlib.sha256(raw).hexdigest(),
        selected_vendor="alpaca_sip",
        report_timestamp=report.timestamp.isoformat(),
    )


def _validate_authoritative_provenance(
    report: ResearchVendorDecisionReport,
    *,
    report_path: Path,
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
            if item.vendor.strip().lower() == "alpaca_sip"
        ),
        None,
    )
    result = next(
        (
            item
            for item in report.candidate_results
            if item.selected and item.vendor.strip().lower() == "alpaca_sip"
        ),
        None,
    )
    if candidate is None or result is None:
        raise ValueError("selected Alpaca evidence is missing")
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
            if item.vendor.strip().lower() == "alpaca_sip"
        ),
        None,
    )
    if rights is None or not rights.passed:
        raise ValueError("passing Alpaca written-rights evidence is missing")
    evidence_hash = _normalize_sha256_reference(rights.evidence_reference)
    if evidence_hash not in candidate.written_evidence_sha256:
        raise ValueError("bake-off rights reference does not match written evidence")


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


__all__ = [
    "AlpacaRightsGateError",
    "PassingAlpacaRightsEvidence",
    "load_passing_alpaca_rights_decision",
]
