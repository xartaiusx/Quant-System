from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from trader.data.alpaca_rights_gate import (
    AlpacaRightsGateError,
    VendorRightsGateError,
    load_passing_alpaca_rights_decision,
    load_passing_vendor_rights_decision,
)
from trader.data.research_bakeoff import run_research_data_bakeoff
from trader.data.research_vendor_decision import run_research_vendor_decision
from vendor_rights_helpers import (
    EVIDENCE_HASH,
    write_authoritative_action_vendor_decision,
    write_authoritative_daily_vendor_decision,
    write_authoritative_vendor_decision,
)


def _write_authoritative_decision(
    root: Path,
    *,
    evidence_reference: str = EVIDENCE_HASH,
    written_evidence_sha256: str = EVIDENCE_HASH,
) -> Path:
    return write_authoritative_vendor_decision(
        root,
        vendor="alpaca_sip",
        evidence_reference=evidence_reference,
        written_evidence_sha256=written_evidence_sha256,
    )


def test_authoritative_rights_gate_returns_exact_report_hash(tmp_path: Path) -> None:
    path = _write_authoritative_decision(tmp_path)
    raw = path.read_bytes()

    evidence = load_passing_alpaca_rights_decision(path)

    assert evidence.selected_vendor == "alpaca_sip"
    assert evidence.report_sha256 == hashlib.sha256(raw).hexdigest()
    assert evidence.report_path == path.resolve()


def test_minute_gate_rejects_authoritative_daily_only_decision(tmp_path: Path) -> None:
    path = write_authoritative_daily_vendor_decision(
        tmp_path,
        vendor="alpaca_sip",
    )

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


@pytest.mark.parametrize(
    "vendor",
    ["alpaca_sip", "massive", "algoseek", "databento", "norgate"],
)
def test_generic_gate_supports_every_program_vendor(
    tmp_path: Path,
    vendor: str,
) -> None:
    path = write_authoritative_daily_vendor_decision(tmp_path, vendor=vendor)

    evidence = load_passing_vendor_rights_decision(
        path,
        expected_vendor=vendor,
        required_data_kind="daily_bars",
    )

    assert evidence.selected_vendor == vendor


def test_daily_gate_rejects_shrinkable_same_kind_evidence(tmp_path: Path) -> None:
    write_authoritative_daily_vendor_decision(tmp_path, vendor="norgate")
    manifest_path = tmp_path / "bakeoff-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"] = [manifest["samples"][0]]
    manifest["samples"][0]["case_tags"] = ["normal_session"]
    manifest["rights"] = [manifest["rights"][0]]
    manifest["required_case_tags"] = ["normal_session"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = _rebuild_reports(tmp_path)

    with pytest.raises(VendorRightsGateError):
        load_passing_vendor_rights_decision(
            path,
            expected_vendor="norgate",
            required_data_kind="daily_bars",
        )


def test_daily_gate_does_not_borrow_other_vendors_overlap(tmp_path: Path) -> None:
    write_authoritative_daily_vendor_decision(tmp_path, vendor="databento")
    manifest_path = tmp_path / "bakeoff-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["case_tags"] = ["normal_session"]
    manifest["samples"].append(
        {
            "sample_id": "second-reference-daily",
            "vendor": "second_reference_vendor",
            "path": "reference-daily.csv",
            "kind": "daily_bars",
            "source_format": "canonical_ohlcv",
            "case_tags": ["daily_overlap"],
        }
    )
    second_rights = dict(manifest["rights"][1])
    second_rights["vendor"] = "second_reference_vendor"
    second_rights["evidence_reference"] = "sha256:" + "d" * 64
    manifest["rights"].append(second_rights)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = _rebuild_reports(tmp_path)

    with pytest.raises(VendorRightsGateError):
        load_passing_vendor_rights_decision(
            path,
            expected_vendor="databento",
            required_data_kind="daily_bars",
        )


def test_action_gate_does_not_borrow_other_vendor_cases(tmp_path: Path) -> None:
    write_authoritative_action_vendor_decision(tmp_path, vendor="algoseek")
    manifest_path = tmp_path / "bakeoff-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["case_tags"] = ["normal_session"]
    manifest["samples"].append(
        {
            "sample_id": "reference-actions",
            "vendor": "reference_vendor",
            "path": "algoseek-actions.csv",
            "kind": "corporate_actions",
            "source_format": "canonical_actions",
            "case_tags": ["ex_dividend", "synthetic_split"],
        }
    )
    manifest["rights"].append(
        {
            **manifest["rights"][0],
            "vendor": "reference_vendor",
            "evidence_reference": "sha256:" + "c" * 64,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = _rebuild_reports(tmp_path)

    with pytest.raises(VendorRightsGateError):
        load_passing_vendor_rights_decision(
            path,
            expected_vendor="algoseek",
            required_data_kind="corporate_actions",
        )


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
        written_evidence_sha256=EVIDENCE_HASH,
    )

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


def test_generic_rights_gate_requires_exact_expected_vendor(tmp_path: Path) -> None:
    path = write_authoritative_vendor_decision(tmp_path, vendor="massive")

    evidence = load_passing_vendor_rights_decision(
        path,
        expected_vendor="massive",
        required_data_kind="minute_bars",
    )
    assert evidence.selected_vendor == "massive"
    with pytest.raises(VendorRightsGateError):
        load_passing_vendor_rights_decision(
            path,
            expected_vendor="alpaca_sip",
            required_data_kind="minute_bars",
        )


def test_minute_gate_does_not_borrow_another_vendor_case(tmp_path: Path) -> None:
    _write_authoritative_decision(tmp_path)
    manifest_path = tmp_path / "bakeoff-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    early = next(
        item for item in manifest["samples"] if item["sample_id"].endswith("early-close")
    )
    early["vendor"] = "reference_vendor"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = _rebuild_reports(tmp_path)

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


def test_minute_gate_requires_pre_and_post_dst_evidence(tmp_path: Path) -> None:
    _write_authoritative_decision(tmp_path)
    manifest_path = tmp_path / "bakeoff-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    post_dst = next(
        item
        for item in manifest["samples"]
        if item["sample_id"].endswith("normal-post-dst")
    )
    post_dst["case_tags"].remove("dst_transition")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = _rebuild_reports(tmp_path)

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


def test_minute_gate_requires_selected_vendor_in_overlap(tmp_path: Path) -> None:
    _write_authoritative_decision(tmp_path)
    manifest_path = tmp_path / "bakeoff-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected_overlap = next(
        item
        for item in manifest["samples"]
        if item["sample_id"].endswith("normal-pre-dst")
    )
    selected_overlap["case_tags"].remove("intraday_overlap")
    manifest["samples"].append(
        {
            "sample_id": "second-reference-overlap",
            "vendor": "second_reference_vendor",
            "path": "reference-overlap.csv",
            "kind": "minute_bars",
            "source_format": "canonical_ohlcv",
            "case_tags": ["intraday_overlap"],
        }
    )
    second_rights = dict(manifest["rights"][1])
    second_rights["vendor"] = "second_reference_vendor"
    second_rights["evidence_reference"] = "sha256:" + "d" * 64
    manifest["rights"].append(second_rights)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = _rebuild_reports(tmp_path)

    with pytest.raises(AlpacaRightsGateError):
        load_passing_alpaca_rights_decision(path)


def test_rights_gate_rejects_changed_bakeoff_source_sample(tmp_path: Path) -> None:
    path = _write_authoritative_decision(tmp_path)
    sample_path = tmp_path / "alpaca_sip-normal-pre-dst.csv"
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


def _rebuild_reports(root: Path) -> Path:
    bakeoff_manifest_path = root / "bakeoff-manifest.json"
    bakeoff_report = run_research_data_bakeoff(bakeoff_manifest_path)
    assert bakeoff_report.ok is True
    (root / "bakeoff-report.json").write_text(
        bakeoff_report.model_dump_json(),
        encoding="utf-8",
    )
    decision_report = run_research_vendor_decision(root / "decision-manifest.json")
    assert decision_report.ok is True
    decision_report_path = root / "decision-report.json"
    decision_report_path.write_text(
        decision_report.model_dump_json(),
        encoding="utf-8",
    )
    return decision_report_path
