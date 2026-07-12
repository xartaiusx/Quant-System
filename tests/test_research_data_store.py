from __future__ import annotations

import csv
import gzip
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from pydantic import ValidationError

from trader.data.research_store import (
    audit_research_data_store,
    ingest_massive_minute_file,
)
from trader.models import ResearchDataAuditRequest, ResearchDataIngestRequest
from trader.reporting.reports import markdown_summary

_FIELDNAMES = [
    "ticker",
    "volume",
    "open",
    "close",
    "high",
    "low",
    "window_start",
    "transactions",
]


def test_ingest_archives_writes_parquet_and_audits_cleanly(tmp_path: Path) -> None:
    source = _write_massive_file(tmp_path / "downloads/2026-07-02.csv.gz", date(2026, 7, 2))
    root = tmp_path / "store"

    report = ingest_massive_minute_file(_request(source, root))

    assert report.ok is True
    assert report.final_status == "completed"
    assert report.rows_scanned == 391
    assert report.symbol_rows_seen == 390
    assert report.rth_rows_selected == 390
    assert report.outside_rth_rows_excluded == 0
    assert report.broker_contacted is False
    assert report.order_api_invoked is False
    assert report.promotion_eligible is False
    assert report.artifact is not None
    assert Path(report.artifact.stored_path).is_file()
    assert Path(report.artifact.stored_path) != source
    assert len(report.partitions) == 1
    partition = report.partitions[0]
    assert partition.session_date == "2026-07-02"
    assert partition.revision == 1
    assert partition.row_count == 390
    assert partition.expected_row_count == 390
    assert pq.ParquetFile(partition.parquet_path).metadata.num_rows == 390

    audit = audit_research_data_store(
        ResearchDataAuditRequest(root_path=root.as_posix())
    )
    assert audit.ok is True
    assert audit.active_session_count == 1
    assert audit.total_row_count == 390
    assert audit.missing_session_dates == []


def test_identical_artifact_is_idempotent(tmp_path: Path) -> None:
    source = _write_massive_file(tmp_path / "downloads/2026-07-02.csv.gz", date(2026, 7, 2))
    root = tmp_path / "store"

    first = ingest_massive_minute_file(_request(source, root))
    second = ingest_massive_minute_file(_request(source, root))

    assert first.ok is True
    assert second.ok is True
    assert second.idempotent_replay is True
    assert second.final_status == "unchanged"
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        partition_count = connection.execute("SELECT COUNT(*) FROM partitions").fetchone()[0]
        run_count = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]
    assert partition_count == 1
    assert run_count == 2


def test_correction_creates_new_revision_without_overwriting_raw(tmp_path: Path) -> None:
    first_source = _write_massive_file(
        tmp_path / "first/2026-07-02.csv.gz",
        date(2026, 7, 2),
    )
    second_source = _write_massive_file(
        tmp_path / "second/2026-07-02.csv.gz",
        date(2026, 7, 2),
        close_offset=Decimal("0.01"),
    )
    root = tmp_path / "store"

    first = ingest_massive_minute_file(_request(first_source, root))
    second = ingest_massive_minute_file(_request(second_source, root))

    assert first.ok is True
    assert second.ok is True
    assert first.artifact is not None
    assert second.artifact is not None
    assert first.artifact.sha256 != second.artifact.sha256
    assert first.artifact.stored_path != second.artifact.stored_path
    assert Path(first.artifact.stored_path).is_file()
    assert Path(second.artifact.stored_path).is_file()
    assert second.partitions[0].revision == 2
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        revisions = connection.execute(
            "SELECT revision, active FROM partitions ORDER BY revision"
        ).fetchall()
    assert revisions == [(1, 0), (2, 1)]


def test_missing_minute_fails_without_activating_partition(tmp_path: Path) -> None:
    source = _write_massive_file(
        tmp_path / "downloads/2026-07-02.csv.gz",
        date(2026, 7, 2),
        omit_index=10,
    )
    root = tmp_path / "store"

    report = ingest_massive_minute_file(_request(source, root))

    assert report.ok is False
    assert report.final_status == "failed"
    assert report.partitions == []
    assert any(finding.code == "missing_rth_minutes" for finding in report.findings)
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        partition_count = connection.execute("SELECT COUNT(*) FROM partitions").fetchone()[0]
    assert partition_count == 0


def test_missing_source_fails_with_structured_evidence(tmp_path: Path) -> None:
    root = tmp_path / "store"

    report = ingest_massive_minute_file(
        _request(tmp_path / "missing/2026-07-02.csv.gz", root)
    )

    assert report.ok is False
    assert report.final_status == "failed"
    assert Path(report.catalog_path).is_file()
    assert any(finding.code == "source_not_found" for finding in report.findings)


def test_out_of_order_rows_fail_closed(tmp_path: Path) -> None:
    source = _write_massive_file(
        tmp_path / "downloads/2026-07-02.csv.gz",
        date(2026, 7, 2),
        reverse=True,
    )

    report = ingest_massive_minute_file(_request(source, tmp_path / "store"))

    assert report.ok is False
    assert any(finding.code == "out_of_order_rows" for finding in report.findings)


def test_exchange_calendar_accepts_early_close_session(tmp_path: Path) -> None:
    source = _write_massive_file(
        tmp_path / "downloads/2026-11-27.csv.gz",
        date(2026, 11, 27),
    )

    report = ingest_massive_minute_file(_request(source, tmp_path / "store"))

    assert report.ok is True
    assert report.rth_rows_selected == 210
    assert report.partitions[0].expected_row_count == 210


def test_audit_detects_partition_tampering(tmp_path: Path) -> None:
    source = _write_massive_file(tmp_path / "downloads/2026-07-02.csv.gz", date(2026, 7, 2))
    root = tmp_path / "store"
    ingest = ingest_massive_minute_file(_request(source, root))
    partition_path = Path(ingest.partitions[0].parquet_path)
    partition_path.write_bytes(partition_path.read_bytes() + b"tampered")

    audit = audit_research_data_store(
        ResearchDataAuditRequest(root_path=root.as_posix())
    )

    assert audit.ok is False
    assert any(
        finding.code == "partition_checksum_mismatch" for finding in audit.findings
    )


def test_audit_detects_missing_xnys_session_between_partitions(tmp_path: Path) -> None:
    first = _write_massive_file(
        tmp_path / "downloads/2026-07-02.csv.gz",
        date(2026, 7, 2),
    )
    second = _write_massive_file(
        tmp_path / "downloads/2026-07-07.csv.gz",
        date(2026, 7, 7),
    )
    root = tmp_path / "store"
    assert ingest_massive_minute_file(_request(first, root)).ok is True
    assert ingest_massive_minute_file(_request(second, root)).ok is True

    audit = audit_research_data_store(
        ResearchDataAuditRequest(root_path=root.as_posix())
    )

    assert audit.ok is False
    assert audit.missing_session_dates == ["2026-07-06"]
    assert any(finding.code == "missing_catalog_sessions" for finding in audit.findings)


def test_scope_is_spy_raw_and_rth_only(tmp_path: Path) -> None:
    source = tmp_path / "unused.csv.gz"
    with pytest.raises(ValidationError, match="SPY-only"):
        ResearchDataIngestRequest(
            source_path=source.as_posix(),
            root_path=tmp_path.as_posix(),
            symbol="AAPL",
        )
    with pytest.raises(ValidationError, match="raw price view"):
        ResearchDataIngestRequest(
            source_path=source.as_posix(),
            root_path=tmp_path.as_posix(),
            price_view="adjusted",
        )
    with pytest.raises(ValidationError, match="regular hours"):
        ResearchDataIngestRequest(
            source_path=source.as_posix(),
            root_path=tmp_path.as_posix(),
            rth_only=False,
        )


def test_reports_serialize_and_render_markdown(tmp_path: Path) -> None:
    source = _write_massive_file(tmp_path / "downloads/2026-07-02.csv.gz", date(2026, 7, 2))
    report = ingest_massive_minute_file(_request(source, tmp_path / "store"))
    payload = report.model_dump(mode="json")

    rendered = markdown_summary(payload)

    assert payload["submitted_orders"] is False
    assert "SPY Research Data Ingestion" in rendered
    assert "Immutable raw preserved: `True`" in rendered
    assert "Order API invoked: `False`" in rendered


def test_module_remains_broker_and_order_api_free() -> None:
    source = Path("src/trader/data/research_store.py").read_text()
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "ibapi",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
    ):
        assert forbidden not in source


def _request(source: Path, root: Path) -> ResearchDataIngestRequest:
    return ResearchDataIngestRequest(
        source_path=source.as_posix(),
        root_path=root.as_posix(),
    )


def _write_massive_file(
    path: Path,
    session_date: date,
    *,
    omit_index: int | None = None,
    reverse: bool = False,
    close_offset: Decimal = Decimal("0"),
) -> Path:
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, str]] = []
    for index, timestamp in enumerate(calendar.session_minutes(session_date)):
        if index == omit_index:
            continue
        event_time = timestamp.to_pydatetime()
        open_ = Decimal("500") + Decimal(index) / Decimal("100")
        close = open_ + Decimal("0.02") + close_offset
        rows.append(
            {
                "ticker": "SPY",
                "volume": str(1000 + index),
                "open": str(open_),
                "close": str(close),
                "high": str(max(open_, close) + Decimal("0.01")),
                "low": str(min(open_, close) - Decimal("0.01")),
                "window_start": str(int(event_time.timestamp()) * 1_000_000_000),
                "transactions": str(10 + index),
            }
        )
    if reverse:
        rows.reverse()
    rows.append(
        {
            "ticker": "AAPL",
            "volume": "100",
            "open": "200",
            "close": "201",
            "high": "202",
            "low": "199",
            "window_start": rows[0]["window_start"],
            "transactions": "10",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, mode="wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path.resolve()
