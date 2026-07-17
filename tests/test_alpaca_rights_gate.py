from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from trader.data.alpaca_rights_gate import (
    AlpacaRightsGateError,
    load_passing_alpaca_rights_decision,
)
from trader.data.research_bakeoff import run_research_data_bakeoff
from trader.data.research_vendor_decision import run_research_vendor_decision

_EVIDENCE_HASH = "sha256:" + "a" * 64
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


def _write_authoritative_decision(
    root: Path,
    *,
    evidence_reference: str = _EVIDENCE_HASH,
    written_evidence_sha256: str = _EVIDENCE_HASH,
) -> Path:
    sample_path = root / "alpaca-daily.csv"
    with sample_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("symbol", "timestamp", "open", "high", "low", "close", "volume"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "symbol": "SPY",
                "timestamp": "2025-01-02",
                "open": "500",
                "high": "501",
                "low": "499",
                "close": "500.5",
                "volume": "1000000",
            }
        )
    rights = {
        "vendor": "alpaca_sip",
        "evidence_reference": evidence_reference,
        "internal_storage_allowed": True,
        "cloud_backup_allowed": True,
        "automated_research_allowed": True,
        "model_training_allowed": True,
        "derived_data_allowed": True,
        "correction_replay_available": True,
        "paper_trading_use_allowed": True,
        "live_trading_use_allowed": True,
        "retention_after_termination_allowed": True,
        "derived_retention_after_termination_allowed": True,
    }
    bakeoff_manifest_path = root / "bakeoff-manifest.json"
    bakeoff_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "required_case_tags": ["normal_session"],
                "samples": [
                    {
                        "sample_id": "alpaca-daily",
                        "vendor": "alpaca_sip",
                        "path": sample_path.name,
                        "kind": "daily_bars",
                        "source_format": "canonical_ohlcv",
                        "case_tags": ["normal_session"],
                    }
                ],
                "rights": [rights],
            }
        ),
        encoding="utf-8",
    )
    bakeoff_report = run_research_data_bakeoff(bakeoff_manifest_path)
    assert bakeoff_report.ok is True
    bakeoff_report_path = root / "bakeoff-report.json"
    bakeoff_report_path.write_text(bakeoff_report.model_dump_json(), encoding="utf-8")

    decision_manifest_path = root / "decision-manifest.json"
    decision_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "score_weights": _WEIGHTS,
                "candidates": [
                    {
                        "vendor": "alpaca_sip",
                        "bakeoff_report_path": bakeoff_report_path.name,
                        "monthly_cost_usd": 100,
                        "estimated_storage_gb": 20,
                        "written_evidence_sha256": [written_evidence_sha256],
                        "technical_scores": {key: 100 for key in _WEIGHTS},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    decision_report = run_research_vendor_decision(decision_manifest_path)
    assert decision_report.ok is True
    decision_report_path = root / "decision-report.json"
    decision_report_path.write_text(decision_report.model_dump_json(), encoding="utf-8")
    return decision_report_path


def test_authoritative_rights_gate_returns_exact_report_hash(tmp_path: Path) -> None:
    path = _write_authoritative_decision(tmp_path)
    raw = path.read_bytes()

    evidence = load_passing_alpaca_rights_decision(path)

    assert evidence.selected_vendor == "alpaca_sip"
    assert evidence.report_sha256 == hashlib.sha256(raw).hexdigest()
    assert evidence.report_path == path.resolve()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"network_accessed": True}),
        lambda payload: payload.update({"final_status": "blocked"}),
        lambda payload: payload.pop("manifest"),
        lambda payload: payload["candidate_results"][0].update(
            {"rights_gate_passed": False}
        ),
        lambda payload: payload["candidate_results"][0].update(
            {"written_evidence_sha256": []}
        ),
    ],
)
def test_authoritative_rights_gate_rejects_lookalike_json(
    tmp_path: Path,
    mutation,
) -> None:
    path = _write_authoritative_decision(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


def test_rights_gate_requires_bakeoff_reference_to_match_decision_hash(
    tmp_path: Path,
) -> None:
    path = _write_authoritative_decision(
        tmp_path,
        evidence_reference="sha256:" + "b" * 64,
        written_evidence_sha256=_EVIDENCE_HASH,
    )

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


def test_rights_gate_rejects_changed_bakeoff_source_sample(tmp_path: Path) -> None:
    path = _write_authoritative_decision(tmp_path)
    sample_path = tmp_path / "alpaca-daily.csv"
    sample_path.write_text(sample_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


def test_rights_gate_has_no_network_broker_or_execution_dependency() -> None:
    for path in (
        Path("src/trader/data/alpaca_rights_gate.py"),
        Path("scripts/validate_alpaca_rights.py"),
    ):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("urllib", "requests", "trader.broker", "trader.execution"):
            assert forbidden not in source
