"""Offline rights-first SPY research-data vendor selection."""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from trader.models import (
    ResearchDataBakeoffReport,
    ResearchVendorDecisionCandidate,
    ResearchVendorDecisionManifest,
    ResearchVendorDecisionReport,
    ResearchVendorDecisionResult,
)

_SCORE_QUANTUM = Decimal("0.01")


def run_research_vendor_decision(manifest_path: Path) -> ResearchVendorDecisionReport:
    """Select at most one vendor; licensing failure always overrides score."""

    resolved = manifest_path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        manifest = ResearchVendorDecisionManifest.model_validate(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ResearchVendorDecisionReport(
            ok=False,
            manifest_path=resolved.as_posix(),
            errors=[f"vendor decision manifest could not be loaded: {exc}"],
            final_status="failed",
        )

    results: list[ResearchVendorDecisionResult] = []
    errors: list[str] = []
    for candidate in manifest.candidates:
        result, candidate_errors = _evaluate_candidate(
            candidate,
            manifest=manifest,
            base_path=resolved.parent,
        )
        results.append(result)
        errors.extend(candidate_errors)

    eligible = [result for result in results if result.eligible]
    selected_vendor: str | None = None
    if eligible:
        winner = max(
            eligible,
            key=lambda result: (result.weighted_score, -result.three_year_tco_usd),
        )
        selected_vendor = winner.vendor
        results = [
            result.model_copy(update={"selected": result.vendor == selected_vendor})
            for result in results
        ]
    else:
        errors.append("no vendor passed rights, bake-off, and budget hard gates")

    errors = list(dict.fromkeys(errors))
    return ResearchVendorDecisionReport(
        ok=selected_vendor is not None and not errors,
        manifest_path=resolved.as_posix(),
        manifest=manifest,
        candidate_results=results,
        selected_vendor=selected_vendor,
        procurement_blocked=selected_vendor is None,
        warnings=[
            "Contracts and RFI responses remain outside Git; only SHA-256 evidence is recorded"
        ],
        errors=errors,
        final_status="selected" if selected_vendor is not None and not errors else "blocked",
    )


def _evaluate_candidate(
    candidate: ResearchVendorDecisionCandidate,
    *,
    manifest: ResearchVendorDecisionManifest,
    base_path: Path,
) -> tuple[ResearchVendorDecisionResult, list[str]]:
    report_path = Path(candidate.bakeoff_report_path).expanduser()
    if not report_path.is_absolute():
        report_path = base_path / report_path
    report_path = report_path.resolve()
    report: ResearchDataBakeoffReport | None = None
    load_error: str | None = None
    try:
        report = ResearchDataBakeoffReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        load_error = f"{candidate.vendor}: bake-off report could not be loaded: {exc}"

    rights_gate = False
    bakeoff_gate = False
    classifications: list[str] = []
    reasons: list[str] = []
    if report is not None and report.manifest is not None:
        rights = next(
            (
                item
                for item in report.manifest.rights
                if item.vendor.strip().lower() == candidate.vendor.strip().lower()
            ),
            None,
        )
        rights_gate = bool(rights and rights.passed)
        bakeoff_gate = bool(
            report.ok
            and candidate.vendor.lower()
            in {vendor.lower() for vendor in report.procurement_ready_vendors}
        )
        classifications = _discrepancy_classifications(report, candidate.vendor)
    if load_error:
        reasons.append(load_error)
    if not rights_gate:
        reasons.append("written rights gate failed")
    if not bakeoff_gate:
        reasons.append("technical bake-off gate failed")

    budget_gate = candidate.monthly_cost_usd <= manifest.max_monthly_budget_usd
    if not budget_gate:
        reasons.append(
            f"monthly cost exceeds ${manifest.max_monthly_budget_usd} budget"
        )
    weighted_score = sum(
        candidate.technical_scores[key] * Decimal(weight)
        for key, weight in manifest.score_weights.items()
    ) / Decimal("100")
    tco = (
        candidate.monthly_cost_usd
        * Decimal("12")
        * Decimal(manifest.evaluation_years)
        + candidate.one_time_cost_usd
    )
    eligible = rights_gate and bakeoff_gate and budget_gate and load_error is None
    result = ResearchVendorDecisionResult(
        vendor=candidate.vendor,
        weighted_score=weighted_score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
        three_year_tco_usd=tco.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
        estimated_storage_gb=candidate.estimated_storage_gb,
        written_evidence_sha256=candidate.written_evidence_sha256,
        rights_gate_passed=rights_gate,
        bakeoff_gate_passed=bakeoff_gate,
        budget_gate_passed=budget_gate,
        eligible=eligible,
        discrepancy_classifications=classifications,
        reasons=list(dict.fromkeys(reasons)),
    )
    return result, [load_error] if load_error else []


def _discrepancy_classifications(
    report: ResearchDataBakeoffReport,
    vendor: str,
) -> list[str]:
    sample_ids = {
        result.sample_id
        for result in report.sample_results
        if result.vendor.strip().lower() == vendor.strip().lower()
    }
    classifications: list[str] = []
    for comparison in report.comparisons:
        if not sample_ids.intersection(
            {comparison.left_sample_id, comparison.right_sample_id}
        ):
            continue
        classification = "within_tolerance" if comparison.ok else "material"
        classifications.append(f"{comparison.comparison_type}:{classification}")
    return list(dict.fromkeys(classifications))


__all__ = ["run_research_vendor_decision"]
