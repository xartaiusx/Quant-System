from __future__ import annotations

from pathlib import Path

from tests.fixtures.historical_snapshots import (
    clean_two_symbol_dataset,
    duplicate_timestamps,
    empty_dataset,
    invalid_ohlc,
    malformed_jsonl_line,
    missing_bars_file,
    missing_manifest,
    negative_volume,
    single_symbol_missing_bars,
)

from trader.data.historical_loader import load_historical_snapshots, load_snapshot_entry
from trader.models import HistoricalLoadStatus


def test_clean_fixture_loads_as_ready(tmp_path: Path) -> None:
    scenario = clean_two_symbol_dataset(tmp_path)

    report = load_historical_snapshots(scenario.load_request())

    assert report.ok is True
    assert report.final_status == "loaded"
    assert {summary.symbol for summary in report.summaries} == {"SPY", "AAPL"}
    assert all(summary.load_status == HistoricalLoadStatus.LOADED for summary in report.summaries)
    assert all(summary.bars_count == 3 for summary in report.summaries)
    assert report.broker_contacted is False
    assert report.order_routing_enabled is False
    assert report.no_order_guarantee is True


def test_gapped_fixture_records_gap_diagnostics(tmp_path: Path) -> None:
    scenario = single_symbol_missing_bars(tmp_path)

    report = load_historical_snapshots(scenario.load_request())
    summary = report.summaries[0]

    assert report.final_status == "partial"
    assert summary.load_status == HistoricalLoadStatus.PARTIAL
    assert summary.missing_gap_count == 1
    assert summary.largest_gap_seconds == 900
    assert "timestamp gaps detected: 1" in summary.warnings


def test_duplicate_fixture_records_duplicate_diagnostics(tmp_path: Path) -> None:
    scenario = duplicate_timestamps(tmp_path)

    report = load_historical_snapshots(scenario.load_request())
    summary = report.summaries[0]

    assert summary.load_status == HistoricalLoadStatus.PARTIAL
    assert summary.duplicate_timestamps_count == 1
    assert "duplicate timestamps detected: 1" in summary.warnings


def test_invalid_ohlc_fixture_fails_cleanly(tmp_path: Path) -> None:
    scenario = invalid_ohlc(tmp_path)

    report = load_historical_snapshots(scenario.load_request())
    summary = report.summaries[0]

    assert report.ok is False
    assert summary.load_status == HistoricalLoadStatus.FAILED
    assert summary.invalid_ohlc_count == 1
    assert "invalid OHLC bars detected: 1" in summary.errors


def test_negative_volume_fixture_fails_cleanly(tmp_path: Path) -> None:
    scenario = negative_volume(tmp_path)

    report = load_historical_snapshots(scenario.load_request())
    summary = report.summaries[0]

    assert report.ok is False
    assert summary.load_status == HistoricalLoadStatus.FAILED
    assert summary.negative_volume_count == 1
    assert "negative-volume bars detected: 1" in summary.errors


def test_malformed_jsonl_non_strict_returns_partial(tmp_path: Path) -> None:
    scenario = malformed_jsonl_line(tmp_path)

    report = load_historical_snapshots(scenario.load_request(strict=False))
    summary = report.summaries[0]

    assert report.ok is True
    assert summary.load_status == HistoricalLoadStatus.PARTIAL
    assert summary.malformed_line_count == 1
    assert "malformed JSONL lines detected: 1" in summary.warnings


def test_malformed_jsonl_strict_fails(tmp_path: Path) -> None:
    scenario = malformed_jsonl_line(tmp_path)

    report = load_historical_snapshots(scenario.load_request(strict=True))
    summary = report.summaries[0]

    assert report.ok is False
    assert summary.load_status == HistoricalLoadStatus.FAILED
    assert summary.malformed_line_count == 1
    assert "malformed JSONL lines detected: 1" in summary.errors


def test_missing_manifest_fails_cleanly(tmp_path: Path) -> None:
    scenario = missing_manifest(tmp_path)
    assert scenario.missing_entry is not None

    result = load_snapshot_entry(
        scenario.missing_entry,
        request=scenario.load_request(),
    )

    assert result.load_status == HistoricalLoadStatus.FAILED
    assert result.issues[0].code == "missing_manifest"
    assert result.broker_contacted is False


def test_missing_bars_file_fails_cleanly(tmp_path: Path) -> None:
    scenario = missing_bars_file(tmp_path)

    report = load_historical_snapshots(scenario.load_request())
    result = report.results[0]

    assert report.ok is False
    assert result.load_status == HistoricalLoadStatus.FAILED
    assert result.issues[0].code == "missing_bars_file"


def test_empty_dataset_fails_cleanly(tmp_path: Path) -> None:
    scenario = empty_dataset(tmp_path)

    report = load_historical_snapshots(scenario.load_request())
    summary = report.summaries[0]

    assert report.ok is False
    assert summary.load_status == HistoricalLoadStatus.FAILED
    assert summary.bars_count == 0
    assert "dataset contains no loadable bars" in summary.errors


def test_loader_stress_report_serializes_diagnostics(tmp_path: Path) -> None:
    scenario = duplicate_timestamps(tmp_path)

    report = load_historical_snapshots(scenario.load_request())
    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "history_load"
    assert payload["broker_contacted"] is False
    assert payload["order_routing_enabled"] is False
    assert payload["no_order_guarantee"] is True
    assert payload["summaries"][0]["duplicate_timestamps_count"] == 1
