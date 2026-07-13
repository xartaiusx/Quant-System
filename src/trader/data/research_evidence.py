"""Offline immutable point-in-time research evidence registry."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from trader.data.research_store import initialize_research_store
from trader.models import (
    ResearchEvidenceAuditItem,
    ResearchEvidenceAuditReport,
    ResearchEvidenceAuditRequest,
    ResearchEvidenceKind,
    ResearchEvidenceManifest,
    ResearchEvidenceManifestRecord,
    ResearchEvidencePublicationPrecision,
    ResearchEvidenceRecordSummary,
    ResearchEvidenceRegistrationReport,
    ResearchEvidenceRightsStatus,
    ResearchEvidenceSourceClass,
)


@dataclass(frozen=True)
class _PreparedEvidence:
    record: ResearchEvidenceManifestRecord
    record_fingerprint: str
    source_path: Path | None


def register_research_evidence(
    manifest_path: Path,
    *,
    root: Path,
) -> ResearchEvidenceRegistrationReport:
    """Register an atomic manifest without network, credentials, or broker access."""

    resolved_manifest = manifest_path.expanduser().resolve()
    resolved_root = root.expanduser().resolve()
    try:
        payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        manifest = ResearchEvidenceManifest.model_validate(payload)
        catalog_path = initialize_research_store(resolved_root)
        prepared = [
            _prepare_record(record, manifest_dir=resolved_manifest.parent)
            for record in manifest.records
        ]
    except (OSError, RuntimeError, sqlite3.Error, ValueError, json.JSONDecodeError) as exc:
        return ResearchEvidenceRegistrationReport(
            ok=False,
            manifest_path=resolved_manifest.as_posix(),
            root_path=resolved_root.as_posix(),
            errors=[f"research evidence manifest could not be prepared: {exc}"],
            final_status="failed",
        )

    summaries: list[ResearchEvidenceRecordSummary] = []
    registered_count = 0
    idempotent_count = 0
    try:
        with sqlite3.connect(catalog_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            for item in prepared:
                existing = connection.execute(
                    """
                    SELECT record_fingerprint, archived_path
                    FROM research_evidence
                    WHERE evidence_id = ? AND revision = ?
                    """,
                    (item.record.evidence_id, item.record.revision),
                ).fetchone()
                if existing is not None:
                    if str(existing["record_fingerprint"]) != item.record_fingerprint:
                        raise ValueError(
                            "an evidence revision cannot be changed after registration: "
                            f"{item.record.evidence_id}:{item.record.revision}"
                        )
                    idempotent_count += 1
                    summaries.append(
                        _record_summary(
                            item,
                            archived=existing["archived_path"] is not None,
                        )
                    )
                    continue

                _validate_revision_lineage(connection, item.record)
                archived_path = _archive_artifact(item, root=resolved_root)
                connection.execute(
                    """
                    INSERT INTO research_evidence(
                        evidence_id, revision, supersedes_revision, source_name,
                        source_class, source_reference, source_url,
                        official_source_urls_json, document_id, title,
                        observed_start, observed_end, published_at,
                        publication_time_precision, first_available_at, retrieved_at,
                        vintage, artifact_reference, artifact_sha256, archived_path,
                        rights_status, permitted_excerpt, evidence_kind, topics_json,
                        affected_instruments_json, record_fingerprint, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    _record_values(
                        item,
                        archived_path=archived_path,
                        created_at=datetime.now(UTC),
                    ),
                )
                registered_count += 1
                summaries.append(_record_summary(item, archived=archived_path is not None))
    except (OSError, sqlite3.Error, ValueError) as exc:
        return ResearchEvidenceRegistrationReport(
            ok=False,
            manifest_path=resolved_manifest.as_posix(),
            root_path=resolved_root.as_posix(),
            catalog_path=catalog_path.as_posix(),
            errors=[f"research evidence registration failed: {exc}"],
            final_status="failed",
        )

    warnings = [
        "Offline evidence metadata only; no broker, credentials, or network accessed",
        "Evidence records cannot enable strategy features, promotion, or execution",
    ]
    if any(record.source_class != "official_primary" for record in manifest.records):
        warnings.append(
            "Secondary evidence is hypothesis context only and is not model truth"
        )
    return ResearchEvidenceRegistrationReport(
        ok=True,
        manifest_path=resolved_manifest.as_posix(),
        root_path=resolved_root.as_posix(),
        catalog_path=catalog_path.as_posix(),
        registered_record_count=registered_count,
        idempotent_record_count=idempotent_count,
        records=summaries,
        warnings=warnings,
        final_status="completed",
    )


def audit_research_evidence(
    request: ResearchEvidenceAuditRequest,
) -> ResearchEvidenceAuditReport:
    """Audit public and local availability at an explicit point in time."""

    root = Path(request.root_path).expanduser().resolve()
    try:
        catalog_path = initialize_research_store(root)
        with sqlite3.connect(catalog_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT *
                FROM research_evidence
                ORDER BY first_available_at, retrieved_at, evidence_id, revision
                """
            ).fetchall()
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return ResearchEvidenceAuditReport(
            ok=False,
            request=request,
            errors=[f"research evidence catalog could not be read: {exc}"],
            final_status="failed",
        )

    errors: list[str] = []
    warnings: list[str] = [
        "Offline evidence audit only; no broker, credentials, or network accessed",
        "Evidence audit is permanently non-promoting and execution-ineligible",
    ]
    row_by_key = {
        (str(row["evidence_id"]), str(row["revision"])): row for row in rows
    }
    successor_by_key: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        predecessor = row["supersedes_revision"]
        if predecessor is not None:
            successor_by_key[(str(row["evidence_id"]), str(predecessor))] = row

    items: list[ResearchEvidenceAuditItem] = []
    source_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    for key, row in row_by_key.items():
        try:
            summary = _summary_from_row(row)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid evidence catalog row {key[0]}:{key[1]}: {exc}")
            continue

        publicly_available = summary.first_available_at <= request.as_of
        locally_retrieved = summary.retrieved_at <= request.as_of
        usable_as_of = publicly_available and locally_retrieved
        successor = successor_by_key.get(key)
        superseded_as_of = bool(
            successor is not None
            and _parse_utc(str(successor["first_available_at"])) <= request.as_of
            and _parse_utc(str(successor["retrieved_at"])) <= request.as_of
        )
        archived_integrity = _check_archived_integrity(row, root=root)
        if archived_integrity is False:
            errors.append(
                f"archived evidence checksum mismatch: {summary.evidence_id}:"
                f"{summary.revision}"
            )
        source_counts[str(summary.source_class)] += 1
        kind_counts[str(summary.evidence_kind)] += 1
        topic_counts.update(summary.topics)
        items.append(
            ResearchEvidenceAuditItem(
                **summary.model_dump(),
                publicly_available_as_of=publicly_available,
                locally_retrieved_as_of=locally_retrieved,
                usable_as_of=usable_as_of,
                superseded_as_of=superseded_as_of,
                archived_integrity_ok=archived_integrity,
            )
        )

    usable_count = sum(item.usable_as_of for item in items)
    public_count = sum(item.publicly_available_as_of for item in items)
    local_count = sum(item.locally_retrieved_as_of for item in items)
    superseded_count = sum(item.superseded_as_of for item in items)
    late_retrieval_count = sum(
        item.publicly_available_as_of and not item.locally_retrieved_as_of
        for item in items
    )
    if not items:
        errors.append("no research evidence records found")
    elif usable_count == 0:
        errors.append("no research evidence was both public and locally retrieved as of cutoff")
    if late_retrieval_count:
        warnings.append(
            f"{late_retrieval_count} record(s) were public but not locally retrieved as of cutoff"
        )
    secondary_count = sum(item.source_class != "official_primary" for item in items)
    if secondary_count:
        warnings.append(
            f"{secondary_count} secondary record(s) remain hypothesis context only"
        )
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    ok = not errors
    return ResearchEvidenceAuditReport(
        ok=ok,
        request=request,
        catalog_path=catalog_path.as_posix(),
        total_record_count=len(items),
        publicly_available_count=public_count,
        locally_retrieved_count=local_count,
        usable_as_of_count=usable_count,
        current_as_of_count=sum(
            item.usable_as_of and not item.superseded_as_of for item in items
        ),
        superseded_as_of_count=superseded_count,
        future_evidence_count=sum(not item.publicly_available_as_of for item in items),
        late_retrieval_count=late_retrieval_count,
        source_class_counts=dict(sorted(source_counts.items())),
        evidence_kind_counts=dict(sorted(kind_counts.items())),
        topic_counts=dict(sorted(topic_counts.items())),
        records=items,
        warnings=warnings,
        errors=errors,
        final_status="completed" if ok else "failed",
    )


def _prepare_record(
    record: ResearchEvidenceManifestRecord,
    *,
    manifest_dir: Path,
) -> _PreparedEvidence:
    source_path: Path | None = None
    if record.artifact_path is not None:
        source_path = Path(record.artifact_path).expanduser()
        if not source_path.is_absolute():
            source_path = manifest_dir / source_path
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise ValueError(f"evidence artifact does not exist: {source_path}")
        actual_hash = _sha256(source_path)
        if actual_hash != record.artifact_sha256:
            raise ValueError(
                f"evidence artifact checksum mismatch for {record.evidence_id}:"
                f"{record.revision}"
            )
    fingerprint_payload = record.model_dump(mode="json", exclude={"artifact_path"})
    fingerprint = _fingerprint(fingerprint_payload)
    return _PreparedEvidence(
        record=record,
        record_fingerprint=fingerprint,
        source_path=source_path,
    )


def _validate_revision_lineage(
    connection: sqlite3.Connection,
    record: ResearchEvidenceManifestRecord,
) -> None:
    prior_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM research_evidence WHERE evidence_id = ?",
            (record.evidence_id,),
        ).fetchone()[0]
    )
    if record.supersedes_revision is None:
        if prior_count:
            raise ValueError(
                f"new revisions for {record.evidence_id} must declare supersedes_revision"
            )
        return
    predecessor = connection.execute(
        """
        SELECT 1 FROM research_evidence
        WHERE evidence_id = ? AND revision = ?
        """,
        (record.evidence_id, record.supersedes_revision),
    ).fetchone()
    if predecessor is None:
        raise ValueError(
            f"missing predecessor {record.evidence_id}:{record.supersedes_revision}"
        )
    successor = connection.execute(
        """
        SELECT revision FROM research_evidence
        WHERE evidence_id = ? AND supersedes_revision = ?
        """,
        (record.evidence_id, record.supersedes_revision),
    ).fetchone()
    if successor is not None:
        raise ValueError(
            f"evidence revision already has successor {record.evidence_id}:"
            f"{record.supersedes_revision}"
        )


def _archive_artifact(item: _PreparedEvidence, *, root: Path) -> str | None:
    if item.record.rights_status != ResearchEvidenceRightsStatus.FULL_DOCUMENT_PERMITTED:
        return None
    if item.source_path is None:
        raise ValueError("full-document evidence is missing its source artifact")
    digest = item.record.artifact_sha256.removeprefix("sha256:")
    relative = Path("evidence/artifacts") / digest
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256(destination) != item.record.artifact_sha256:
            raise ValueError("content-addressed evidence archive checksum mismatch")
        return relative.as_posix()
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        shutil.copyfile(item.source_path, temporary)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        if _sha256(temporary) != item.record.artifact_sha256:
            raise ValueError("copied evidence artifact checksum mismatch")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return relative.as_posix()


def _record_values(
    item: _PreparedEvidence,
    *,
    archived_path: str | None,
    created_at: datetime,
) -> tuple[object, ...]:
    record = item.record
    return (
        record.evidence_id,
        record.revision,
        record.supersedes_revision,
        record.source_name,
        str(record.source_class),
        record.source_reference,
        record.source_url,
        json.dumps(record.official_source_urls, sort_keys=True, separators=(",", ":")),
        record.document_id,
        record.title,
        record.observed_start.isoformat(),
        record.observed_end.isoformat(),
        record.published_at.isoformat(),
        str(record.publication_time_precision),
        record.first_available_at.isoformat(),
        record.retrieved_at.isoformat(),
        record.vintage,
        record.artifact_reference,
        record.artifact_sha256,
        archived_path,
        str(record.rights_status),
        record.permitted_excerpt,
        str(record.evidence_kind),
        json.dumps(record.topics, sort_keys=True, separators=(",", ":")),
        json.dumps(record.affected_instruments, sort_keys=True, separators=(",", ":")),
        item.record_fingerprint,
        created_at.isoformat(),
    )


def _record_summary(
    item: _PreparedEvidence,
    *,
    archived: bool,
) -> ResearchEvidenceRecordSummary:
    record = item.record
    return ResearchEvidenceRecordSummary(
        **record.model_dump(exclude={"artifact_path", "permitted_excerpt"}),
        archived=archived,
        record_fingerprint=item.record_fingerprint,
    )


def _summary_from_row(row: sqlite3.Row) -> ResearchEvidenceRecordSummary:
    return ResearchEvidenceRecordSummary(
        evidence_id=str(row["evidence_id"]),
        revision=str(row["revision"]),
        supersedes_revision=(
            str(row["supersedes_revision"])
            if row["supersedes_revision"] is not None
            else None
        ),
        source_name=str(row["source_name"]),
        source_class=ResearchEvidenceSourceClass(str(row["source_class"])),
        source_reference=str(row["source_reference"]),
        source_url=str(row["source_url"]) if row["source_url"] is not None else None,
        official_source_urls=json.loads(str(row["official_source_urls_json"])),
        document_id=str(row["document_id"]),
        title=str(row["title"]),
        observed_start=date.fromisoformat(str(row["observed_start"])),
        observed_end=date.fromisoformat(str(row["observed_end"])),
        published_at=_parse_utc(str(row["published_at"])),
        publication_time_precision=ResearchEvidencePublicationPrecision(
            str(row["publication_time_precision"])
        ),
        first_available_at=_parse_utc(str(row["first_available_at"])),
        retrieved_at=_parse_utc(str(row["retrieved_at"])),
        vintage=str(row["vintage"]),
        artifact_reference=str(row["artifact_reference"]),
        artifact_sha256=str(row["artifact_sha256"]),
        rights_status=ResearchEvidenceRightsStatus(str(row["rights_status"])),
        evidence_kind=ResearchEvidenceKind(str(row["evidence_kind"])),
        topics=json.loads(str(row["topics_json"])),
        affected_instruments=json.loads(str(row["affected_instruments_json"])),
        archived=row["archived_path"] is not None,
        record_fingerprint=str(row["record_fingerprint"]),
    )


def _check_archived_integrity(row: sqlite3.Row, *, root: Path) -> bool | None:
    archived_path = row["archived_path"]
    if archived_path is None:
        return None
    relative = Path(str(archived_path))
    if relative.is_absolute():
        return False
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return False
    return _sha256(target) == str(row["artifact_sha256"])


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("catalog evidence timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = ["audit_research_evidence", "register_research_evidence"]
