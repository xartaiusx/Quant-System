"""Offline immutable SPY research-data store and lineage catalog."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from trader.models import (
    ResearchDataArtifact,
    ResearchDataAuditReport,
    ResearchDataAuditRequest,
    ResearchDataIngestReport,
    ResearchDataIngestRequest,
    ResearchDataPartition,
    ResearchDataQualityFinding,
    ResearchDataQualityStatus,
)

DEFAULT_RESEARCH_DATA_ROOT = Path("D:/MarketData/Quant-System")
CATALOG_RELATIVE_PATH = Path("catalog/research.sqlite3")
CATALOG_SCHEMA_VERSION = 3
_MASSIVE_REQUIRED_COLUMNS = frozenset(
    {
        "ticker",
        "volume",
        "open",
        "close",
        "high",
        "low",
        "window_start",
        "transactions",
    }
)
_ALPACA_REQUIRED_FIELDS = frozenset({"t", "o", "h", "l", "c", "v", "n", "vw"})
_UTC_NANOSECONDS_PER_MINUTE = 60_000_000_000
_PRICE_QUANTUM = Decimal("0.00000001")
_EASTERN = ZoneInfo("America/New_York")
_DATE_IN_FILENAME = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})")
_SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class _MinuteAggregate:
    timestamp: datetime
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    transactions: int
    vwap: Decimal | None = None


@dataclass(frozen=True)
class _ParsedFile:
    rows_scanned: int
    symbol_rows_seen: int
    outside_rth_rows_excluded: int
    rows_by_session: dict[date, list[_MinuteAggregate]]
    findings: list[ResearchDataQualityFinding]


def ingest_massive_minute_file(
    request: ResearchDataIngestRequest,
) -> ResearchDataIngestReport:
    """Archive and ingest one licensed Massive aggregate flat file offline."""

    if request.source_name != "massive":
        raise ValueError("Massive ingestion requires source_name=massive")
    return _ingest_minute_file(request)


def ingest_alpaca_sip_minute_file(
    request: ResearchDataIngestRequest,
) -> ResearchDataIngestReport:
    """Archive and ingest one rights-approved Alpaca SIP JSON export offline."""

    if request.source_name != "alpaca_sip":
        raise ValueError("Alpaca SIP ingestion requires source_name=alpaca_sip")
    return _ingest_minute_file(request)


def _ingest_minute_file(
    request: ResearchDataIngestRequest,
) -> ResearchDataIngestReport:
    """Archive and ingest one supported immutable SIP minute artifact."""

    root = Path(request.root_path).expanduser().resolve()
    catalog_path = root / CATALOG_RELATIVE_PATH
    try:
        catalog_path = initialize_research_store(root)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        message = f"research store could not be initialized: {exc}"
        return _failed_ingest_report(
            request,
            root=root,
            catalog_path=catalog_path,
            warnings=["Offline research-data ingestion only; no broker contacted"],
            errors=[message],
            findings=[_finding("error", "store_initialization_failed", message)],
        )
    source_path = Path(request.source_path).expanduser().resolve()
    standard_warning = "Offline research-data ingestion only; no broker contacted"
    if not source_path.is_file():
        message = f"source flat file not found: {source_path}"
        return _failed_ingest_report(
            request,
            root=root,
            catalog_path=catalog_path,
            warnings=[standard_warning],
            errors=[message],
            findings=[_finding("error", "source_not_found", message)],
        )

    try:
        source_sha256 = _sha256_file(source_path)
        archived_path = _archive_source_file(
            source_path,
            root=root,
            source_sha256=source_sha256,
            request=request,
        )
    except (OSError, RuntimeError) as exc:
        message = f"source flat file could not be archived immutably: {exc}"
        return _failed_ingest_report(
            request,
            root=root,
            catalog_path=catalog_path,
            warnings=[standard_warning],
            errors=[message],
            findings=[_finding("error", "source_archive_failed", message)],
        )
    artifact = ResearchDataArtifact(
        source_path=source_path.as_posix(),
        stored_path=archived_path.as_posix(),
        sha256=source_sha256,
        size_bytes=archived_path.stat().st_size,
    )
    run_id = uuid4().hex

    try:
        parsed = _parse_minute_file(archived_path, request=request)
    except (csv.Error, OSError, UnicodeError, ValueError) as exc:
        message = f"source flat file could not be parsed: {exc}"
        findings = [_finding("error", "source_parse_failed", message)]
        with _catalog_connection(catalog_path) as connection:
            artifact_id = _upsert_artifact(connection, request, artifact)
            _record_ingestion_run(
                connection,
                run_id=run_id,
                artifact_id=artifact_id,
                request=request,
                status="failed",
                parsed=None,
                findings=findings,
            )
        return _failed_ingest_report(
            request,
            root=root,
            catalog_path=catalog_path,
            artifact=artifact,
            warnings=[standard_warning],
            errors=[message],
            findings=findings,
        )

    findings = [*parsed.findings, *_quality_findings(parsed.rows_by_session, archived_path)]
    errors = list(dict.fromkeys(item.message for item in findings if item.severity == "error"))
    warnings = list(
        dict.fromkeys(
            [standard_warning, *[item.message for item in findings if item.severity == "warning"]]
        )
    )
    try:
        with _catalog_connection(catalog_path) as connection:
            artifact_id = _upsert_artifact(connection, request, artifact)
            if errors:
                _record_ingestion_run(
                    connection,
                    run_id=run_id,
                    artifact_id=artifact_id,
                    request=request,
                    status="failed",
                    parsed=parsed,
                    findings=findings,
                )
                return _failed_ingest_report(
                    request,
                    root=root,
                    catalog_path=catalog_path,
                    artifact=artifact,
                    parsed=parsed,
                    warnings=warnings,
                    errors=errors,
                    findings=findings,
                )

            _record_ingestion_run(
                connection,
                run_id=run_id,
                artifact_id=artifact_id,
                request=request,
                status="processing",
                parsed=parsed,
                findings=[],
            )
            partitions, idempotent_replay = _activate_partitions(
                connection,
                root=root,
                artifact=artifact,
                run_id=run_id,
                artifact_id=artifact_id,
                request=request,
                parsed=parsed,
            )
            _record_ingestion_run(
                connection,
                run_id=run_id,
                artifact_id=artifact_id,
                request=request,
                status="unchanged" if idempotent_replay else "completed",
                parsed=parsed,
                findings=findings,
                partitions=partitions,
            )
    except (OSError, RuntimeError, sqlite3.Error, pa.ArrowException) as exc:
        message = f"curated research partition could not be activated: {exc}"
        storage_finding = _finding("error", "partition_activation_failed", message)
        return _failed_ingest_report(
            request,
            root=root,
            catalog_path=catalog_path,
            artifact=artifact,
            parsed=parsed,
            warnings=warnings,
            errors=[*errors, message],
            findings=[*findings, storage_finding],
        )

    return ResearchDataIngestReport(
        ok=bool(partitions),
        request=request,
        root_path=root.as_posix(),
        catalog_path=catalog_path.as_posix(),
        artifact=artifact,
        rows_scanned=parsed.rows_scanned,
        symbol_rows_seen=parsed.symbol_rows_seen,
        rth_rows_selected=sum(len(rows) for rows in parsed.rows_by_session.values()),
        outside_rth_rows_excluded=parsed.outside_rth_rows_excluded,
        idempotent_replay=idempotent_replay,
        partitions=partitions,
        findings=findings,
        warnings=warnings,
        final_status="unchanged" if idempotent_replay else "completed",
    )


def audit_research_data_store(
    request: ResearchDataAuditRequest,
) -> ResearchDataAuditReport:
    """Verify active catalog coverage, files, checksums, and Parquet row counts."""

    root = Path(request.root_path).expanduser().resolve()
    catalog_path = root / CATALOG_RELATIVE_PATH
    standard_warning = "Offline research-data audit only; no broker contacted"
    if not catalog_path.is_file():
        message = f"research data catalog not found: {catalog_path}"
        return ResearchDataAuditReport(
            ok=False,
            request=request,
            root_path=root.as_posix(),
            catalog_path=catalog_path.as_posix(),
            findings=[_finding("error", "catalog_not_found", message)],
            warnings=[standard_warning],
            errors=[message],
            final_status="failed",
        )

    with _catalog_connection(catalog_path) as connection:
        rows = connection.execute(
            """
            SELECT p.*, a.sha256 AS source_sha256
            FROM partitions AS p
            JOIN source_artifacts AS a ON a.id = p.artifact_id
            WHERE p.symbol = ? AND p.dataset = ? AND p.price_view = ? AND p.active = 1
            ORDER BY p.session_date, p.revision
            """,
            (request.symbol, request.dataset, request.price_view),
        ).fetchall()

    findings: list[ResearchDataQualityFinding] = []
    partitions = [_partition_from_row(row) for row in rows]
    if not partitions:
        findings.append(
            _finding("error", "no_active_partitions", "no active SPY partitions found")
        )

    active_dates = [partition.session_date for partition in partitions]
    if len(active_dates) != len(set(active_dates)):
        findings.append(
            _finding(
                "error",
                "duplicate_active_session",
                "multiple active revisions exist for one or more sessions",
                count=len(active_dates) - len(set(active_dates)),
            )
        )

    for partition in partitions:
        path = Path(partition.parquet_path).resolve()
        if not _is_relative_to(path, root):
            findings.append(
                _finding(
                    "error",
                    "partition_outside_root",
                    f"partition path escapes research root: {path}",
                    session_date=partition.session_date,
                )
            )
            continue
        if not path.is_file():
            findings.append(
                _finding(
                    "error",
                    "partition_missing",
                    f"active Parquet partition is missing: {path}",
                    session_date=partition.session_date,
                )
            )
            continue
        actual_sha256 = _sha256_file(path)
        if actual_sha256 != partition.parquet_sha256:
            findings.append(
                _finding(
                    "error",
                    "partition_checksum_mismatch",
                    f"Parquet checksum mismatch for {partition.session_date}",
                    session_date=partition.session_date,
                    samples=[actual_sha256],
                )
            )
            continue
        try:
            row_count = pq.ParquetFile(path).metadata.num_rows
        except (OSError, pa.ArrowException) as exc:
            findings.append(
                _finding(
                    "error",
                    "partition_unreadable",
                    f"active Parquet partition is unreadable for "
                    f"{partition.session_date}: {exc}",
                    session_date=partition.session_date,
                )
            )
            continue
        if row_count != partition.row_count:
            findings.append(
                _finding(
                    "error",
                    "partition_row_count_mismatch",
                    f"Parquet row count mismatch for {partition.session_date}",
                    session_date=partition.session_date,
                    samples=[str(row_count), str(partition.row_count)],
                )
            )

    missing_sessions = _missing_catalog_sessions(active_dates)
    if missing_sessions:
        findings.append(
            _finding(
                "error",
                "missing_catalog_sessions",
                f"active catalog has missing XNYS sessions: {len(missing_sessions)}",
                count=len(missing_sessions),
                samples=missing_sessions[:_SAMPLE_LIMIT],
            )
        )

    errors = list(dict.fromkeys(item.message for item in findings if item.severity == "error"))
    return ResearchDataAuditReport(
        ok=bool(partitions) and not errors,
        request=request,
        root_path=root.as_posix(),
        catalog_path=catalog_path.as_posix(),
        active_partitions=partitions,
        active_session_count=len(partitions),
        total_row_count=sum(partition.row_count for partition in partitions),
        first_session_date=active_dates[0] if active_dates else None,
        last_session_date=active_dates[-1] if active_dates else None,
        missing_session_dates=missing_sessions,
        findings=findings,
        warnings=[standard_warning],
        errors=errors,
        final_status="completed" if partitions and not errors else "failed",
    )


def initialize_research_store(root: Path) -> Path:
    """Create the offline research-store layout and versioned SQLite catalog."""

    root.mkdir(parents=True, exist_ok=True)
    for relative in ("raw", "curated", "catalog", "quarantine"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    catalog_path = root / CATALOG_RELATIVE_PATH
    with _catalog_connection(catalog_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                version INTEGER PRIMARY KEY,
                installed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                dataset TEXT NOT NULL,
                original_path TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id TEXT PRIMARY KEY,
                artifact_id INTEGER NOT NULL REFERENCES source_artifacts(id),
                symbol TEXT NOT NULL,
                dataset TEXT NOT NULL,
                price_view TEXT NOT NULL,
                status TEXT NOT NULL,
                rows_scanned INTEGER NOT NULL,
                symbol_rows_seen INTEGER NOT NULL,
                rth_rows_selected INTEGER NOT NULL,
                outside_rth_rows_excluded INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS partitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_id INTEGER NOT NULL REFERENCES source_artifacts(id),
                run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
                symbol TEXT NOT NULL,
                dataset TEXT NOT NULL,
                price_view TEXT NOT NULL,
                session_date TEXT NOT NULL,
                revision INTEGER NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                row_count INTEGER NOT NULL,
                expected_row_count INTEGER NOT NULL,
                first_timestamp TEXT,
                last_timestamp TEXT,
                parquet_path TEXT NOT NULL,
                parquet_sha256 TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(symbol, dataset, price_view, session_date, revision),
                UNIQUE(artifact_id, symbol, dataset, price_view, session_date)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_partition_per_session
            ON partitions(symbol, dataset, price_view, session_date)
            WHERE active = 1;
            CREATE TABLE IF NOT EXISTS quality_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
                partition_id INTEGER REFERENCES partitions(id),
                severity TEXT NOT NULL,
                code TEXT NOT NULL,
                message TEXT NOT NULL,
                finding_count INTEGER NOT NULL,
                session_date TEXT,
                samples_json TEXT NOT NULL
            );
            """
        )
        versions = sorted(
            row[0] for row in connection.execute("SELECT version FROM schema_metadata")
        )
        if not versions:
            connection.execute(
                "INSERT INTO schema_metadata(version, installed_at) VALUES (?, ?)",
                (1, _utc_iso()),
            )
            versions = [1]
        if versions[-1] == 1:
            _install_catalog_v2(connection)
            connection.execute(
                "INSERT INTO schema_metadata(version, installed_at) VALUES (?, ?)",
                (2, _utc_iso()),
            )
            versions.append(2)
        if versions[-1] == 2:
            _install_catalog_v3(connection)
            versions.append(3)
        if versions != list(range(1, CATALOG_SCHEMA_VERSION + 1)):
            raise RuntimeError(f"unsupported research catalog schema versions: {versions}")
    return catalog_path


def _install_catalog_v2(connection: sqlite3.Connection) -> None:
    """Install additive corporate-action, derived-lineage, and experiment tables."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS action_sets (
            id TEXT PRIMARY KEY,
            artifact_id INTEGER NOT NULL REFERENCES source_artifacts(id),
            source_name TEXT NOT NULL,
            dataset TEXT NOT NULL,
            symbol TEXT NOT NULL,
            coverage_start TEXT NOT NULL,
            coverage_end TEXT NOT NULL,
            complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            source_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS corporate_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_set_id TEXT NOT NULL REFERENCES action_sets(id),
            symbol TEXT NOT NULL,
            action_type TEXT NOT NULL,
            ex_date TEXT NOT NULL,
            factor TEXT,
            cash_amount TEXT,
            currency TEXT,
            revision TEXT NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE(action_set_id, symbol, action_type, ex_date, revision)
        );
        CREATE INDEX IF NOT EXISTS corporate_actions_lookup
        ON corporate_actions(symbol, ex_date, action_type, active);
        CREATE TABLE IF NOT EXISTS derived_partitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            dataset TEXT NOT NULL,
            price_view TEXT NOT NULL,
            bar_size TEXT NOT NULL,
            session_date TEXT NOT NULL,
            revision INTEGER NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            row_count INTEGER NOT NULL,
            expected_row_count INTEGER NOT NULL,
            first_timestamp TEXT,
            last_timestamp TEXT,
            parquet_path TEXT NOT NULL,
            parquet_sha256 TEXT NOT NULL,
            action_fingerprint TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            algorithm_version TEXT NOT NULL,
            quality_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(symbol, dataset, price_view, bar_size, session_date, revision)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_derived_partition
        ON derived_partitions(symbol, dataset, price_view, bar_size, session_date)
        WHERE active = 1;
        CREATE TABLE IF NOT EXISTS derived_lineage (
            derived_partition_id INTEGER NOT NULL REFERENCES derived_partitions(id),
            parent_partition_id INTEGER NOT NULL REFERENCES partitions(id),
            lineage_role TEXT NOT NULL,
            parent_parquet_sha256 TEXT NOT NULL,
            PRIMARY KEY (derived_partition_id, parent_partition_id, lineage_role)
        );
        CREATE TABLE IF NOT EXISTS experiment_specs (
            experiment_id TEXT PRIMARY KEY,
            spec_fingerprint TEXT NOT NULL UNIQUE,
            spec_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS experiment_runs (
            run_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL REFERENCES experiment_specs(experiment_id),
            phase TEXT NOT NULL,
            dataset_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL,
            report_path TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS holdout_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL REFERENCES experiment_specs(experiment_id),
            holdout_fingerprint TEXT NOT NULL,
            confirmation TEXT NOT NULL,
            accessed_at TEXT NOT NULL,
            UNIQUE(experiment_id, holdout_fingerprint)
        );
        """
    )


def _install_catalog_v3(connection: sqlite3.Connection) -> None:
    """Install holdout governance and versioned instrument identity metadata."""

    connection.executescript(
        """
        SAVEPOINT install_catalog_v3;
        ALTER TABLE experiment_specs
        ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
        ALTER TABLE experiment_specs
        ADD COLUMN supersedes_experiment_id TEXT;
        ALTER TABLE experiment_specs
        ADD COLUMN superseded_by_experiment_id TEXT;
        CREATE TABLE sealed_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL REFERENCES experiment_specs(experiment_id),
            symbol TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            purpose TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (start_date <= end_date),
            UNIQUE(experiment_id, symbol, start_date, end_date, purpose)
        );
        CREATE INDEX sealed_period_overlap_lookup
        ON sealed_periods(symbol, start_date, end_date);
        CREATE TABLE instrument_master (
            internal_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            security_name TEXT NOT NULL,
            sec_type TEXT NOT NULL,
            currency TEXT NOT NULL,
            primary_exchange TEXT NOT NULL,
            routing_exchange TEXT NOT NULL,
            min_tick TEXT NOT NULL,
            listing_start TEXT NOT NULL,
            listing_end TEXT,
            ibkr_con_id INTEGER NOT NULL,
            composite_figi TEXT,
            cusip TEXT,
            isin TEXT,
            vendor_mappings_json TEXT NOT NULL,
            source_references_json TEXT NOT NULL,
            record_fingerprint TEXT NOT NULL,
            active INTEGER NOT NULL CHECK(active IN (0, 1)),
            created_at TEXT NOT NULL,
            PRIMARY KEY (internal_id, version)
        );
        CREATE UNIQUE INDEX one_active_instrument_revision
        ON instrument_master(internal_id) WHERE active = 1;
        INSERT INTO schema_metadata(version, installed_at)
        VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
        RELEASE SAVEPOINT install_catalog_v3;
        """
    )


def _parse_minute_file(
    path: Path,
    *,
    request: ResearchDataIngestRequest,
) -> _ParsedFile:
    if request.source_name == "massive":
        return _parse_massive_minute_file(path, request=request)
    if request.source_name == "alpaca_sip":
        return _parse_alpaca_sip_minute_file(path, request=request)
    raise ValueError(f"unsupported minute source: {request.source_name}")


def _parse_massive_minute_file(
    path: Path,
    *,
    request: ResearchDataIngestRequest,
) -> _ParsedFile:
    calendar = xcals.get_calendar("XNYS")
    rows_scanned = 0
    symbol_rows_seen = 0
    outside_rth_rows_excluded = 0
    rows_by_session: dict[date, list[_MinuteAggregate]] = defaultdict(list)
    findings: list[ResearchDataQualityFinding] = []
    with _open_csv_text(path) as stream:
        reader = csv.DictReader(stream)
        headers = frozenset(reader.fieldnames or [])
        missing_columns = sorted(_MASSIVE_REQUIRED_COLUMNS - headers)
        if missing_columns:
            raise ValueError(f"missing required Massive columns: {', '.join(missing_columns)}")
        for line_number, row in enumerate(reader, start=2):
            rows_scanned += 1
            if (row.get("ticker") or "").strip().upper() != request.symbol:
                continue
            symbol_rows_seen += 1
            try:
                aggregate = _parse_minute_row(row)
            except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
                findings.append(
                    _finding(
                        "error",
                        "malformed_massive_row",
                        f"malformed SPY row at line {line_number}: {exc}",
                        samples=[str(line_number)],
                    )
                )
                continue

            try:
                session = calendar.date_to_session(aggregate.session_date, direction="none")
            except ValueError:
                outside_rth_rows_excluded += 1
                continue
            session_open = calendar.session_open(session).to_pydatetime()
            session_close = calendar.session_close(session).to_pydatetime()
            if not session_open <= aggregate.timestamp < session_close:
                outside_rth_rows_excluded += 1
                continue
            rows_by_session[aggregate.session_date].append(aggregate)

    if symbol_rows_seen == 0:
        findings.append(_finding("error", "symbol_not_found", "source contains no SPY rows"))
    if symbol_rows_seen and not rows_by_session:
        findings.append(
            _finding("error", "no_rth_rows", "source contains no SPY regular-session rows")
        )
    return _ParsedFile(
        rows_scanned=rows_scanned,
        symbol_rows_seen=symbol_rows_seen,
        outside_rth_rows_excluded=outside_rth_rows_excluded,
        rows_by_session=dict(rows_by_session),
        findings=findings,
    )


def _parse_alpaca_sip_minute_file(
    path: Path,
    *,
    request: ResearchDataIngestRequest,
) -> _ParsedFile:
    calendar = xcals.get_calendar("XNYS")
    payload = _read_json_payload(path)
    if payload.get("source") != "alpaca_sip":
        raise ValueError("Alpaca source payload must declare source=alpaca_sip")
    if str(payload.get("symbol", "")).upper() != request.symbol:
        raise ValueError("Alpaca source payload must contain SPY only")
    if payload.get("feed") != "sip" or payload.get("timeframe") != "1Min":
        raise ValueError("Alpaca source payload must use SIP one-minute bars")
    if payload.get("adjustment") != "raw" or payload.get("sort") != "asc":
        raise ValueError("Alpaca source payload must be raw and ascending")
    raw_bars = payload.get("bars")
    if not isinstance(raw_bars, list):
        raise ValueError("Alpaca source payload must contain a bars array")

    rows_by_session: dict[date, list[_MinuteAggregate]] = defaultdict(list)
    findings: list[ResearchDataQualityFinding] = []
    outside_rth_rows_excluded = 0
    for index, raw_bar in enumerate(raw_bars, start=1):
        if not isinstance(raw_bar, dict) or not _ALPACA_REQUIRED_FIELDS.issubset(raw_bar):
            findings.append(
                _finding(
                    "error",
                    "malformed_alpaca_row",
                    f"malformed SPY Alpaca bar at index {index}: missing required fields",
                    samples=[str(index)],
                )
            )
            continue
        try:
            aggregate = _parse_alpaca_minute_row(raw_bar)
        except (InvalidOperation, TypeError, ValueError) as exc:
            findings.append(
                _finding(
                    "error",
                    "malformed_alpaca_row",
                    f"malformed SPY Alpaca bar at index {index}: {exc}",
                    samples=[str(index)],
                )
            )
            continue
        try:
            session = calendar.date_to_session(aggregate.session_date, direction="none")
        except ValueError:
            outside_rth_rows_excluded += 1
            continue
        session_open = calendar.session_open(session).to_pydatetime()
        session_close = calendar.session_close(session).to_pydatetime()
        if not session_open <= aggregate.timestamp < session_close:
            outside_rth_rows_excluded += 1
            continue
        rows_by_session[aggregate.session_date].append(aggregate)
    if not raw_bars:
        findings.append(_finding("error", "symbol_not_found", "source contains no SPY rows"))
    if raw_bars and not rows_by_session:
        findings.append(
            _finding("error", "no_rth_rows", "source contains no SPY regular-session rows")
        )
    return _ParsedFile(
        rows_scanned=len(raw_bars),
        symbol_rows_seen=len(raw_bars),
        outside_rth_rows_excluded=outside_rth_rows_excluded,
        rows_by_session=dict(rows_by_session),
        findings=findings,
    )


def _parse_minute_row(row: dict[str, str]) -> _MinuteAggregate:
    window_start = int(row["window_start"])
    if window_start % _UTC_NANOSECONDS_PER_MINUTE:
        raise ValueError("window_start is not aligned to a UTC minute")
    timestamp = datetime.fromtimestamp(window_start // 1_000_000_000, tz=UTC)
    session_date = timestamp.astimezone(_EASTERN).date()
    open_ = _price(row["open"])
    close = _price(row["close"])
    high = _price(row["high"])
    low = _price(row["low"])
    volume = _whole_number(row["volume"], "volume")
    transactions = _whole_number(row["transactions"], "transactions")
    return _MinuteAggregate(
        timestamp=timestamp,
        session_date=session_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        transactions=transactions,
    )


def _parse_alpaca_minute_row(row: dict[str, Any]) -> _MinuteAggregate:
    timestamp = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Alpaca timestamp must include a timezone")
    timestamp = timestamp.astimezone(UTC)
    if timestamp.second or timestamp.microsecond:
        raise ValueError("Alpaca timestamp is not aligned to a UTC minute")
    session_date = timestamp.astimezone(_EASTERN).date()
    return _MinuteAggregate(
        timestamp=timestamp,
        session_date=session_date,
        open=_price(row["o"]),
        high=_price(row["h"]),
        low=_price(row["l"]),
        close=_price(row["c"]),
        volume=_whole_number(row["v"], "volume"),
        transactions=_whole_number(row["n"], "transactions"),
        vwap=_price(row["vw"]),
    )


def _quality_findings(
    rows_by_session: dict[date, list[_MinuteAggregate]],
    archived_path: Path,
) -> list[ResearchDataQualityFinding]:
    findings: list[ResearchDataQualityFinding] = []
    filename_date = _date_from_filename(archived_path.name)
    calendar = xcals.get_calendar("XNYS")
    for session_date, rows in sorted(rows_by_session.items()):
        session_text = session_date.isoformat()
        timestamps = [row.timestamp for row in rows]
        if timestamps != sorted(timestamps):
            findings.append(
                _finding(
                    "error",
                    "out_of_order_rows",
                    f"SPY rows are out of order for {session_text}",
                    session_date=session_text,
                )
            )
        duplicate_count = len(timestamps) - len(set(timestamps))
        if duplicate_count:
            findings.append(
                _finding(
                    "error",
                    "duplicate_timestamps",
                    f"duplicate SPY minute timestamps for {session_text}",
                    count=duplicate_count,
                    session_date=session_text,
                )
            )
        invalid_ohlc = [
            row.timestamp.isoformat()
            for row in rows
            if row.high < max(row.open, row.close, row.low)
            or row.low > min(row.open, row.close, row.high)
        ]
        if invalid_ohlc:
            findings.append(
                _finding(
                    "error",
                    "invalid_ohlc",
                    f"invalid OHLC relationships for {session_text}",
                    count=len(invalid_ohlc),
                    session_date=session_text,
                    samples=invalid_ohlc[:_SAMPLE_LIMIT],
                )
            )
        negative_values = [
            row.timestamp.isoformat()
            for row in rows
            if row.volume < 0 or row.transactions < 0
        ]
        if negative_values:
            findings.append(
                _finding(
                    "error",
                    "negative_activity",
                    f"negative volume or transaction counts for {session_text}",
                    count=len(negative_values),
                    session_date=session_text,
                    samples=negative_values[:_SAMPLE_LIMIT],
                )
            )
        zero_volume = [row.timestamp.isoformat() for row in rows if row.volume == 0]
        if zero_volume:
            findings.append(
                _finding(
                    "warning",
                    "zero_volume",
                    f"zero-volume SPY bars for {session_text}",
                    count=len(zero_volume),
                    session_date=session_text,
                    samples=zero_volume[:_SAMPLE_LIMIT],
                )
            )
        session = calendar.date_to_session(session_date, direction="none")
        expected = {
            value.to_pydatetime() for value in calendar.session_minutes(session)
        }
        actual = set(timestamps)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing:
            findings.append(
                _finding(
                    "error",
                    "missing_rth_minutes",
                    f"missing XNYS SPY minutes for {session_text}: {len(missing)}",
                    count=len(missing),
                    session_date=session_text,
                    samples=[value.isoformat() for value in missing[:_SAMPLE_LIMIT]],
                )
            )
        if unexpected:
            findings.append(
                _finding(
                    "error",
                    "unexpected_rth_minutes",
                    f"unexpected XNYS SPY minutes for {session_text}: {len(unexpected)}",
                    count=len(unexpected),
                    session_date=session_text,
                    samples=[value.isoformat() for value in unexpected[:_SAMPLE_LIMIT]],
                )
            )
        if filename_date is not None and filename_date != session_date:
            findings.append(
                _finding(
                    "error",
                    "filename_session_mismatch",
                    f"source filename date does not match SPY session {session_text}",
                    session_date=session_text,
                    samples=[filename_date.isoformat()],
                )
            )
    return findings


def _activate_partitions(
    connection: sqlite3.Connection,
    *,
    root: Path,
    run_id: str,
    artifact_id: int,
    artifact: ResearchDataArtifact,
    request: ResearchDataIngestRequest,
    parsed: _ParsedFile,
) -> tuple[list[ResearchDataPartition], bool]:
    existing_rows = connection.execute(
        """
        SELECT p.*, a.sha256 AS source_sha256
        FROM partitions AS p
        JOIN source_artifacts AS a ON a.id = p.artifact_id
        WHERE p.artifact_id = ? AND p.symbol = ? AND p.dataset = ? AND p.price_view = ?
        ORDER BY p.session_date
        """,
        (artifact_id, request.symbol, request.dataset, request.price_view),
    ).fetchall()
    existing_by_session = {row["session_date"]: row for row in existing_rows}
    if set(existing_by_session) == {
        value.isoformat() for value in parsed.rows_by_session
    }:
        return ([_partition_from_row(row) for row in existing_rows], True)

    partitions: list[ResearchDataPartition] = []
    for session_date, rows in sorted(parsed.rows_by_session.items()):
        session_text = session_date.isoformat()
        existing = existing_by_session.get(session_text)
        if existing is not None:
            partitions.append(_partition_from_row(existing))
            continue
        revision_row = connection.execute(
            """
            SELECT COALESCE(MAX(revision), 0)
            FROM partitions
            WHERE symbol = ? AND dataset = ? AND price_view = ? AND session_date = ?
            """,
            (request.symbol, request.dataset, request.price_view, session_text),
        ).fetchone()
        if revision_row is None:
            raise RuntimeError("partition revision query returned no row")
        revision = int(revision_row[0]) + 1
        connection.execute(
            """
            UPDATE partitions SET active = 0
            WHERE symbol = ? AND dataset = ? AND price_view = ? AND session_date = ?
            """,
            (request.symbol, request.dataset, request.price_view, session_text),
        )
        parquet_path = _partition_path(
            root,
            request=request,
            session_date=session_date,
            revision=revision,
            source_sha256=artifact.sha256,
        )
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        _write_partition(
            parquet_path,
            rows,
            source_sha256=artifact.sha256,
            request=request,
        )
        parquet_sha256 = _sha256_file(parquet_path)
        first_timestamp = rows[0].timestamp
        last_timestamp = rows[-1].timestamp
        expected_row_count = len(
            xcals.get_calendar("XNYS").session_minutes(session_date)
        )
        cursor = connection.execute(
            """
            INSERT INTO partitions(
                artifact_id, run_id, symbol, dataset, price_view, session_date,
                revision, active, row_count, expected_row_count, first_timestamp,
                last_timestamp, parquet_path, parquet_sha256, quality_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                run_id,
                request.symbol,
                request.dataset,
                request.price_view,
                session_text,
                revision,
                len(rows),
                expected_row_count,
                first_timestamp.isoformat(),
                last_timestamp.isoformat(),
                parquet_path.as_posix(),
                parquet_sha256,
                ResearchDataQualityStatus.PASSED.value,
                _utc_iso(),
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("curated partition was not recorded")
        partitions.append(
            ResearchDataPartition(
                session_date=session_text,
                revision=revision,
                row_count=len(rows),
                expected_row_count=expected_row_count,
                first_timestamp=first_timestamp,
                last_timestamp=last_timestamp,
                parquet_path=parquet_path.as_posix(),
                parquet_sha256=parquet_sha256,
                source_sha256=artifact.sha256,
                quality_status=ResearchDataQualityStatus.PASSED,
            )
        )
    return partitions, False


def _write_partition(
    path: Path,
    rows: list[_MinuteAggregate],
    *,
    source_sha256: str,
    request: ResearchDataIngestRequest,
) -> None:
    schema = pa.schema(
        [
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("event_time_utc", pa.timestamp("ns", tz="UTC"), nullable=False),
            pa.field("session_date", pa.date32(), nullable=False),
            pa.field("open", pa.decimal128(20, 8), nullable=False),
            pa.field("high", pa.decimal128(20, 8), nullable=False),
            pa.field("low", pa.decimal128(20, 8), nullable=False),
            pa.field("close", pa.decimal128(20, 8), nullable=False),
            pa.field("volume", pa.int64(), nullable=False),
            pa.field("transactions", pa.int64(), nullable=False),
            pa.field("vwap", pa.decimal128(20, 8), nullable=True),
            pa.field("source", pa.string(), nullable=False),
            pa.field("dataset", pa.string(), nullable=False),
            pa.field("price_view", pa.string(), nullable=False),
            pa.field("source_artifact_sha256", pa.string(), nullable=False),
        ],
        metadata={
            b"source": request.source_name.encode("ascii"),
            b"dataset": f"us_stocks_sip/{request.dataset}".encode("ascii"),
            b"price_view": b"raw",
            b"adjusted": b"false",
            b"session_calendar": b"XNYS",
            b"session_scope": b"regular_hours",
            b"vendor_decision_sha256": (
                request.vendor_decision_sha256 or "not_required"
            ).encode("ascii"),
        },
    )
    table = pa.Table.from_pylist(
        [
            {
                "symbol": request.symbol,
                "event_time_utc": row.timestamp,
                "session_date": row.session_date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "transactions": row.transactions,
                "vwap": row.vwap,
                "source": request.source_name,
                "dataset": request.dataset,
                "price_view": request.price_view,
                "source_artifact_sha256": source_sha256,
            }
            for row in rows
        ],
        schema=schema,
    )
    temporary_path = path.with_name(f".{uuid4().hex[:8]}.tmp")
    try:
        pq.write_table(
            table,
            temporary_path,
            compression="zstd",
            version="2.6",
            write_statistics=True,
        )
        if path.exists():
            if _sha256_file(path) != _sha256_file(temporary_path):
                raise RuntimeError(f"immutable Parquet collision: {path}")
            return
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _record_ingestion_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    artifact_id: int,
    request: ResearchDataIngestRequest,
    status: str,
    parsed: _ParsedFile | None,
    findings: list[ResearchDataQualityFinding],
    partitions: list[ResearchDataPartition] | None = None,
) -> None:
    selected = sum(len(rows) for rows in parsed.rows_by_session.values()) if parsed else 0
    timestamp = _utc_iso()
    connection.execute(
        """
        INSERT INTO ingestion_runs(
            id, artifact_id, symbol, dataset, price_view, status, rows_scanned,
            symbol_rows_seen, rth_rows_selected, outside_rth_rows_excluded,
            started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            rows_scanned = excluded.rows_scanned,
            symbol_rows_seen = excluded.symbol_rows_seen,
            rth_rows_selected = excluded.rth_rows_selected,
            outside_rth_rows_excluded = excluded.outside_rth_rows_excluded,
            completed_at = excluded.completed_at
        """,
        (
            run_id,
            artifact_id,
            request.symbol,
            request.dataset,
            request.price_view,
            status,
            parsed.rows_scanned if parsed else 0,
            parsed.symbol_rows_seen if parsed else 0,
            selected,
            parsed.outside_rth_rows_excluded if parsed else 0,
            timestamp,
            timestamp,
        ),
    )
    partition_ids: dict[str, int] = {}
    for partition in partitions or []:
        row = connection.execute(
            """
            SELECT id FROM partitions
            WHERE symbol = ? AND dataset = ? AND price_view = ?
              AND session_date = ? AND revision = ?
            """,
            (
                request.symbol,
                request.dataset,
                request.price_view,
                partition.session_date,
                partition.revision,
            ),
        ).fetchone()
        if row is not None:
            partition_ids[partition.session_date] = int(row[0])
    for finding in findings:
        connection.execute(
            """
            INSERT INTO quality_findings(
                run_id, partition_id, severity, code, message, finding_count,
                session_date, samples_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                partition_ids.get(finding.session_date or ""),
                finding.severity,
                finding.code,
                finding.message,
                finding.count,
                finding.session_date,
                json.dumps(finding.samples),
            ),
        )


def _upsert_artifact(
    connection: sqlite3.Connection,
    request: ResearchDataIngestRequest,
    artifact: ResearchDataArtifact,
) -> int:
    connection.execute(
        """
        INSERT OR IGNORE INTO source_artifacts(
            source_name, dataset, original_path, stored_path, sha256, size_bytes, first_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request.source_name,
            request.dataset,
            artifact.source_path,
            artifact.stored_path,
            artifact.sha256,
            artifact.size_bytes,
            _utc_iso(),
        ),
    )
    row = connection.execute(
        "SELECT id FROM source_artifacts WHERE sha256 = ?",
        (artifact.sha256,),
    ).fetchone()
    if row is None:
        raise RuntimeError("source artifact was not recorded")
    return int(row[0])


def _archive_source_file(
    source_path: Path,
    *,
    root: Path,
    source_sha256: str,
    request: ResearchDataIngestRequest,
) -> Path:
    source_date = _date_from_filename(source_path.name)
    if source_date is None:
        destination_dir = (
            root
            / "raw"
            / request.source_name
            / "us_stocks_sip"
            / request.dataset
            / "unclassified"
        )
    else:
        destination_dir = (
            root
            / "raw"
            / request.source_name
            / "us_stocks_sip"
            / request.dataset
            / f"year={source_date.year:04d}"
            / f"month={source_date.month:02d}"
        )
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source_path.name
    if source_path == destination.resolve():
        return destination
    if destination.exists():
        if _sha256_file(destination) == source_sha256:
            return destination
        destination = destination.with_name(
            f"{_base_name(source_path.name)}-{source_sha256[:12]}{_combined_suffix(source_path)}"
        )
        if destination.exists():
            if _sha256_file(destination) != source_sha256:
                raise RuntimeError(f"immutable archive collision: {destination}")
            return destination
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with source_path.open("rb") as source, temporary.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if _sha256_file(temporary) != source_sha256:
            raise RuntimeError("archived source checksum does not match original")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _partition_path(
    root: Path,
    *,
    request: ResearchDataIngestRequest,
    session_date: date,
    revision: int,
    source_sha256: str,
) -> Path:
    return (
        root
        / "curated"
        / request.source_name
        / "us_stocks_sip"
        / request.dataset
        / f"price_view={request.price_view}"
        / f"symbol={request.symbol}"
        / f"year={session_date.year:04d}"
        / f"month={session_date.month:02d}"
        / f"session={session_date.isoformat()}"
        / f"revision={revision:04d}"
        / f"part-{source_sha256[:16]}.parquet"
    )


def _partition_from_row(row: sqlite3.Row) -> ResearchDataPartition:
    return ResearchDataPartition(
        session_date=str(row["session_date"]),
        revision=int(row["revision"]),
        active=bool(row["active"]),
        row_count=int(row["row_count"]),
        expected_row_count=int(row["expected_row_count"]),
        first_timestamp=_optional_datetime(row["first_timestamp"]),
        last_timestamp=_optional_datetime(row["last_timestamp"]),
        parquet_path=str(row["parquet_path"]),
        parquet_sha256=str(row["parquet_sha256"]),
        source_sha256=str(row["source_sha256"]),
        quality_status=ResearchDataQualityStatus(str(row["quality_status"])),
    )


def _missing_catalog_sessions(active_dates: list[str]) -> list[str]:
    if len(active_dates) < 2:
        return []
    calendar = xcals.get_calendar("XNYS")
    expected = {
        value.date().isoformat()
        for value in calendar.sessions_in_range(active_dates[0], active_dates[-1])
    }
    return sorted(expected - set(active_dates))


def _failed_ingest_report(
    request: ResearchDataIngestRequest,
    *,
    root: Path,
    catalog_path: Path,
    warnings: list[str],
    errors: list[str],
    findings: list[ResearchDataQualityFinding],
    artifact: ResearchDataArtifact | None = None,
    parsed: _ParsedFile | None = None,
) -> ResearchDataIngestReport:
    return ResearchDataIngestReport(
        ok=False,
        request=request,
        root_path=root.as_posix(),
        catalog_path=catalog_path.as_posix(),
        artifact=artifact,
        rows_scanned=parsed.rows_scanned if parsed else 0,
        symbol_rows_seen=parsed.symbol_rows_seen if parsed else 0,
        rth_rows_selected=(
            sum(len(rows) for rows in parsed.rows_by_session.values()) if parsed else 0
        ),
        outside_rth_rows_excluded=parsed.outside_rth_rows_excluded if parsed else 0,
        findings=findings,
        warnings=warnings,
        errors=errors,
        final_status="failed",
    )


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    count: int = 1,
    session_date: str | None = None,
    samples: list[str] | None = None,
) -> ResearchDataQualityFinding:
    return ResearchDataQualityFinding(
        severity=severity,
        code=code,
        message=message,
        count=count,
        session_date=session_date,
        samples=samples or [],
    )


@contextmanager
def _catalog_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def _open_csv_text(path: Path) -> Iterator[IO[str]]:
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, mode="rt", encoding="utf-8-sig", newline="") as stream:
            yield stream
        return
    with path.open(mode="rt", encoding="utf-8-sig", newline="") as stream:
        yield stream


def _read_json_payload(path: Path) -> dict[str, Any]:
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, mode="rt", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    else:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("JSON source must contain an object")
    return payload


def _price(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("price must be finite and positive")
    return parsed.quantize(_PRICE_QUANTUM)


def _whole_number(value: object, field_name: str) -> int:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise ValueError(f"{field_name} must be a finite whole number")
    return int(parsed)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_from_filename(name: str) -> date | None:
    match = _DATE_IN_FILENAME.search(name)
    if match is None:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def _combined_suffix(path: Path) -> str:
    return "".join(path.suffixes)


def _base_name(name: str) -> str:
    suffix = "".join(Path(name).suffixes)
    return name[: -len(suffix)] if suffix else name


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value)).astimezone(UTC)


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
