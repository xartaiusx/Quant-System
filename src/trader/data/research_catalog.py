"""Offline SPY catalog v2 imports, derived views, and broker-free loading."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from trader.data.research_store import (
    CATALOG_RELATIVE_PATH,
    ingest_massive_minute_file,
    initialize_research_store,
)
from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    ResearchCanonicalDailyIngestReport,
    ResearchCanonicalDailyIngestRequest,
    ResearchCatalogLoadReport,
    ResearchCatalogLoadRequest,
    ResearchCorporateAction,
    ResearchCorporateActionIngestReport,
    ResearchCorporateActionIngestRequest,
    ResearchDataArtifact,
    ResearchDataBatchImportItem,
    ResearchDataBatchImportReport,
    ResearchDataBatchImportRequest,
    ResearchDataIngestRequest,
    ResearchDataPartition,
    ResearchDataQualityStatus,
    ResearchDerivedPartition,
    ResearchDerivedViewReport,
    ResearchDerivedViewRequest,
    ResearchSampleKind,
)

_DAILY_COLUMNS = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
_ACTION_COLUMNS = {
    "symbol",
    "ex_date",
    "event_type",
    "factor",
    "cash_amount",
    "currency",
    "revision",
}
_ALLOWED_ACTIONS = {"split", "dividend"}
_PRICE_QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True)
class _DailyBar:
    session_date: date
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class _CatalogAction:
    action_type: str
    ex_date: date
    factor: Decimal | None
    cash_amount: Decimal | None
    currency: str | None
    revision: str


@dataclass(frozen=True)
class _RawPartitionRow:
    id: int
    dataset: str
    session_date: date
    parquet_path: Path
    parquet_sha256: str
    row_count: int
    expected_row_count: int


def ingest_canonical_daily_file(
    request: ResearchCanonicalDailyIngestRequest,
) -> ResearchCanonicalDailyIngestReport:
    """Archive and activate one complete canonical SPY daily export."""

    root = Path(request.root_path).expanduser().resolve()
    source_path = Path(request.source_path).expanduser().resolve()
    catalog_path = root / CATALOG_RELATIVE_PATH
    warnings = ["Offline licensed daily-data ingestion only; no broker contacted"]
    errors: list[str] = []
    artifact: ResearchDataArtifact | None = None
    try:
        catalog_path = initialize_research_store(root)
        artifact, artifact_id = _archive_artifact(
            source_path,
            root=root,
            source_name=request.source_name,
            dataset=request.dataset,
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        return ResearchCanonicalDailyIngestReport(
            ok=False,
            request=request,
            root_path=root.as_posix(),
            catalog_path=catalog_path.as_posix(),
            artifact=artifact,
            errors=[f"daily source could not be archived: {exc}"],
            warnings=warnings,
            final_status="failed",
        )

    try:
        bars = _parse_daily_file(source_path)
        missing_sessions = _missing_daily_sessions(bars)
        if missing_sessions:
            errors.append(
                f"daily source is missing {len(missing_sessions)} XNYS sessions"
            )
        with _catalog_connection(catalog_path) as connection:
            existing = _daily_partitions_for_artifact(
                connection,
                artifact_id=artifact_id,
                request=request,
            )
            if existing and len(existing) == len(bars) and not errors:
                return ResearchCanonicalDailyIngestReport(
                    ok=True,
                    request=request,
                    root_path=root.as_posix(),
                    catalog_path=catalog_path.as_posix(),
                    artifact=artifact,
                    rows_scanned=len(bars),
                    partitions=existing,
                    idempotent_replay=True,
                    warnings=warnings,
                    final_status="unchanged",
                )
            run_id = uuid4().hex
            if errors:
                _record_generic_ingestion_run(
                    connection,
                    run_id=run_id,
                    artifact_id=artifact_id,
                    request=request,
                    status="failed",
                    row_count=len(bars),
                )
                return ResearchCanonicalDailyIngestReport(
                    ok=False,
                    request=request,
                    root_path=root.as_posix(),
                    catalog_path=catalog_path.as_posix(),
                    artifact=artifact,
                    rows_scanned=len(bars),
                    missing_session_dates=missing_sessions,
                    warnings=warnings,
                    errors=errors,
                    final_status="failed",
                )
            _record_generic_ingestion_run(
                connection,
                run_id=run_id,
                artifact_id=artifact_id,
                request=request,
                status="completed",
                row_count=len(bars),
            )
            partitions = _activate_daily_partitions(
                connection,
                root=root,
                request=request,
                artifact=artifact,
                artifact_id=artifact_id,
                run_id=run_id,
                bars=bars,
            )
        return ResearchCanonicalDailyIngestReport(
            ok=True,
            request=request,
            root_path=root.as_posix(),
            catalog_path=catalog_path.as_posix(),
            artifact=artifact,
            rows_scanned=len(bars),
            partitions=partitions,
            warnings=warnings,
            final_status="completed",
        )
    except (OSError, ValueError, csv.Error, sqlite3.Error, RuntimeError) as exc:
        return ResearchCanonicalDailyIngestReport(
            ok=False,
            request=request,
            root_path=root.as_posix(),
            catalog_path=catalog_path.as_posix(),
            artifact=artifact,
            warnings=warnings,
            errors=[f"daily source failed validation: {exc}"],
            final_status="failed",
        )


def ingest_corporate_action_file(
    request: ResearchCorporateActionIngestRequest,
) -> ResearchCorporateActionIngestReport:
    """Archive and activate one complete canonical corporate-action set."""

    root = Path(request.root_path).expanduser().resolve()
    source_path = Path(request.source_path).expanduser().resolve()
    catalog_path = root / CATALOG_RELATIVE_PATH
    warnings = ["Offline corporate-action ingestion only; no broker contacted"]
    artifact: ResearchDataArtifact | None = None
    try:
        catalog_path = initialize_research_store(root)
        artifact, artifact_id = _archive_artifact(
            source_path,
            root=root,
            source_name=request.source_name,
            dataset=request.dataset,
        )
        actions = _parse_action_file(source_path, request)
        with _catalog_connection(catalog_path) as connection:
            existing = connection.execute(
                """
                SELECT id FROM action_sets
                WHERE source_sha256 = ? AND symbol = ? AND active = 1
                """,
                (artifact.sha256, request.symbol),
            ).fetchone()
            if existing is not None:
                return ResearchCorporateActionIngestReport(
                    ok=True,
                    request=request,
                    root_path=root.as_posix(),
                    catalog_path=catalog_path.as_posix(),
                    artifact=artifact,
                    action_set_id=str(existing["id"]),
                    actions=[_action_model(item) for item in actions],
                    idempotent_replay=True,
                    warnings=warnings,
                    final_status="unchanged",
                )
            action_set_id = f"actions-{uuid4().hex}"
            _supersede_action_sets(connection, request)
            connection.execute(
                """
                INSERT INTO action_sets(
                    id, artifact_id, source_name, dataset, symbol, coverage_start,
                    coverage_end, complete, active, source_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (
                    action_set_id,
                    artifact_id,
                    request.source_name,
                    request.dataset,
                    request.symbol,
                    request.coverage_start,
                    request.coverage_end,
                    artifact.sha256,
                    _utc_iso(),
                ),
            )
            for action in actions:
                connection.execute(
                    """
                    INSERT INTO corporate_actions(
                        action_set_id, symbol, action_type, ex_date, factor,
                        cash_amount, currency, revision, active, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        action_set_id,
                        request.symbol,
                        action.action_type,
                        action.ex_date.isoformat(),
                        str(action.factor) if action.factor is not None else None,
                        (
                            str(action.cash_amount)
                            if action.cash_amount is not None
                            else None
                        ),
                        action.currency,
                        action.revision,
                        _utc_iso(),
                    ),
                )
        return ResearchCorporateActionIngestReport(
            ok=True,
            request=request,
            root_path=root.as_posix(),
            catalog_path=catalog_path.as_posix(),
            artifact=artifact,
            action_set_id=action_set_id,
            actions=[_action_model(item) for item in actions],
            warnings=warnings,
            final_status="completed",
        )
    except (OSError, ValueError, csv.Error, sqlite3.Error, RuntimeError) as exc:
        return ResearchCorporateActionIngestReport(
            ok=False,
            request=request,
            root_path=root.as_posix(),
            catalog_path=catalog_path.as_posix(),
            artifact=artifact,
            warnings=warnings,
            errors=[f"corporate-action source failed validation: {exc}"],
            final_status="failed",
        )


def import_research_data_batch(
    request: ResearchDataBatchImportRequest,
) -> ResearchDataBatchImportReport:
    """Import sorted local files without downloading or reading credentials."""

    source_dir = Path(request.source_dir).expanduser().resolve()
    errors: list[str] = []
    warnings = ["Batch import is offline and reads local licensed files only"]
    if not source_dir.is_dir():
        errors.append(f"source directory not found: {source_dir.as_posix()}")
        paths: list[Path] = []
    else:
        paths = sorted(
            path.resolve() for path in source_dir.glob(request.pattern) if path.is_file()
        )
        if any(not path.is_relative_to(source_dir) for path in paths):
            errors.append("batch import pattern resolved outside source directory")
            paths = []
        if not paths:
            errors.append("batch import found no matching local files")

    items: list[ResearchDataBatchImportItem] = []
    for path in paths:
        item = _import_batch_item(request, path)
        items.append(item)
        errors.extend(item.errors)
        warnings.extend(item.warnings)
    failed_count = sum(1 for item in items if not item.ok)
    succeeded_count = sum(1 for item in items if item.ok)
    ok = bool(items) and not errors and failed_count == 0
    return ResearchDataBatchImportReport(
        ok=ok,
        request=request,
        source_files=[path.as_posix() for path in paths],
        items=items,
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        warnings=_unique(warnings),
        errors=_unique(errors),
        final_status="completed" if ok else "failed",
    )


def derive_research_views(
    request: ResearchDerivedViewRequest,
) -> ResearchDerivedViewReport:
    """Derive source-hashed raw execution, adjusted signal, and benchmark views."""

    root = Path(request.root_path).expanduser().resolve()
    catalog_path = root / CATALOG_RELATIVE_PATH
    warnings = ["Derived research views are offline, broker-free, and non-promoting"]
    errors: list[str] = []
    partitions: list[ResearchDerivedPartition] = []
    stale_superseded = 0
    idempotent_count = 0
    action_fingerprint: str | None = None
    try:
        catalog_path = initialize_research_store(root)
        with _catalog_connection(catalog_path) as connection:
            minute_parents = _active_raw_partitions(
                connection,
                dataset="minute_aggs_v1",
            )
            daily_parents = _active_raw_partitions(
                connection,
                dataset="daily_bars_v1",
            )
            all_parents = [*minute_parents, *daily_parents]
            if not minute_parents:
                errors.append("no active raw Massive SPY minute partitions found")
            if not daily_parents:
                warnings.append("no active raw SPY daily partitions found; benchmark not derived")
            if all_parents:
                coverage_start = min(item.session_date for item in all_parents)
                coverage_end = max(item.session_date for item in all_parents)
                actions, action_fingerprint = _active_actions(
                    connection,
                    coverage_start=coverage_start,
                    coverage_end=coverage_end,
                )
            else:
                actions = []
                errors.append("no active raw SPY catalog partitions found")
            if not errors and action_fingerprint is not None:
                for parent in minute_parents:
                    raw_rows = _read_parent_rows(parent)
                    _validate_minute_parent(parent, raw_rows)
                    for price_view in ("raw_execution", "split_adjusted_signal"):
                        derived_rows = _derive_five_minute_rows(
                            raw_rows,
                            session_date=parent.session_date,
                            actions=actions,
                            adjusted=price_view == "split_adjusted_signal",
                        )
                        result, stale, unchanged = _activate_derived_partition(
                            connection,
                            root=root,
                            request=request,
                            dataset="spy_5m_v1",
                            price_view=price_view,
                            bar_size="5 mins",
                            session_date=parent.session_date,
                            rows=derived_rows,
                            expected_row_count=parent.expected_row_count // 5,
                            parents=[parent],
                            action_fingerprint=action_fingerprint,
                        )
                        partitions.append(result)
                        stale_superseded += stale
                        idempotent_count += int(unchanged)
                if daily_parents:
                    benchmark_results, stale, benchmark_unchanged = _derive_daily_benchmark(
                        connection,
                        root=root,
                        request=request,
                        parents=daily_parents,
                        actions=actions,
                        action_fingerprint=action_fingerprint,
                    )
                    partitions.extend(benchmark_results)
                    stale_superseded += stale
                    idempotent_count += benchmark_unchanged
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        errors.append(f"derived view generation failed: {exc}")
    ok = bool(partitions) and not errors
    return ResearchDerivedViewReport(
        ok=ok,
        request=request,
        root_path=root.as_posix(),
        catalog_path=catalog_path.as_posix(),
        action_fingerprint=action_fingerprint,
        partitions=partitions,
        stale_partitions_superseded=stale_superseded,
        idempotent_partition_count=idempotent_count,
        warnings=_unique(warnings),
        errors=_unique(errors),
        final_status="completed" if ok else "failed",
    )


def load_research_catalog(
    request: ResearchCatalogLoadRequest,
) -> ResearchCatalogLoadReport:
    """Load non-sealed active, checksum-valid derived SPY partitions."""

    return _load_research_catalog(request, final_holdout_access=None)


def load_research_catalog_for_final_holdout(
    request: ResearchCatalogLoadRequest,
    *,
    experiment_id: str,
    holdout_access_fingerprint: str,
) -> ResearchCatalogLoadReport:
    """Load one consumed final holdout through a catalog-verified capability."""

    return _load_research_catalog(
        request,
        final_holdout_access=(experiment_id, holdout_access_fingerprint),
    )


def _load_research_catalog(
    request: ResearchCatalogLoadRequest,
    *,
    final_holdout_access: tuple[str, str] | None,
) -> ResearchCatalogLoadReport:
    """Load active derived partitions while enforcing permanent holdout seals."""

    root = Path(request.root_path).expanduser().resolve()
    catalog_path = root / CATALOG_RELATIVE_PATH
    warnings = ["Research catalog load is offline and broker-free"]
    errors: list[str] = []
    partitions: list[ResearchDerivedPartition] = []
    corporate_actions: list[ResearchCorporateAction] = []
    action_fingerprint: str | None = None
    bars: list[BacktestBar] = []
    try:
        if not catalog_path.is_file():
            raise ValueError(f"research catalog not found: {catalog_path.as_posix()}")
        with _catalog_connection(catalog_path) as connection:
            rows = _active_derived_rows(connection, request)
            if not rows:
                errors.append("no matching active derived SPY partitions found")
            else:
                errors.extend(_derived_coverage_errors(rows, request))
                coverage_start = date.fromisoformat(str(rows[0]["session_date"]))
                coverage_end = date.fromisoformat(str(rows[-1]["session_date"]))
                errors.extend(
                    _sealed_period_errors(
                        connection,
                        symbol=request.symbol,
                        coverage_start=coverage_start,
                        coverage_end=coverage_end,
                        requested_start=request.start_date,
                        requested_end=request.end_date,
                        final_holdout_access=final_holdout_access,
                    )
                )
                actions, action_fingerprint = _active_actions(
                    connection,
                    coverage_start=coverage_start,
                    coverage_end=coverage_end,
                )
                corporate_actions = [_action_model(action) for action in actions]
                algorithm_versions = {str(row["algorithm_version"]) for row in rows}
                if len(algorithm_versions) != 1:
                    errors.append("derived catalog selection contains algorithm-version drift")
                if request.price_view == "total_return_benchmark":
                    errors.extend(
                        _benchmark_chain_errors(
                            connection,
                            rows,
                            action_fingerprint=action_fingerprint,
                        )
                    )
            for row in rows if not errors else []:
                partition = _derived_partition_from_row(connection, row)
                if partition.action_fingerprint != action_fingerprint:
                    errors.append(
                        f"derived action fingerprint is stale: {partition.session_date}"
                    )
                    continue
                partition_path = Path(partition.parquet_path).resolve()
                if not partition_path.is_file():
                    errors.append(
                        f"derived partition missing: {partition.session_date}"
                    )
                    continue
                if _sha256(partition_path) != partition.parquet_sha256:
                    errors.append(
                        f"derived partition checksum mismatch: {partition.session_date}"
                    )
                    continue
                lineage_errors = _derived_lineage_errors(connection, row)
                if lineage_errors:
                    errors.extend(lineage_errors)
                    continue
                loaded = _load_derived_bars(
                    partition_path,
                    request.symbol,
                    price_view=partition.price_view,
                )
                if len(loaded) != partition.row_count:
                    errors.append(
                        f"derived partition row mismatch: {partition.session_date}"
                    )
                    continue
                if partition.row_count != partition.expected_row_count:
                    errors.append(
                        f"derived partition is incomplete: {partition.session_date}"
                    )
                    continue
                partitions.append(partition)
                bars.extend(loaded)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        errors.append(f"research catalog load failed: {exc}")

    timestamps = [bar.timestamp for bar in bars]
    if timestamps != sorted(timestamps):
        errors.append("loaded derived bars are not chronological")
    if len(timestamps) != len(set(timestamps)):
        errors.append("loaded derived bars contain duplicate timestamps")
    feed = _feed_from_bars(bars) if bars and not errors else None
    dataset_fingerprint = _bars_fingerprint(bars) if feed is not None else None
    return ResearchCatalogLoadReport(
        ok=feed is not None and not errors,
        request=request,
        catalog_path=catalog_path.as_posix(),
        partitions=partitions,
        corporate_actions=corporate_actions,
        action_fingerprint=action_fingerprint,
        feed=feed,
        dataset_fingerprint=dataset_fingerprint,
        warnings=_unique(warnings),
        errors=_unique(errors),
        final_status="loaded" if feed is not None and not errors else "failed",
    )


def _sealed_period_errors(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    coverage_start: date,
    coverage_end: date,
    requested_start: str | None,
    requested_end: str | None,
    final_holdout_access: tuple[str, str] | None,
) -> list[str]:
    rows = connection.execute(
        """
        SELECT
            sealed_periods.experiment_id,
            sealed_periods.start_date,
            sealed_periods.end_date,
            experiment_specs.status
        FROM sealed_periods
        JOIN experiment_specs
          ON experiment_specs.experiment_id = sealed_periods.experiment_id
        WHERE sealed_periods.symbol = ?
          AND sealed_periods.start_date <= ?
          AND sealed_periods.end_date >= ?
        ORDER BY sealed_periods.start_date, sealed_periods.experiment_id
        """,
        (symbol, coverage_end.isoformat(), coverage_start.isoformat()),
    ).fetchall()
    if not rows:
        return []
    if final_holdout_access is None:
        periods = ", ".join(
            f"{row['experiment_id']}:{row['start_date']}..{row['end_date']}"
            for row in rows
        )
        return [f"research catalog request overlaps permanently sealed holdout: {periods}"]

    experiment_id, access_fingerprint = final_holdout_access
    authorized = next(
        (
            row
            for row in rows
            if str(row["experiment_id"]) == experiment_id
            and str(row["start_date"]) == requested_start
            and str(row["end_date"]) == requested_end
            and str(row["status"]) == "active"
        ),
        None,
    )
    if authorized is None:
        return ["final-holdout capability does not match an active exact catalog seal"]
    access = connection.execute(
        """
        SELECT 1 FROM holdout_access
        WHERE experiment_id = ? AND holdout_fingerprint = ?
        """,
        (experiment_id, access_fingerprint),
    ).fetchone()
    if access is None:
        return ["final-holdout capability was not recorded before catalog access"]
    return []


def _import_batch_item(
    request: ResearchDataBatchImportRequest,
    path: Path,
) -> ResearchDataBatchImportItem:
    kind = str(request.kind)
    if kind == ResearchSampleKind.MINUTE_BARS:
        report = ingest_massive_minute_file(
            ResearchDataIngestRequest(
                source_path=path.as_posix(),
                root_path=request.root_path,
            )
        )
        return ResearchDataBatchImportItem(
            source_path=path.as_posix(),
            report_type=report.report_type,
            ok=report.ok,
            final_status=report.final_status,
            partition_count=len(report.partitions),
            idempotent_replay=report.idempotent_replay,
            warnings=report.warnings,
            errors=report.errors,
        )
    if kind == ResearchSampleKind.DAILY_BARS:
        daily = ingest_canonical_daily_file(
            ResearchCanonicalDailyIngestRequest(
                source_path=path.as_posix(),
                root_path=request.root_path,
                source_name=request.vendor,
            )
        )
        return ResearchDataBatchImportItem(
            source_path=path.as_posix(),
            report_type=daily.report_type,
            ok=daily.ok,
            final_status=daily.final_status,
            partition_count=len(daily.partitions),
            idempotent_replay=daily.idempotent_replay,
            warnings=daily.warnings,
            errors=daily.errors,
        )
    actions = ingest_corporate_action_file(
        ResearchCorporateActionIngestRequest(
            source_path=path.as_posix(),
            root_path=request.root_path,
            source_name=request.vendor,
            coverage_start=request.coverage_start or "",
            coverage_end=request.coverage_end or "",
        )
    )
    return ResearchDataBatchImportItem(
        source_path=path.as_posix(),
        report_type=actions.report_type,
        ok=actions.ok,
        final_status=actions.final_status,
        action_count=len(actions.actions),
        idempotent_replay=actions.idempotent_replay,
        warnings=actions.warnings,
        errors=actions.errors,
    )


def _parse_daily_file(path: Path) -> list[_DailyBar]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_columns(set(reader.fieldnames or []), _DAILY_COLUMNS)
        bars: list[_DailyBar] = []
        for row in reader:
            if str(row.get("symbol", "")).strip().upper() != "SPY":
                continue
            timestamp = _parse_timestamp(str(row["timestamp"]))
            bar = _DailyBar(
                session_date=timestamp.date(),
                timestamp=timestamp,
                open=_decimal(row["open"]),
                high=_decimal(row["high"]),
                low=_decimal(row["low"]),
                close=_decimal(row["close"]),
                volume=_decimal(row["volume"]),
            )
            _validate_ohlcv(bar)
            bars.append(bar)
    if not bars:
        raise ValueError("canonical daily source contains no SPY rows")
    dates = [bar.session_date for bar in bars]
    if dates != sorted(dates):
        raise ValueError("canonical daily rows are not chronological")
    if len(dates) != len(set(dates)):
        raise ValueError("canonical daily rows contain duplicate sessions")
    calendar = xcals.get_calendar("XNYS")
    invalid = [value for value in dates if not calendar.is_session(value)]
    if invalid:
        raise ValueError(f"daily rows contain non-XNYS sessions: {invalid[0]}")
    return bars


def _parse_action_file(
    path: Path,
    request: ResearchCorporateActionIngestRequest,
) -> list[_CatalogAction]:
    coverage_start = date.fromisoformat(request.coverage_start)
    coverage_end = date.fromisoformat(request.coverage_end)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_columns(set(reader.fieldnames or []), _ACTION_COLUMNS)
        actions: list[_CatalogAction] = []
        for row in reader:
            if str(row.get("symbol", "")).strip().upper() != "SPY":
                continue
            action_type = str(row["event_type"]).strip().lower()
            if action_type not in _ALLOWED_ACTIONS:
                raise ValueError(f"unsupported corporate action type: {action_type}")
            ex_date = date.fromisoformat(str(row["ex_date"]).strip())
            if ex_date < coverage_start or ex_date > coverage_end:
                raise ValueError(f"corporate action outside declared coverage: {ex_date}")
            factor = _optional_decimal(row.get("factor"))
            cash_amount = _optional_decimal(row.get("cash_amount"))
            if action_type == "split" and (
                factor is None or factor <= 0 or factor == Decimal("1")
            ):
                raise ValueError("split action requires a positive non-unit factor")
            if action_type == "dividend" and (
                cash_amount is None or cash_amount <= 0
            ):
                raise ValueError("dividend action requires a positive cash amount")
            revision = str(row["revision"]).strip()
            if not revision:
                raise ValueError("corporate action revision is required")
            actions.append(
                _CatalogAction(
                    action_type=action_type,
                    ex_date=ex_date,
                    factor=factor,
                    cash_amount=cash_amount,
                    currency=str(row.get("currency", "")).strip().upper() or None,
                    revision=revision,
                )
            )
    keys = [(item.action_type, item.ex_date) for item in actions]
    if len(keys) != len(set(keys)):
        raise ValueError("corporate action source contains duplicate events")
    return sorted(actions, key=lambda item: (item.ex_date, item.action_type, item.revision))


def _missing_daily_sessions(bars: list[_DailyBar]) -> list[str]:
    expected = {
        item.date()
        for item in xcals.get_calendar("XNYS").sessions_in_range(
            bars[0].session_date,
            bars[-1].session_date,
        )
    }
    observed = {bar.session_date for bar in bars}
    return sorted(item.isoformat() for item in expected - observed)


def _archive_artifact(
    source_path: Path,
    *,
    root: Path,
    source_name: str,
    dataset: str,
) -> tuple[ResearchDataArtifact, int]:
    if not source_path.is_file():
        raise ValueError(f"source file not found: {source_path.as_posix()}")
    source_sha256 = _sha256(source_path)
    target_dir = root / "raw" / source_name.strip().lower() / dataset.strip().lower()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source_path.name
    if target.exists() and _sha256(target) != source_sha256:
        target = target.with_name(f"{target.stem}-{source_sha256[:12]}{target.suffix}")
    if not target.exists():
        shutil.copy2(source_path, target)
    if _sha256(target) != source_sha256:
        raise RuntimeError("archived research artifact checksum mismatch")
    catalog_path = root / CATALOG_RELATIVE_PATH
    with _catalog_connection(catalog_path) as connection:
        row = connection.execute(
            """
            SELECT id, source_name, dataset, stored_path, size_bytes
            FROM source_artifacts
            WHERE sha256 = ?
            """,
            (source_sha256,),
        ).fetchone()
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO source_artifacts(
                    source_name, dataset, original_path, stored_path, sha256,
                    size_bytes, first_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_name,
                    dataset,
                    source_path.as_posix(),
                    target.as_posix(),
                    source_sha256,
                    source_path.stat().st_size,
                    _utc_iso(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("research artifact insert returned no id")
            artifact_id = int(cursor.lastrowid)
        else:
            if str(row["source_name"]).lower() != source_name.lower() or str(
                row["dataset"]
            ).lower() != dataset.lower():
                raise ValueError("artifact checksum already belongs to another dataset")
            artifact_id = int(row["id"])
            target = Path(str(row["stored_path"]))
    artifact = ResearchDataArtifact(
        source_path=source_path.as_posix(),
        stored_path=target.as_posix(),
        sha256=source_sha256,
        size_bytes=source_path.stat().st_size,
    )
    return artifact, artifact_id


def _daily_partitions_for_artifact(
    connection: sqlite3.Connection,
    *,
    artifact_id: int,
    request: ResearchCanonicalDailyIngestRequest,
) -> list[ResearchDataPartition]:
    rows = connection.execute(
        """
        SELECT p.*, a.sha256 AS source_sha256
        FROM partitions AS p
        JOIN source_artifacts AS a ON a.id = p.artifact_id
        WHERE p.artifact_id = ? AND p.symbol = ? AND p.dataset = ?
          AND p.price_view = ?
        ORDER BY p.session_date
        """,
        (artifact_id, request.symbol, request.dataset, request.price_view),
    ).fetchall()
    return [_research_partition_from_row(row) for row in rows]


def _activate_daily_partitions(
    connection: sqlite3.Connection,
    *,
    root: Path,
    request: ResearchCanonicalDailyIngestRequest,
    artifact: ResearchDataArtifact,
    artifact_id: int,
    run_id: str,
    bars: list[_DailyBar],
) -> list[ResearchDataPartition]:
    results: list[ResearchDataPartition] = []
    for bar in bars:
        session_text = bar.session_date.isoformat()
        revision = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(revision), 0) FROM partitions
                WHERE symbol = ? AND dataset = ? AND price_view = ? AND session_date = ?
                """,
                (request.symbol, request.dataset, request.price_view, session_text),
            ).fetchone()[0]
        ) + 1
        connection.execute(
            """
            UPDATE partitions SET active = 0
            WHERE symbol = ? AND dataset = ? AND price_view = ? AND session_date = ?
            """,
            (request.symbol, request.dataset, request.price_view, session_text),
        )
        parquet_path = (
            root
            / "curated"
            / request.source_name.lower()
            / request.dataset
            / "price_view=raw"
            / "symbol=SPY"
            / f"year={bar.session_date.year:04d}"
            / f"month={bar.session_date.month:02d}"
            / f"session={session_text}"
            / f"part-r{revision:04d}-{artifact.sha256[:12]}.parquet"
        )
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        _write_daily_partition(parquet_path, bar, request, artifact.sha256)
        parquet_sha256 = _sha256(parquet_path)
        connection.execute(
            """
            INSERT INTO partitions(
                artifact_id, run_id, symbol, dataset, price_view, session_date,
                revision, active, row_count, expected_row_count, first_timestamp,
                last_timestamp, parquet_path, parquet_sha256, quality_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                run_id,
                request.symbol,
                request.dataset,
                request.price_view,
                session_text,
                revision,
                bar.timestamp.isoformat(),
                bar.timestamp.isoformat(),
                parquet_path.as_posix(),
                parquet_sha256,
                ResearchDataQualityStatus.PASSED.value,
                _utc_iso(),
            ),
        )
        results.append(
            ResearchDataPartition(
                session_date=session_text,
                revision=revision,
                row_count=1,
                expected_row_count=1,
                first_timestamp=bar.timestamp,
                last_timestamp=bar.timestamp,
                parquet_path=parquet_path.as_posix(),
                parquet_sha256=parquet_sha256,
                source_sha256=artifact.sha256,
                quality_status=ResearchDataQualityStatus.PASSED,
            )
        )
    return results


def _write_daily_partition(
    path: Path,
    bar: _DailyBar,
    request: ResearchCanonicalDailyIngestRequest,
    source_sha256: str,
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
            pa.field("volume", pa.decimal128(24, 4), nullable=False),
            pa.field("source", pa.string(), nullable=False),
            pa.field("dataset", pa.string(), nullable=False),
            pa.field("price_view", pa.string(), nullable=False),
            pa.field("source_artifact_sha256", pa.string(), nullable=False),
        ],
        metadata={
            b"session_calendar": b"XNYS",
            b"session_scope": b"regular_hours",
            b"adjusted": b"false",
        },
    )
    table = pa.Table.from_pylist(
        [
            {
                "symbol": request.symbol,
                "event_time_utc": bar.timestamp,
                "session_date": bar.session_date,
                "open": bar.open.quantize(_PRICE_QUANTUM),
                "high": bar.high.quantize(_PRICE_QUANTUM),
                "low": bar.low.quantize(_PRICE_QUANTUM),
                "close": bar.close.quantize(_PRICE_QUANTUM),
                "volume": bar.volume.quantize(Decimal("0.0001")),
                "source": request.source_name,
                "dataset": request.dataset,
                "price_view": request.price_view,
                "source_artifact_sha256": source_sha256,
            }
        ],
        schema=schema,
    )
    _write_immutable_parquet(path, table)


def _record_generic_ingestion_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    artifact_id: int,
    request: ResearchCanonicalDailyIngestRequest,
    status: str,
    row_count: int,
) -> None:
    now = _utc_iso()
    connection.execute(
        """
        INSERT INTO ingestion_runs(
            id, artifact_id, symbol, dataset, price_view, status, rows_scanned,
            symbol_rows_seen, rth_rows_selected, outside_rth_rows_excluded,
            started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            run_id,
            artifact_id,
            request.symbol,
            request.dataset,
            request.price_view,
            status,
            row_count,
            row_count,
            row_count,
            now,
            now,
        ),
    )


def _supersede_action_sets(
    connection: sqlite3.Connection,
    request: ResearchCorporateActionIngestRequest,
) -> None:
    rows = connection.execute(
        """
        SELECT id FROM action_sets
        WHERE symbol = ? AND active = 1
          AND coverage_start <= ? AND coverage_end >= ?
        """,
        (request.symbol, request.coverage_end, request.coverage_start),
    ).fetchall()
    ids = [str(row["id"]) for row in rows]
    for action_set_id in ids:
        connection.execute("UPDATE action_sets SET active = 0 WHERE id = ?", (action_set_id,))
        connection.execute(
            "UPDATE corporate_actions SET active = 0 WHERE action_set_id = ?",
            (action_set_id,),
        )


def _action_model(action: _CatalogAction) -> ResearchCorporateAction:
    return ResearchCorporateAction(
        action_type=action.action_type,
        ex_date=action.ex_date.isoformat(),
        factor=action.factor,
        cash_amount=action.cash_amount,
        currency=action.currency,
        revision=action.revision,
    )


def _active_raw_partitions(
    connection: sqlite3.Connection,
    *,
    dataset: str,
) -> list[_RawPartitionRow]:
    rows = connection.execute(
        """
        SELECT id, dataset, session_date, parquet_path, parquet_sha256,
               row_count, expected_row_count
        FROM partitions
        WHERE symbol = 'SPY' AND dataset = ? AND price_view = 'raw' AND active = 1
          AND quality_status = 'passed'
        ORDER BY session_date
        """,
        (dataset,),
    ).fetchall()
    return [
        _RawPartitionRow(
            id=int(row["id"]),
            dataset=str(row["dataset"]),
            session_date=date.fromisoformat(str(row["session_date"])),
            parquet_path=Path(str(row["parquet_path"])).resolve(),
            parquet_sha256=str(row["parquet_sha256"]),
            row_count=int(row["row_count"]),
            expected_row_count=int(row["expected_row_count"]),
        )
        for row in rows
    ]


def _active_actions(
    connection: sqlite3.Connection,
    *,
    coverage_start: date,
    coverage_end: date,
) -> tuple[list[_CatalogAction], str]:
    sets = connection.execute(
        """
        SELECT id, source_sha256 FROM action_sets
        WHERE symbol = 'SPY' AND complete = 1 AND active = 1
          AND coverage_start <= ? AND coverage_end >= ?
        ORDER BY created_at DESC
        """,
        (coverage_start.isoformat(), coverage_end.isoformat()),
    ).fetchall()
    if len(sets) != 1:
        raise ValueError(
            "derived views require exactly one active complete corporate-action set "
            "covering all parent sessions"
        )
    action_set_id = str(sets[0]["id"])
    rows = connection.execute(
        """
        SELECT action_type, ex_date, factor, cash_amount, currency, revision
        FROM corporate_actions
        WHERE action_set_id = ? AND symbol = 'SPY' AND active = 1
        ORDER BY ex_date, action_type, revision
        """,
        (action_set_id,),
    ).fetchall()
    actions = [
        _CatalogAction(
            action_type=str(row["action_type"]),
            ex_date=date.fromisoformat(str(row["ex_date"])),
            factor=_optional_decimal(row["factor"]),
            cash_amount=_optional_decimal(row["cash_amount"]),
            currency=str(row["currency"]) if row["currency"] else None,
            revision=str(row["revision"]),
        )
        for row in rows
    ]
    payload = {
        "action_set_source_sha256": str(sets[0]["source_sha256"]),
        "actions": [
            {
                "action_type": item.action_type,
                "cash_amount": str(item.cash_amount) if item.cash_amount is not None else None,
                "currency": item.currency,
                "ex_date": item.ex_date.isoformat(),
                "factor": str(item.factor) if item.factor is not None else None,
                "revision": item.revision,
            }
            for item in actions
        ],
    }
    return actions, _fingerprint(payload)


def _read_parent_rows(parent: _RawPartitionRow) -> list[dict[str, Any]]:
    if not parent.parquet_path.is_file():
        raise ValueError(f"raw parent missing: {parent.session_date}")
    if _sha256(parent.parquet_path) != parent.parquet_sha256:
        raise ValueError(f"raw parent checksum mismatch: {parent.session_date}")
    return cast(list[dict[str, Any]], pq.read_table(parent.parquet_path).to_pylist())


def _validate_minute_parent(
    parent: _RawPartitionRow,
    rows: list[dict[str, Any]],
) -> None:
    if len(rows) != parent.row_count or parent.row_count != parent.expected_row_count:
        raise ValueError(f"raw parent row count is incomplete: {parent.session_date}")
    if parent.expected_row_count not in {210, 390}:
        raise ValueError(f"unexpected XNYS minute count: {parent.session_date}")
    timestamps = [_as_datetime(row["event_time_utc"]) for row in rows]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise ValueError(f"raw parent timestamps are invalid: {parent.session_date}")
    if any(
        right - left != timedelta(minutes=1)
        for left, right in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise ValueError(f"raw parent minute sequence is incomplete: {parent.session_date}")


def _derive_five_minute_rows(
    rows: list[dict[str, Any]],
    *,
    session_date: date,
    actions: list[_CatalogAction],
    adjusted: bool,
) -> list[dict[str, Any]]:
    if len(rows) % 5:
        raise ValueError(f"incomplete five-minute groups: {session_date}")
    split_product = Decimal("1")
    if adjusted:
        for action in actions:
            if action.action_type == "split" and action.ex_date > session_date:
                assert action.factor is not None
                split_product *= action.factor
    price_factor = Decimal("1") / split_product
    volume_factor = split_product
    derived: list[dict[str, Any]] = []
    for offset in range(0, len(rows), 5):
        group = rows[offset : offset + 5]
        timestamps = [_as_datetime(item["event_time_utc"]) for item in group]
        if any(
            right - left != timedelta(minutes=1)
            for left, right in zip(timestamps, timestamps[1:], strict=False)
        ):
            raise ValueError(f"incomplete five-minute group: {timestamps[0].isoformat()}")
        derived.append(
            {
                "symbol": "SPY",
                "event_time_utc": timestamps[0],
                "session_date": session_date,
                "open": (_decimal(group[0]["open"]) * price_factor).quantize(
                    _PRICE_QUANTUM
                ),
                "high": (
                    max(_decimal(item["high"]) for item in group) * price_factor
                ).quantize(_PRICE_QUANTUM),
                "low": (
                    min(_decimal(item["low"]) for item in group) * price_factor
                ).quantize(_PRICE_QUANTUM),
                "close": (_decimal(group[-1]["close"]) * price_factor).quantize(
                    _PRICE_QUANTUM
                ),
                "volume": int(
                    sum(Decimal(str(item["volume"])) for item in group)
                    * volume_factor
                ),
            }
        )
    return derived


def _derive_daily_benchmark(
    connection: sqlite3.Connection,
    *,
    root: Path,
    request: ResearchDerivedViewRequest,
    parents: list[_RawPartitionRow],
    actions: list[_CatalogAction],
    action_fingerprint: str,
) -> tuple[list[ResearchDerivedPartition], int, int]:
    shares = Decimal("1")
    initial_value: Decimal | None = None
    chain_fingerprint = _benchmark_chain_seed(
        action_fingerprint=action_fingerprint,
        algorithm_version=request.algorithm_version,
    )
    results: list[ResearchDerivedPartition] = []
    stale_count = 0
    unchanged_count = 0
    actions_by_date: dict[date, list[_CatalogAction]] = {}
    for action in actions:
        actions_by_date.setdefault(action.ex_date, []).append(action)
    for parent in parents:
        rows = _read_parent_rows(parent)
        if len(rows) != 1:
            raise ValueError(f"daily parent must contain one row: {parent.session_date}")
        row = rows[0]
        close = _decimal(row["close"])
        for action in actions_by_date.get(parent.session_date, []):
            if action.action_type == "split":
                assert action.factor is not None
                shares *= action.factor
            elif action.action_type == "dividend":
                assert action.cash_amount is not None
                dividend_cash = shares * action.cash_amount
                shares += dividend_cash / close
        if initial_value is None:
            initial_value = shares * close
        total_return_index = (shares * close / initial_value * Decimal("100")).quantize(
            _PRICE_QUANTUM
        )
        chain_fingerprint = _benchmark_chain_step(
            chain_fingerprint,
            parent.parquet_sha256,
            action_fingerprint=action_fingerprint,
            algorithm_version=request.algorithm_version,
        )
        benchmark_row = {
            "symbol": "SPY",
            "event_time_utc": _as_datetime(row["event_time_utc"]),
            "session_date": parent.session_date,
            "open": _decimal(row["open"]).quantize(_PRICE_QUANTUM),
            "high": _decimal(row["high"]).quantize(_PRICE_QUANTUM),
            "low": _decimal(row["low"]).quantize(_PRICE_QUANTUM),
            "close": close.quantize(_PRICE_QUANTUM),
            "volume": int(_decimal(row["volume"])),
            "total_return_index": total_return_index,
        }
        input_fingerprint = chain_fingerprint
        result, stale, unchanged = _activate_derived_partition(
            connection,
            root=root,
            request=request,
            dataset="spy_daily_total_return_v1",
            price_view="total_return_benchmark",
            bar_size="1 day",
            session_date=parent.session_date,
            rows=[benchmark_row],
            expected_row_count=1,
            parents=[parent],
            action_fingerprint=action_fingerprint,
            input_fingerprint=input_fingerprint,
        )
        results.append(result)
        stale_count += stale
        unchanged_count += int(unchanged)
    return results, stale_count, unchanged_count


def _activate_derived_partition(
    connection: sqlite3.Connection,
    *,
    root: Path,
    request: ResearchDerivedViewRequest,
    dataset: str,
    price_view: str,
    bar_size: str,
    session_date: date,
    rows: list[dict[str, Any]],
    expected_row_count: int,
    parents: list[_RawPartitionRow],
    action_fingerprint: str,
    input_fingerprint: str | None = None,
) -> tuple[ResearchDerivedPartition, int, bool]:
    selected_input_fingerprint = input_fingerprint or _fingerprint(
        {
            "action_fingerprint": action_fingerprint,
            "algorithm_version": request.algorithm_version,
            "parents": [parent.parquet_sha256 for parent in parents],
        }
    )
    session_text = session_date.isoformat()
    existing = connection.execute(
        """
        SELECT * FROM derived_partitions
        WHERE symbol = ? AND dataset = ? AND price_view = ? AND bar_size = ?
          AND session_date = ? AND active = 1
        """,
        (request.symbol, dataset, price_view, bar_size, session_text),
    ).fetchone()
    if (
        existing is not None
        and str(existing["input_fingerprint"]) == selected_input_fingerprint
        and Path(str(existing["parquet_path"])).is_file()
        and _sha256(Path(str(existing["parquet_path"]))) == str(existing["parquet_sha256"])
    ):
        return _derived_partition_from_row(connection, existing), 0, True

    stale = int(existing is not None)
    revision = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(revision), 0) FROM derived_partitions
            WHERE symbol = ? AND dataset = ? AND price_view = ? AND bar_size = ?
              AND session_date = ?
            """,
            (request.symbol, dataset, price_view, bar_size, session_text),
        ).fetchone()[0]
    ) + 1
    connection.execute(
        """
        UPDATE derived_partitions SET active = 0
        WHERE symbol = ? AND dataset = ? AND price_view = ? AND bar_size = ?
          AND session_date = ?
        """,
        (request.symbol, dataset, price_view, bar_size, session_text),
    )
    parquet_path = (
        root
        / "derived"
        / dataset
        / f"price_view={price_view}"
        / "symbol=SPY"
        / f"year={session_date.year:04d}"
        / f"month={session_date.month:02d}"
        / f"session={session_text}"
        / f"part-r{revision:04d}-{selected_input_fingerprint[7:19]}.parquet"
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    _write_derived_partition(
        parquet_path,
        rows,
        dataset=dataset,
        price_view=price_view,
        bar_size=bar_size,
        action_fingerprint=action_fingerprint,
        input_fingerprint=selected_input_fingerprint,
        algorithm_version=request.algorithm_version,
    )
    parquet_sha256 = _sha256(parquet_path)
    first_timestamp = _as_datetime(rows[0]["event_time_utc"])
    last_timestamp = _as_datetime(rows[-1]["event_time_utc"])
    cursor = connection.execute(
        """
        INSERT INTO derived_partitions(
            symbol, dataset, price_view, bar_size, session_date, revision, active,
            row_count, expected_row_count, first_timestamp, last_timestamp,
            parquet_path, parquet_sha256, action_fingerprint, input_fingerprint,
            algorithm_version, quality_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request.symbol,
            dataset,
            price_view,
            bar_size,
            session_text,
            revision,
            len(rows),
            expected_row_count,
            first_timestamp.isoformat(),
            last_timestamp.isoformat(),
            parquet_path.as_posix(),
            parquet_sha256,
            action_fingerprint,
            selected_input_fingerprint,
            request.algorithm_version,
            ResearchDataQualityStatus.PASSED.value,
            _utc_iso(),
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("derived partition insert returned no id")
    derived_id = int(cursor.lastrowid)
    for parent in parents:
        connection.execute(
            """
            INSERT INTO derived_lineage(
                derived_partition_id, parent_partition_id, lineage_role,
                parent_parquet_sha256
            ) VALUES (?, ?, 'source', ?)
            """,
            (derived_id, parent.id, parent.parquet_sha256),
        )
    row = connection.execute(
        "SELECT * FROM derived_partitions WHERE id = ?",
        (derived_id,),
    ).fetchone()
    assert row is not None
    return _derived_partition_from_row(connection, row), stale, False


def _write_derived_partition(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    dataset: str,
    price_view: str,
    bar_size: str,
    action_fingerprint: str,
    input_fingerprint: str,
    algorithm_version: str,
) -> None:
    fields = [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("event_time_utc", pa.timestamp("ns", tz="UTC"), nullable=False),
        pa.field("session_date", pa.date32(), nullable=False),
        pa.field("open", pa.decimal128(20, 8), nullable=False),
        pa.field("high", pa.decimal128(20, 8), nullable=False),
        pa.field("low", pa.decimal128(20, 8), nullable=False),
        pa.field("close", pa.decimal128(20, 8), nullable=False),
        pa.field("volume", pa.int64(), nullable=False),
    ]
    if price_view == "total_return_benchmark":
        fields.append(pa.field("total_return_index", pa.decimal128(20, 8), nullable=False))
    schema = pa.schema(
        fields,
        metadata={
            b"source": b"quant-system-derived",
            b"dataset": dataset.encode("ascii"),
            b"price_view": price_view.encode("ascii"),
            b"bar_size": bar_size.encode("ascii"),
            b"action_fingerprint": action_fingerprint.encode("ascii"),
            b"input_fingerprint": input_fingerprint.encode("ascii"),
            b"algorithm_version": algorithm_version.encode("ascii"),
            b"session_calendar": b"XNYS",
        },
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    _write_immutable_parquet(path, table)


def _write_immutable_parquet(path: Path, table: pa.Table) -> None:
    temporary = path.with_name(f".{uuid4().hex[:8]}.tmp")
    try:
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            version="2.6",
            write_statistics=True,
        )
        if path.exists():
            if _sha256(path) != _sha256(temporary):
                raise RuntimeError(f"immutable Parquet collision: {path}")
            return
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _active_derived_rows(
    connection: sqlite3.Connection,
    request: ResearchCatalogLoadRequest,
) -> list[sqlite3.Row]:
    clauses = [
        "symbol = ?",
        "price_view = ?",
        "bar_size = ?",
        "active = 1",
        "quality_status = 'passed'",
    ]
    parameters: list[object] = [request.symbol, request.price_view, request.bar_size]
    if request.start_date:
        clauses.append("session_date >= ?")
        parameters.append(request.start_date)
    if request.end_date:
        clauses.append("session_date <= ?")
        parameters.append(request.end_date)
    query = (
        "SELECT * FROM derived_partitions WHERE "
        + " AND ".join(clauses)
        + " ORDER BY session_date, first_timestamp"
    )
    return connection.execute(query, parameters).fetchall()


def _derived_coverage_errors(
    rows: list[sqlite3.Row],
    request: ResearchCatalogLoadRequest,
) -> list[str]:
    observed = {date.fromisoformat(str(row["session_date"])) for row in rows}
    start = date.fromisoformat(request.start_date) if request.start_date else min(observed)
    end = date.fromisoformat(request.end_date) if request.end_date else max(observed)
    calendar = xcals.get_calendar("XNYS")
    expected = {item.date() for item in calendar.sessions_in_range(start, end)}
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    errors: list[str] = []
    if missing:
        samples = ", ".join(item.isoformat() for item in missing[:5])
        errors.append(
            f"catalog coverage is missing {len(missing)} XNYS sessions: {samples}"
        )
    if unexpected:
        samples = ", ".join(item.isoformat() for item in unexpected[:5])
        errors.append(f"catalog contains non-XNYS sessions: {samples}")
    return errors


def _benchmark_chain_errors(
    connection: sqlite3.Connection,
    rows: list[sqlite3.Row],
    *,
    action_fingerprint: str,
) -> list[str]:
    if not rows:
        return []
    algorithm_versions = {str(row["algorithm_version"]) for row in rows}
    if len(algorithm_versions) != 1:
        return []
    algorithm_version = next(iter(algorithm_versions))
    selected = {str(row["session_date"]): str(row["input_fingerprint"]) for row in rows}
    chain_fingerprint = _benchmark_chain_seed(
        action_fingerprint=action_fingerprint,
        algorithm_version=algorithm_version,
    )
    observed_selected: set[str] = set()
    errors: list[str] = []
    for parent in _active_raw_partitions(connection, dataset="daily_bars_v1"):
        chain_fingerprint = _benchmark_chain_step(
            chain_fingerprint,
            parent.parquet_sha256,
            action_fingerprint=action_fingerprint,
            algorithm_version=algorithm_version,
        )
        session_text = parent.session_date.isoformat()
        expected = selected.get(session_text)
        if expected is None:
            continue
        observed_selected.add(session_text)
        if expected != chain_fingerprint:
            errors.append(f"benchmark input fingerprint is stale: {session_text}")
    for missing in sorted(set(selected) - observed_selected):
        errors.append(f"benchmark parent session is unavailable: {missing}")
    return errors


def _benchmark_chain_seed(
    *,
    action_fingerprint: str,
    algorithm_version: str,
) -> str:
    return _fingerprint(
        {
            "action_fingerprint": action_fingerprint,
            "algorithm_version": algorithm_version,
            "chain": "benchmark-genesis",
        }
    )


def _benchmark_chain_step(
    previous_fingerprint: str,
    parent_sha256: str,
    *,
    action_fingerprint: str,
    algorithm_version: str,
) -> str:
    return _fingerprint(
        {
            "action_fingerprint": action_fingerprint,
            "algorithm_version": algorithm_version,
            "parent_sha256": parent_sha256,
            "previous_fingerprint": previous_fingerprint,
        }
    )


def _derived_partition_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> ResearchDerivedPartition:
    parent_ids = [
        int(item["parent_partition_id"])
        for item in connection.execute(
            """
            SELECT parent_partition_id FROM derived_lineage
            WHERE derived_partition_id = ? ORDER BY parent_partition_id
            """,
            (int(row["id"]),),
        ).fetchall()
    ]
    return ResearchDerivedPartition(
        session_date=str(row["session_date"]),
        dataset=str(row["dataset"]),
        price_view=str(row["price_view"]),
        bar_size=str(row["bar_size"]),
        revision=int(row["revision"]),
        active=bool(row["active"]),
        row_count=int(row["row_count"]),
        expected_row_count=int(row["expected_row_count"]),
        first_timestamp=_optional_datetime(row["first_timestamp"]),
        last_timestamp=_optional_datetime(row["last_timestamp"]),
        parquet_path=str(row["parquet_path"]),
        parquet_sha256=str(row["parquet_sha256"]),
        action_fingerprint=str(row["action_fingerprint"]),
        input_fingerprint=str(row["input_fingerprint"]),
        algorithm_version=str(row["algorithm_version"]),
        parent_partition_ids=parent_ids,
        quality_status=ResearchDataQualityStatus(str(row["quality_status"])),
    )


def _derived_lineage_errors(
    connection: sqlite3.Connection,
    derived_row: sqlite3.Row,
) -> list[str]:
    rows = connection.execute(
        """
        SELECT l.parent_partition_id, l.parent_parquet_sha256,
               p.active, p.parquet_path, p.parquet_sha256
        FROM derived_lineage AS l
        JOIN partitions AS p ON p.id = l.parent_partition_id
        WHERE l.derived_partition_id = ?
        """,
        (int(derived_row["id"]),),
    ).fetchall()
    if not rows:
        return [f"derived partition lacks parent lineage: {derived_row['session_date']}"]
    errors: list[str] = []
    for row in rows:
        if not bool(row["active"]):
            errors.append(
                f"derived parent is superseded: {derived_row['session_date']}"
            )
            continue
        recorded_hash = str(row["parent_parquet_sha256"])
        catalog_hash = str(row["parquet_sha256"])
        if recorded_hash != catalog_hash:
            errors.append(
                f"derived parent fingerprint drift: {derived_row['session_date']}"
            )
            continue
        path = Path(str(row["parquet_path"])).resolve()
        if not path.is_file() or _sha256(path) != catalog_hash:
            errors.append(
                f"derived parent checksum mismatch: {derived_row['session_date']}"
            )
    return errors


def _load_derived_bars(
    path: Path,
    symbol: str,
    *,
    price_view: str,
) -> list[BacktestBar]:
    rows = pq.read_table(path).to_pylist()
    use_total_return = price_view == "total_return_benchmark"
    return [
        BacktestBar(
            symbol=symbol,
            timestamp=_as_datetime(row["event_time_utc"]),
            open=_decimal(row["total_return_index"] if use_total_return else row["open"]),
            high=_decimal(row["total_return_index"] if use_total_return else row["high"]),
            low=_decimal(row["total_return_index"] if use_total_return else row["low"]),
            close=_decimal(row["total_return_index"] if use_total_return else row["close"]),
            volume=_decimal(row["volume"]),
            source_bars_path=path.as_posix(),
            source="research_catalog",
        )
        for row in rows
    ]


def _feed_from_bars(bars: list[BacktestBar]) -> BacktestDataFeed:
    frames = [
        BacktestFeedFrame(timestamp=bar.timestamp, bars_by_symbol={"SPY": bar})
        for bar in bars
    ]
    return BacktestDataFeed(
        symbols=["SPY"],
        alignment_mode=BacktestAlignmentMode.INTERSECTION,
        frames=frames,
        total_bars=len(bars),
        frame_count=len(frames),
        first_timestamp=bars[0].timestamp,
        last_timestamp=bars[-1].timestamp,
        missing_bars_by_symbol={"SPY": 0},
        duplicate_timestamps_by_symbol={"SPY": 0},
        feed_status=BacktestFeedStatus.READY,
    )


def _bars_fingerprint(bars: list[BacktestBar]) -> str:
    payload = [
        {
            "close": str(bar.close),
            "high": str(bar.high),
            "low": str(bar.low),
            "open": str(bar.open),
            "symbol": bar.symbol,
            "timestamp": bar.timestamp.isoformat(),
            "volume": str(bar.volume),
        }
        for bar in bars
    ]
    return _fingerprint(payload)


def _research_partition_from_row(row: sqlite3.Row) -> ResearchDataPartition:
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


def _validate_ohlcv(bar: _DailyBar) -> None:
    values = (bar.open, bar.high, bar.low, bar.close)
    if any(value <= 0 or not value.is_finite() for value in values):
        raise ValueError(f"invalid daily OHLC: {bar.session_date}")
    if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
        raise ValueError(f"inconsistent daily OHLC: {bar.session_date}")
    if (
        bar.volume < 0
        or not bar.volume.is_finite()
        or bar.volume != bar.volume.to_integral_value()
    ):
        raise ValueError(f"invalid daily volume: {bar.session_date}")


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if len(normalized) == 10:
        return datetime.combine(date.fromisoformat(normalized), datetime.min.time(), tzinfo=UTC)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return _parse_timestamp(str(value))


def _optional_datetime(value: object) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    return _as_datetime(value)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    return _decimal(value)


def _require_columns(observed: set[str], required: set[str]) -> None:
    missing = sorted(required - observed)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


@contextmanager
def _catalog_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "derive_research_views",
    "import_research_data_batch",
    "ingest_canonical_daily_file",
    "ingest_corporate_action_file",
    "load_research_catalog",
]
