from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from trader.cli import app
from trader.data.research_vendor_decision import run_research_vendor_decision
from trader.models import ResearchVendorDecisionManifest
from trader.reporting.reports import markdown_summary

_WEIGHTS = {
    "rights_and_permitted_use": 20,
    "data_quality": 20,
    "coverage": 10,
    "corporate_actions": 10,
    "corrections": 10,
    "timestamp_sessions": 10,
    "delivery_operations": 10,
    "total_cost_storage": 10,
}


def test_vendor_decision_selects_highest_eligible_candidate(tmp_path: Path) -> None:
    alpha = _write_bakeoff(tmp_path / "alpha.json", "Alpha", rights=True)
    beta = _write_bakeoff(tmp_path / "beta.json", "Beta", rights=True)
    manifest = _write_manifest(
        tmp_path / "decision.json",
        [
            _candidate("Alpha", alpha.name, score=80, monthly_cost=300),
            _candidate("Beta", beta.name, score=90, monthly_cost=500),
        ],
    )

    report = run_research_vendor_decision(manifest)

    assert report.ok is True
    assert report.selected_vendor == "Beta"
    assert report.procurement_blocked is False
    assert [item.vendor for item in report.candidate_results if item.selected] == ["Beta"]
    assert report.candidate_results[1].three_year_tco_usd == 18000
    assert report.broker_contacted is False
    assert report.credentials_read is False
    assert report.network_accessed is False


def test_rights_failure_overrides_perfect_score(tmp_path: Path) -> None:
    rejected = _write_bakeoff(tmp_path / "massive.json", "Massive", rights=False)
    manifest = _write_manifest(
        tmp_path / "decision.json",
        [_candidate("Massive", rejected.name, score=100, monthly_cost=100)],
    )

    report = run_research_vendor_decision(manifest)

    assert report.ok is False
    assert report.selected_vendor is None
    assert report.procurement_blocked is True
    assert report.candidate_results[0].weighted_score == 100
    assert report.candidate_results[0].rights_gate_passed is False
    assert "written rights gate failed" in report.candidate_results[0].reasons


def test_free_alpaca_candidate_cannot_bypass_written_rights_gate(tmp_path: Path) -> None:
    bakeoff = _write_bakeoff(tmp_path / "alpaca.json", "alpaca_sip", rights=False)
    manifest = _write_manifest(
        tmp_path / "decision.json",
        [_candidate("alpaca_sip", bakeoff.name, score=100, monthly_cost=0)],
    )

    report = run_research_vendor_decision(manifest)

    assert report.ok is False
    assert report.selected_vendor is None
    assert report.procurement_blocked is True
    assert report.candidate_results[0].budget_gate_passed is True
    assert report.candidate_results[0].rights_gate_passed is False


def test_vendor_decision_reports_render_and_command_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected = _write_bakeoff(tmp_path / "vendor.json", "Vendor", rights=True)
    manifest = _write_manifest(
        tmp_path / "decision.json",
        [_candidate("Vendor", selected.name, score=80, monthly_cost=200)],
    )
    report = run_research_vendor_decision(manifest)

    markdown = markdown_summary(report.model_dump(mode="json"))
    assert "Research Data Vendor Decision" in markdown
    assert "Selected vendor: `Vendor`" in markdown
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["research-vendor-decision", "--manifest", manifest.as_posix()],
    )
    assert result.exit_code == 0
    assert "Selected vendor: Vendor" in result.output


def test_vendor_decision_module_is_offline_and_order_free() -> None:
    source = Path("src/trader/data/research_vendor_decision.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "import ibapi",
        "from ibapi",
        "httpx",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
    ):
        assert forbidden not in source


def test_vendor_decision_cannot_weaken_budget_or_weights() -> None:
    payload = {
        "max_monthly_budget_usd": 701,
        "score_weights": _WEIGHTS,
        "candidates": [_candidate("Vendor", "report.json", score=80, monthly_cost=200)],
    }
    with pytest.raises(ValidationError, match="less than or equal to 700"):
        ResearchVendorDecisionManifest.model_validate(payload)

    payload["max_monthly_budget_usd"] = 700
    payload["score_weights"] = {**_WEIGHTS, "coverage": 9, "corporate_actions": 11}
    with pytest.raises(ValidationError, match="approved policy"):
        ResearchVendorDecisionManifest.model_validate(payload)


def test_vendor_decision_fails_closed_on_invalid_or_missing_evidence(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    invalid_report = run_research_vendor_decision(invalid)
    assert invalid_report.ok is False
    assert "could not be loaded" in invalid_report.errors[0]

    manifest = _write_manifest(
        tmp_path / "missing.json",
        [_candidate("Missing", "missing-bakeoff.json", score=100, monthly_cost=10)],
    )
    missing_report = run_research_vendor_decision(manifest)
    assert missing_report.ok is False
    assert missing_report.selected_vendor is None
    assert "could not be loaded" in " ".join(missing_report.errors)


def _candidate(
    vendor: str,
    report_path: str,
    *,
    score: int,
    monthly_cost: int,
) -> dict[str, object]:
    return {
        "vendor": vendor,
        "bakeoff_report_path": report_path,
        "monthly_cost_usd": monthly_cost,
        "estimated_storage_gb": 25,
        "written_evidence_sha256": ["sha256:" + "a" * 64],
        "technical_scores": {key: score for key in _WEIGHTS},
    }


def _write_manifest(path: Path, candidates: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "max_monthly_budget_usd": 700,
                "evaluation_years": 3,
                "score_weights": _WEIGHTS,
                "candidates": candidates,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_bakeoff(path: Path, vendor: str, *, rights: bool) -> Path:
    rights_payload = {
        "vendor": vendor,
        "evidence_reference": "sha256:" + "b" * 64,
        "internal_storage_allowed": rights,
        "cloud_backup_allowed": rights,
        "automated_research_allowed": rights,
        "model_training_allowed": rights,
        "derived_data_allowed": rights,
        "correction_replay_available": rights,
        "paper_trading_use_allowed": rights,
        "live_trading_use_allowed": rights,
        "retention_after_termination_allowed": rights,
        "derived_retention_after_termination_allowed": rights,
    }
    payload = {
        "ok": rights,
        "manifest_path": "fixtures/bakeoff.json",
        "manifest": {
            "manifest_version": 1,
            "symbol": "SPY",
            "samples": [
                {
                    "sample_id": f"{vendor.lower()}-minute",
                    "vendor": vendor,
                    "path": "local.csv",
                    "kind": "minute_bars",
                    "source_format": "canonical_ohlcv",
                }
            ],
            "rights": [rights_payload],
        },
        "rights_verified_vendors": [vendor] if rights else [],
        "rights_failed_vendors": [] if rights else [vendor],
        "procurement_ready_vendors": [vendor] if rights else [],
        "errors": [] if rights else ["vendor rights evidence failed"],
        "final_status": "completed" if rights else "failed",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
