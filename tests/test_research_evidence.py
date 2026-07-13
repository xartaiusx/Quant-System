from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from trader.cli import app
from trader.data.research_evidence import (
    audit_research_evidence,
    register_research_evidence,
)
from trader.models import (
    ResearchEvidenceAuditRequest,
    ResearchEvidenceManifest,
)
from trader.reporting.reports import markdown_summary


def test_register_and_audit_point_in_time_primary_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "eia.json"
    artifact.write_text('{"value": 1}\n', encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_record(artifact, evidence_id="eia-release")],
    )
    root = tmp_path / "store"

    registered = register_research_evidence(manifest, root=root)
    audited = audit_research_evidence(
        ResearchEvidenceAuditRequest(
            root_path=root.as_posix(),
            as_of="2026-07-13T19:00:00Z",
        )
    )

    assert registered.ok is True
    assert registered.registered_record_count == 1
    assert registered.records[0].archived is False
    assert registered.strategy_feature_eligible is False
    assert registered.promotion_eligible is False
    assert registered.execution_eligible is False
    assert audited.ok is True
    assert audited.total_record_count == 1
    assert audited.usable_as_of_count == 1
    assert audited.current_as_of_count == 1
    assert audited.records[0].publicly_available_as_of is True
    assert audited.records[0].locally_retrieved_as_of is True
    assert audited.records[0].archived_integrity_ok is None
    assert audited.order_api_invoked is False


def test_audit_distinguishes_publication_from_late_local_retrieval(tmp_path: Path) -> None:
    artifact = tmp_path / "release.json"
    artifact.write_text("{}\n", encoding="utf-8")
    record = _record(artifact, evidence_id="late-release")
    record["published_at"] = "2026-07-10T12:00:00Z"
    record["first_available_at"] = "2026-07-10T12:00:00Z"
    record["retrieved_at"] = "2026-07-13T18:00:00Z"
    manifest = _write_manifest(tmp_path / "manifest.json", [record])
    root = tmp_path / "store"
    assert register_research_evidence(manifest, root=root).ok is True

    report = audit_research_evidence(
        ResearchEvidenceAuditRequest(
            root_path=root.as_posix(),
            as_of="2026-07-11T12:00:00Z",
        )
    )

    assert report.ok is False
    assert report.publicly_available_count == 1
    assert report.locally_retrieved_count == 0
    assert report.usable_as_of_count == 0
    assert report.late_retrieval_count == 1
    assert "both public and locally retrieved" in report.errors[0]


def test_evidence_revisions_are_immutable_idempotent_and_linear(tmp_path: Path) -> None:
    root = tmp_path / "store"
    initial_artifact = tmp_path / "initial.txt"
    initial_artifact.write_text("initial", encoding="utf-8")
    initial_record = _record(initial_artifact, evidence_id="noaa-enso")
    initial_manifest = _write_manifest(tmp_path / "initial.json", [initial_record])

    first = register_research_evidence(initial_manifest, root=root)
    replay = register_research_evidence(initial_manifest, root=root)
    assert first.ok is True
    assert replay.ok is True
    assert replay.idempotent_record_count == 1

    revised_artifact = tmp_path / "revised.txt"
    revised_artifact.write_text("revised", encoding="utf-8")
    revised = _record(
        revised_artifact,
        evidence_id="noaa-enso",
        revision="revision-2",
        supersedes_revision="initial",
    )
    revised["published_at"] = "2026-07-14T12:00:00Z"
    revised["first_available_at"] = "2026-07-14T12:00:00Z"
    revised["retrieved_at"] = "2026-07-14T12:05:00Z"
    revised_manifest = _write_manifest(tmp_path / "revised.json", [revised])
    assert register_research_evidence(revised_manifest, root=root).ok is True

    audit = audit_research_evidence(
        ResearchEvidenceAuditRequest(
            root_path=root.as_posix(),
            as_of="2026-07-14T13:00:00Z",
        )
    )
    assert audit.ok is True
    assert audit.usable_as_of_count == 2
    assert audit.superseded_as_of_count == 1
    assert audit.current_as_of_count == 1

    mutated = dict(initial_record)
    mutated["title"] = "Changed after immutable registration"
    mutated_manifest = _write_manifest(tmp_path / "mutated.json", [mutated])
    rejected = register_research_evidence(mutated_manifest, root=root)
    assert rejected.ok is False
    assert "cannot be changed" in rejected.errors[0]

    fork_artifact = tmp_path / "fork.txt"
    fork_artifact.write_text("fork", encoding="utf-8")
    fork = _record(
        fork_artifact,
        evidence_id="noaa-enso",
        revision="revision-fork",
        supersedes_revision="initial",
    )
    fork["published_at"] = "2026-07-15T12:00:00Z"
    fork["first_available_at"] = "2026-07-15T12:00:00Z"
    fork["retrieved_at"] = "2026-07-15T12:05:00Z"
    fork_manifest = _write_manifest(tmp_path / "fork.json", [fork])
    forked = register_research_evidence(fork_manifest, root=root)
    assert forked.ok is False
    assert "already has successor" in forked.errors[0]


def test_full_document_retention_is_content_addressed_and_audited(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "official.txt"
    artifact.write_text("official release", encoding="utf-8")
    record = _record(artifact, evidence_id="official-archive")
    record["rights_status"] = "full_document_permitted"
    manifest = _write_manifest(tmp_path / "manifest.json", [record])
    root = tmp_path / "store"

    registered = register_research_evidence(manifest, root=root)
    digest = _sha256(artifact).removeprefix("sha256:")
    archived = root / "evidence/artifacts" / digest

    assert registered.ok is True
    assert registered.records[0].archived is True
    assert archived.read_text(encoding="utf-8") == "official release"
    archived.write_text("corrupt", encoding="utf-8")

    audit = audit_research_evidence(
        ResearchEvidenceAuditRequest(
            root_path=root.as_posix(),
            as_of="2026-07-13T19:00:00Z",
        )
    )
    assert audit.ok is False
    assert audit.records[0].archived_integrity_ok is False
    assert "checksum mismatch" in audit.errors[0]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"official_source_urls": ["https://example.com/release"]}, "approved primary"),
        ({"published_at": "2026-07-13T12:00:00"}, "explicit timezone"),
        ({"artifact_sha256": "sha256:bad"}, "SHA-256"),
        ({"affected_instruments": ["ES"]}, "limited to SPY"),
        ({"permitted_excerpt": "not authorized"}, "metadata-only"),
    ],
)
def test_manifest_rejects_unknown_or_unsafe_evidence(
    tmp_path: Path,
    change: dict[str, object],
    message: str,
) -> None:
    artifact = tmp_path / "release.json"
    artifact.write_text("{}", encoding="utf-8")
    record = _record(artifact, evidence_id="invalid")
    record.update(change)

    with pytest.raises(ValidationError, match=message):
        ResearchEvidenceManifest.model_validate(
            {"manifest_version": 1, "records": [record]}
        )


def test_reports_render_and_cli_commands_remain_non_promoting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "release.json"
    artifact.write_text("{}\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_record(artifact, evidence_id="cli-release")],
    )
    root = tmp_path / "store"
    report = register_research_evidence(manifest, root=root)
    markdown = markdown_summary(report.model_dump(mode="json"))
    assert "Point-in-Time Research Evidence Registration" in markdown
    assert "Strategy feature eligible: `False`" in markdown

    monkeypatch.chdir(tmp_path)
    registration = CliRunner().invoke(
        app,
        [
            "research-evidence-register",
            "--manifest",
            manifest.as_posix(),
            "--root",
            root.as_posix(),
        ],
    )
    audit = CliRunner().invoke(
        app,
        [
            "research-evidence-audit",
            "--root",
            root.as_posix(),
            "--as-of",
            "2026-07-13T19:00:00Z",
        ],
    )
    naive = CliRunner().invoke(
        app,
        [
            "research-evidence-audit",
            "--root",
            root.as_posix(),
            "--as-of",
            "2026-07-13T19:00:00",
        ],
    )

    assert registration.exit_code == 0
    assert "Strategy feature eligible: false" in registration.output
    assert audit.exit_code == 0
    assert "Usable as of cutoff: 1" in audit.output
    assert naive.exit_code == 2
    assert "explicit timezone" in naive.output


def test_evidence_module_is_offline_broker_free_and_order_free() -> None:
    source = Path("src/trader/data/research_evidence.py").read_text(encoding="utf-8")
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "import ibapi",
        "from ibapi",
        "httpx",
        "requests",
        "urllib.request",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
    ):
        assert forbidden not in source


def test_catalog_stores_no_source_artifact_path_or_full_metadata_only_content(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "private-location" / "brief.txt"
    artifact.parent.mkdir()
    artifact.write_text("brief content", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_record(artifact, evidence_id="secondary")],
    )
    root = tmp_path / "store"
    assert register_research_evidence(manifest, root=root).ok is True

    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        row = connection.execute(
            "SELECT archived_path, permitted_excerpt FROM research_evidence"
        ).fetchone()
        columns = {
            item[1] for item in connection.execute("PRAGMA table_info(research_evidence)")
        }
    assert row == (None, None)
    assert "artifact_path" not in columns


def _record(
    artifact: Path,
    *,
    evidence_id: str,
    revision: str = "initial",
    supersedes_revision: str | None = None,
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "revision": revision,
        "supersedes_revision": supersedes_revision,
        "source_name": "U.S. Energy Information Administration",
        "source_class": "official_primary",
        "source_reference": "eia-api-v2-release",
        "source_url": "https://www.eia.gov/opendata/documentation.php",
        "official_source_urls": ["https://www.eia.gov/opendata/documentation.php"],
        "document_id": f"document-{evidence_id}",
        "title": "Official point-in-time release",
        "observed_start": "2026-07-01",
        "observed_end": "2026-07-10",
        "published_at": "2026-07-13T18:00:00Z",
        "publication_time_precision": "exact",
        "first_available_at": "2026-07-13T18:00:00Z",
        "retrieved_at": "2026-07-13T18:05:00Z",
        "vintage": "2026-07-13",
        "artifact_reference": artifact.name,
        "artifact_path": artifact.as_posix(),
        "artifact_sha256": _sha256(artifact),
        "rights_status": "metadata_only",
        "evidence_kind": "fact",
        "topics": ["energy", "petroleum"],
        "affected_instruments": ["SPY", "USO"],
    }


def _write_manifest(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps({"manifest_version": 1, "records": records}),
        encoding="utf-8",
    )
    return path


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
