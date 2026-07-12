from __future__ import annotations

import csv
import gzip
import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from typer.testing import CliRunner

from trader.cli import app
from trader.data.research_catalog import (
    derive_research_views,
    import_research_data_batch,
    ingest_canonical_daily_file,
    ingest_corporate_action_file,
    load_research_catalog,
    load_research_catalog_for_final_holdout,
)
from trader.data.research_store import (
    ingest_massive_minute_file,
    initialize_research_store,
)
from trader.models import (
    ResearchCanonicalDailyIngestRequest,
    ResearchCatalogLoadRequest,
    ResearchCorporateActionIngestRequest,
    ResearchDataBatchImportRequest,
    ResearchDataIngestRequest,
    ResearchDerivedViewRequest,
    ResearchSampleKind,
)
from trader.reporting.reports import markdown_summary

_MASSIVE_FIELDS = [
    "ticker",
    "volume",
    "open",
    "close",
    "high",
    "low",
    "window_start",
    "transactions",
]
_DAILY_FIELDS = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
_ACTION_FIELDS = [
    "symbol",
    "ex_date",
    "event_type",
    "factor",
    "cash_amount",
    "currency",
    "revision",
]


def test_catalog_v1_is_migrated_to_v3(tmp_path: Path) -> None:
    root = tmp_path / "store"
    catalog = root / "catalog/research.sqlite3"
    catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata(version INTEGER PRIMARY KEY, installed_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_metadata(version, installed_at) VALUES (1, 'test')"
        )

    initialized = initialize_research_store(root)

    assert initialized == catalog
    with sqlite3.connect(catalog) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_metadata ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert versions == [(1,), (2,), (3,)]
    assert {
        "action_sets",
        "corporate_actions",
        "derived_partitions",
        "derived_lineage",
        "experiment_specs",
        "experiment_runs",
        "holdout_access",
        "sealed_periods",
        "instrument_master",
    } <= tables


def test_catalog_v3_migration_rolls_back_on_schema_conflict(tmp_path: Path) -> None:
    root = tmp_path / "store"
    catalog = root / "catalog/research.sqlite3"
    catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata(version INTEGER PRIMARY KEY, installed_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_metadata(version, installed_at) VALUES (?, 'test')",
            [(1,), (2,)],
        )
        connection.execute(
            """
            CREATE TABLE experiment_specs(
                experiment_id TEXT PRIMARY KEY,
                spec_fingerprint TEXT NOT NULL UNIQUE,
                spec_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE TABLE sealed_periods(conflict TEXT)")

    with pytest.raises(sqlite3.Error):
        initialize_research_store(root)

    with sqlite3.connect(catalog) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(experiment_specs)")
        }
        versions = connection.execute(
            "SELECT version FROM schema_metadata ORDER BY version"
        ).fetchall()
    assert "status" not in columns
    assert "supersedes_experiment_id" not in columns
    assert versions == [(1,), (2,)]


def test_derive_and_load_normal_session_with_split_lineage(tmp_path: Path) -> None:
    root = tmp_path / "store"
    source = _write_massive_file(tmp_path / "source/2026-07-02.csv.gz", date(2026, 7, 2))
    assert ingest_massive_minute_file(_minute_request(source, root)).ok is True
    actions = _write_actions(
        tmp_path / "source/actions.csv",
        [
            {
                "symbol": "SPY",
                "ex_date": "2026-07-06",
                "event_type": "split",
                "factor": "2",
                "cash_amount": "",
                "currency": "USD",
                "revision": "synthetic-v1",
            }
        ],
    )
    assert _ingest_actions(actions, root, "2026-07-02", "2026-07-06").ok is True

    derived = derive_research_views(ResearchDerivedViewRequest(root_path=root.as_posix()))

    assert derived.ok is True
    assert len(derived.partitions) == 2
    assert {partition.row_count for partition in derived.partitions} == {78}
    assert {partition.expected_row_count for partition in derived.partitions} == {78}
    raw = load_research_catalog(
        ResearchCatalogLoadRequest(root_path=root.as_posix(), price_view="raw_execution")
    )
    adjusted = load_research_catalog(
        ResearchCatalogLoadRequest(
            root_path=root.as_posix(),
            price_view="split_adjusted_signal",
        )
    )
    assert raw.ok is True and raw.feed is not None
    assert adjusted.ok is True and adjusted.feed is not None
    assert len(raw.feed.frames) == 78
    assert len(adjusted.feed.frames) == 78
    raw_open = raw.feed.frames[0].bars_by_symbol["SPY"].open
    adjusted_open = adjusted.feed.frames[0].bars_by_symbol["SPY"].open
    assert adjusted_open == raw_open / Decimal("2")
    assert adjusted.dataset_fingerprint is not None

    unchanged = derive_research_views(
        ResearchDerivedViewRequest(root_path=root.as_posix())
    )
    assert unchanged.ok is True
    assert unchanged.idempotent_partition_count == 2


def test_catalog_seal_blocks_generic_access_and_requires_recorded_capability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    source = _write_massive_file(tmp_path / "source/2026-07-02.csv.gz", date(2026, 7, 2))
    assert ingest_massive_minute_file(_minute_request(source, root)).ok is True
    actions = _write_actions(tmp_path / "source/actions.csv", [])
    assert _ingest_actions(actions, root, "2026-07-02", "2026-07-02").ok is True
    assert derive_research_views(ResearchDerivedViewRequest(root_path=root.as_posix())).ok
    catalog = root / "catalog/research.sqlite3"
    with sqlite3.connect(catalog) as connection:
        connection.execute(
            """
            INSERT INTO experiment_specs(
                experiment_id, spec_fingerprint, spec_json, created_at, status
            ) VALUES ('sealed-v1', 'sha256:spec', '{}', 'test', 'active')
            """
        )
        connection.execute(
            """
            INSERT INTO sealed_periods(
                experiment_id, symbol, start_date, end_date, purpose, created_at
            ) VALUES ('sealed-v1', 'SPY', '2026-07-02', '2026-07-02',
                      'final_holdout', 'test')
            """
        )

    request = ResearchCatalogLoadRequest(
        root_path=root.as_posix(),
        start_date="2026-07-02",
        end_date="2026-07-02",
    )
    generic = load_research_catalog(request)
    assert generic.ok is False
    assert "permanently sealed holdout" in generic.errors[0]

    unauthorized = load_research_catalog_for_final_holdout(
        request,
        experiment_id="sealed-v1",
        holdout_access_fingerprint="sha256:access",
    )
    assert unauthorized.ok is False
    assert "not recorded" in unauthorized.errors[0]

    with sqlite3.connect(catalog) as connection:
        connection.execute(
            """
            INSERT INTO holdout_access(
                experiment_id, holdout_fingerprint, confirmation, accessed_at
            ) VALUES ('sealed-v1', 'sha256:access', 'CONFIRM', 'test')
            """
        )
    authorized = load_research_catalog_for_final_holdout(
        request,
        experiment_id="sealed-v1",
        holdout_access_fingerprint="sha256:access",
    )
    assert authorized.ok is True


def test_early_close_derives_exactly_42_five_minute_bars(tmp_path: Path) -> None:
    root = tmp_path / "store"
    source = _write_massive_file(tmp_path / "source/2026-11-27.csv.gz", date(2026, 11, 27))
    assert ingest_massive_minute_file(_minute_request(source, root)).ok is True
    actions = _write_actions(tmp_path / "source/actions.csv", [])
    assert _ingest_actions(actions, root, "2026-11-27", "2026-11-27").ok is True

    report = derive_research_views(ResearchDerivedViewRequest(root_path=root.as_posix()))

    assert report.ok is True
    assert len(report.partitions) == 2
    assert {partition.row_count for partition in report.partitions} == {42}
    assert {partition.expected_row_count for partition in report.partitions} == {42}


def test_daily_import_and_dividend_total_return_benchmark(tmp_path: Path) -> None:
    root = tmp_path / "store"
    minute = _write_massive_file(tmp_path / "source/2026-07-02.csv.gz", date(2026, 7, 2))
    assert ingest_massive_minute_file(_minute_request(minute, root)).ok is True
    daily = _write_daily(
        tmp_path / "source/daily.csv",
        [
            ("2026-07-01", "100", "101", "99", "100", "1000000"),
            ("2026-07-02", "100", "102", "99", "101", "1100000"),
        ],
    )
    daily_report = ingest_canonical_daily_file(
        ResearchCanonicalDailyIngestRequest(
            source_path=daily.as_posix(),
            root_path=root.as_posix(),
        )
    )
    assert daily_report.ok is True
    assert len(daily_report.partitions) == 2
    actions = _write_actions(
        tmp_path / "source/actions.csv",
        [
            {
                "symbol": "SPY",
                "ex_date": "2026-07-02",
                "event_type": "dividend",
                "factor": "",
                "cash_amount": "1.00",
                "currency": "USD",
                "revision": "vendor-v1",
            }
        ],
    )
    assert _ingest_actions(actions, root, "2026-07-01", "2026-07-02").ok is True

    derived = derive_research_views(ResearchDerivedViewRequest(root_path=root.as_posix()))

    assert derived.ok is True
    benchmark = [
        partition
        for partition in derived.partitions
        if partition.price_view == "total_return_benchmark"
    ]
    assert len(benchmark) == 2
    rows = [
        pq.read_table(partition.parquet_path).to_pylist()[0]
        for partition in benchmark
    ]
    assert rows[0]["total_return_index"] == Decimal("100.00000000")
    assert rows[1]["total_return_index"] > Decimal("101")


def test_missing_daily_source_fails_closed(tmp_path: Path) -> None:
    report = ingest_canonical_daily_file(
        ResearchCanonicalDailyIngestRequest(
            source_path=(tmp_path / "missing.csv").as_posix(),
            root_path=(tmp_path / "store").as_posix(),
        )
    )

    assert report.ok is False
    assert report.final_status == "failed"
    assert "source file not found" in report.errors[0]


def test_daily_source_rejects_fractional_volume(tmp_path: Path) -> None:
    source = _write_daily(
        tmp_path / "source/daily.csv",
        [("2026-07-02", "100", "101", "99", "100", "1000.5")],
    )

    report = ingest_canonical_daily_file(
        ResearchCanonicalDailyIngestRequest(
            source_path=source.as_posix(),
            root_path=(tmp_path / "store").as_posix(),
        )
    )

    assert report.ok is False
    assert "invalid daily volume" in report.errors[0]


def test_parent_correction_invalidates_derived_revision(tmp_path: Path) -> None:
    root = tmp_path / "store"
    first = _write_massive_file(tmp_path / "first/2026-07-02.csv.gz", date(2026, 7, 2))
    assert ingest_massive_minute_file(_minute_request(first, root)).ok is True
    actions = _write_actions(tmp_path / "first/actions.csv", [])
    assert _ingest_actions(actions, root, "2026-07-02", "2026-07-02").ok is True
    initial = derive_research_views(ResearchDerivedViewRequest(root_path=root.as_posix()))
    assert initial.ok is True

    correction = _write_massive_file(
        tmp_path / "correction/2026-07-02.csv.gz",
        date(2026, 7, 2),
        close_offset=Decimal("0.01"),
    )
    assert ingest_massive_minute_file(_minute_request(correction, root)).ok is True
    stale_load = load_research_catalog(
        ResearchCatalogLoadRequest(root_path=root.as_posix())
    )
    assert stale_load.ok is False
    assert any("parent is superseded" in error for error in stale_load.errors)

    refreshed = derive_research_views(ResearchDerivedViewRequest(root_path=root.as_posix()))
    assert refreshed.ok is True
    assert refreshed.stale_partitions_superseded == 2
    assert {partition.revision for partition in refreshed.partitions} == {2}
    assert load_research_catalog(
        ResearchCatalogLoadRequest(root_path=root.as_posix())
    ).ok is True


def test_action_set_correction_invalidates_derived_revision(tmp_path: Path) -> None:
    root = tmp_path / "store"
    minute = _write_massive_file(tmp_path / "source/2026-07-02.csv.gz", date(2026, 7, 2))
    assert ingest_massive_minute_file(_minute_request(minute, root)).ok is True
    empty_actions = _write_actions(tmp_path / "source/actions-empty.csv", [])
    assert _ingest_actions(empty_actions, root, "2026-07-02", "2026-07-02").ok is True
    assert derive_research_views(
        ResearchDerivedViewRequest(root_path=root.as_posix())
    ).ok is True

    corrected_actions = _write_actions(
        tmp_path / "correction/actions.csv",
        [
            {
                "symbol": "SPY",
                "ex_date": "2026-07-02",
                "event_type": "dividend",
                "factor": "",
                "cash_amount": "1.00",
                "currency": "USD",
                "revision": "vendor-v2",
            }
        ],
    )
    assert _ingest_actions(
        corrected_actions,
        root,
        "2026-07-02",
        "2026-07-02",
    ).ok is True

    stale = load_research_catalog(
        ResearchCatalogLoadRequest(root_path=root.as_posix())
    )

    assert stale.ok is False
    assert any("action fingerprint is stale" in error for error in stale.errors)
    assert derive_research_views(
        ResearchDerivedViewRequest(root_path=root.as_posix())
    ).ok is True
    assert load_research_catalog(
        ResearchCatalogLoadRequest(root_path=root.as_posix())
    ).ok is True


def test_prior_daily_correction_invalidates_later_benchmark(tmp_path: Path) -> None:
    root = tmp_path / "store"
    minute = _write_massive_file(tmp_path / "source/2026-07-02.csv.gz", date(2026, 7, 2))
    assert ingest_massive_minute_file(_minute_request(minute, root)).ok is True
    daily = _write_daily(
        tmp_path / "source/daily.csv",
        [
            ("2026-07-01", "100", "101", "99", "100", "1000000"),
            ("2026-07-02", "100", "102", "99", "101", "1100000"),
        ],
    )
    assert ingest_canonical_daily_file(
        ResearchCanonicalDailyIngestRequest(
            source_path=daily.as_posix(),
            root_path=root.as_posix(),
        )
    ).ok is True
    actions = _write_actions(tmp_path / "source/actions.csv", [])
    assert _ingest_actions(actions, root, "2026-07-01", "2026-07-02").ok is True
    assert derive_research_views(
        ResearchDerivedViewRequest(root_path=root.as_posix())
    ).ok is True

    correction = _write_daily(
        tmp_path / "correction/daily.csv",
        [("2026-07-01", "100", "102", "99", "101", "1000000")],
    )
    assert ingest_canonical_daily_file(
        ResearchCanonicalDailyIngestRequest(
            source_path=correction.as_posix(),
            root_path=root.as_posix(),
        )
    ).ok is True
    request = ResearchCatalogLoadRequest(
        root_path=root.as_posix(),
        price_view="total_return_benchmark",
        bar_size="1 day",
        start_date="2026-07-02",
        end_date="2026-07-02",
    )

    stale = load_research_catalog(request)

    assert stale.ok is False
    assert any("benchmark input fingerprint is stale" in error for error in stale.errors)
    assert derive_research_views(
        ResearchDerivedViewRequest(root_path=root.as_posix())
    ).ok is True
    assert load_research_catalog(request).ok is True


def test_corporate_action_source_rejects_duplicate_event_revisions(tmp_path: Path) -> None:
    source = _write_actions(
        tmp_path / "source/actions.csv",
        [
            {
                "symbol": "SPY",
                "ex_date": "2026-07-02",
                "event_type": "dividend",
                "factor": "",
                "cash_amount": "1.00",
                "currency": "USD",
                "revision": "vendor-v1",
            },
            {
                "symbol": "SPY",
                "ex_date": "2026-07-02",
                "event_type": "dividend",
                "factor": "",
                "cash_amount": "1.01",
                "currency": "USD",
                "revision": "vendor-v2",
            },
        ],
    )

    report = _ingest_actions(
        source,
        tmp_path / "store",
        "2026-07-02",
        "2026-07-02",
    )

    assert report.ok is False
    assert "duplicate events" in report.errors[0]


def test_catalog_loader_rejects_parent_checksum_drift(tmp_path: Path) -> None:
    root = tmp_path / "store"
    source = _write_massive_file(tmp_path / "source/2026-07-02.csv.gz", date(2026, 7, 2))
    ingest = ingest_massive_minute_file(_minute_request(source, root))
    actions = _write_actions(tmp_path / "source/actions.csv", [])
    assert ingest.ok is True
    assert _ingest_actions(actions, root, "2026-07-02", "2026-07-02").ok is True
    assert derive_research_views(
        ResearchDerivedViewRequest(root_path=root.as_posix())
    ).ok is True
    parent = Path(ingest.partitions[0].parquet_path)
    parent.write_bytes(parent.read_bytes() + b"tampered")

    report = load_research_catalog(
        ResearchCatalogLoadRequest(root_path=root.as_posix())
    )

    assert report.ok is False
    assert any("parent checksum mismatch" in error for error in report.errors)


def test_batch_import_is_sorted_local_and_broker_free(tmp_path: Path) -> None:
    root = tmp_path / "store"
    source_dir = tmp_path / "minute"
    _write_massive_file(source_dir / "2026-07-02.csv.gz", date(2026, 7, 2))
    _write_massive_file(source_dir / "2026-07-01.csv.gz", date(2026, 7, 1))

    report = import_research_data_batch(
        ResearchDataBatchImportRequest(
            source_dir=source_dir.as_posix(),
            root_path=root.as_posix(),
            vendor="massive",
            kind=ResearchSampleKind.MINUTE_BARS,
        )
    )

    assert report.ok is True
    assert report.succeeded_count == 2
    assert [Path(path).name for path in report.source_files] == [
        "2026-07-01.csv.gz",
        "2026-07-02.csv.gz",
    ]
    assert report.broker_contacted is False
    assert report.credentials_read is False
    assert report.network_accessed is False
    assert report.order_api_invoked is False


def test_alpaca_batch_import_requires_rights_and_maps_sip_fields(tmp_path: Path) -> None:
    root = tmp_path / "store"
    source_dir = tmp_path / "alpaca"
    source = _write_alpaca_sip_file(
        source_dir / "alpaca-sip-SPY-202607.json.gz",
        date(2026, 7, 2),
    )
    missing = import_research_data_batch(
        ResearchDataBatchImportRequest(
            source_dir=source_dir.as_posix(),
            root_path=root.as_posix(),
            vendor="alpaca_sip",
            kind=ResearchSampleKind.MINUTE_BARS,
            pattern="*.json.gz",
            vendor_decision_report_path=(tmp_path / "missing.json").as_posix(),
        )
    )
    assert missing.ok is False
    assert "vendor-decision report" in missing.errors[0]

    decision = _write_alpaca_vendor_decision(tmp_path / "alpaca-decision.json")
    report = import_research_data_batch(
        ResearchDataBatchImportRequest(
            source_dir=source_dir.as_posix(),
            root_path=root.as_posix(),
            vendor="alpaca_sip",
            kind=ResearchSampleKind.MINUTE_BARS,
            pattern="*.json.gz",
            vendor_decision_report_path=decision.as_posix(),
        )
    )

    assert report.ok is True
    assert report.succeeded_count == 1
    assert report.source_files == [source.as_posix()]
    parquet_path = next(root.rglob("*.parquet"))
    table = pq.read_table(parquet_path)
    assert table.schema.metadata[b"source"] == b"alpaca_sip"
    assert table.schema.metadata[b"vendor_decision_sha256"].startswith(b"sha256:")
    assert table.column("transactions")[0].as_py() == 10
    assert table.column("vwap")[0].as_py() == Decimal("500.01000000")


def test_catalog_module_remains_broker_order_and_network_free() -> None:
    source = Path("src/trader/data/research_catalog.py").read_text(encoding="utf-8")
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "ibapi",
        "requests",
        "httpx",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
    ):
        assert forbidden not in source


def test_catalog_reports_render_and_commands_are_registered(tmp_path: Path) -> None:
    root = tmp_path / "store"
    source = _write_massive_file(tmp_path / "source/2026-07-02.csv.gz", date(2026, 7, 2))
    assert ingest_massive_minute_file(_minute_request(source, root)).ok is True
    actions = _write_actions(tmp_path / "source/actions.csv", [])
    assert _ingest_actions(actions, root, "2026-07-02", "2026-07-02").ok is True
    derived = derive_research_views(ResearchDerivedViewRequest(root_path=root.as_posix()))
    loaded = load_research_catalog(
        ResearchCatalogLoadRequest(root_path=root.as_posix())
    )

    assert "Derived Research Views" in markdown_summary(derived.model_dump(mode="json"))
    assert "Dataset fingerprint" in markdown_summary(loaded.model_dump(mode="json"))
    runner = CliRunner()
    for command in (
        "research-data-import-batch",
        "research-data-derive",
        "research-catalog-load",
    ):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0


def _minute_request(source: Path, root: Path) -> ResearchDataIngestRequest:
    return ResearchDataIngestRequest(
        source_path=source.as_posix(),
        root_path=root.as_posix(),
    )


def _ingest_actions(
    source: Path,
    root: Path,
    coverage_start: str,
    coverage_end: str,
):
    return ingest_corporate_action_file(
        ResearchCorporateActionIngestRequest(
            source_path=source.as_posix(),
            root_path=root.as_posix(),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )
    )


def _write_massive_file(
    path: Path,
    session_date: date,
    *,
    close_offset: Decimal = Decimal("0"),
) -> Path:
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, str]] = []
    for index, timestamp in enumerate(calendar.session_minutes(session_date)):
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, mode="wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_MASSIVE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path.resolve()


def _write_alpaca_sip_file(path: Path, session_date: date) -> Path:
    calendar = xcals.get_calendar("XNYS")
    bars: list[dict[str, object]] = []
    for index, timestamp in enumerate(calendar.session_minutes(session_date)):
        event_time = timestamp.to_pydatetime()
        open_ = Decimal("500") + Decimal(index) / Decimal("100")
        close = open_ + Decimal("0.02")
        bars.append(
            {
                "t": event_time.isoformat().replace("+00:00", "Z"),
                "o": str(open_),
                "h": str(close + Decimal("0.01")),
                "l": str(open_ - Decimal("0.01")),
                "c": str(close),
                "v": 1000 + index,
                "n": 10 + index,
                "vw": str(open_ + Decimal("0.01")),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, mode="wt", encoding="utf-8") as stream:
        json.dump(
            {
                "schema_version": 1,
                "source": "alpaca_sip",
                "symbol": "SPY",
                "feed": "sip",
                "timeframe": "1Min",
                "adjustment": "raw",
                "sort": "asc",
                "bars": bars,
            },
            stream,
        )
    return path.resolve()


def _write_alpaca_vendor_decision(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "manifest_path": "local/alpaca-decision.json",
                "candidate_results": [
                    {
                        "vendor": "alpaca_sip",
                        "weighted_score": "90",
                        "three_year_tco_usd": "0",
                        "estimated_storage_gb": "25",
                        "written_evidence_sha256": ["sha256:" + "a" * 64],
                        "rights_gate_passed": True,
                        "bakeoff_gate_passed": True,
                        "budget_gate_passed": True,
                        "eligible": True,
                        "selected": True,
                    }
                ],
                "selected_vendor": "alpaca_sip",
                "procurement_blocked": False,
                "final_status": "completed",
            }
        ),
        encoding="utf-8",
    )
    return path.resolve()


def _write_daily(
    path: Path,
    rows: list[tuple[str, str, str, str, str, str]],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_DAILY_FIELDS)
        writer.writeheader()
        for session, open_, high, low, close, volume in rows:
            writer.writerow(
                {
                    "symbol": "SPY",
                    "timestamp": datetime.combine(
                        date.fromisoformat(session),
                        datetime.min.time(),
                        tzinfo=UTC,
                    ).isoformat(),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )
    return path.resolve()


def _write_actions(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_ACTION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path.resolve()
