from __future__ import annotations

from pathlib import Path

from tests.fixtures.historical_snapshots import (
    duplicate_timestamps,
    empty_dataset,
    multi_symbol_partial_overlap,
    single_symbol_missing_bars,
)

from trader.backtest.data_adapter import (
    build_backtest_feed,
    build_backtest_feed_report,
    iter_feed_frames,
)
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    BacktestAlignmentMode,
    BacktestDataAdapterRequest,
    BacktestFeedStatus,
    HistoricalLoadedDataset,
    HistoricalLoaderReport,
)


def _datasets(report: HistoricalLoaderReport) -> list[HistoricalLoadedDataset]:
    return [result.dataset for result in report.results if result.dataset is not None]


def test_union_alignment_includes_all_timestamps(tmp_path: Path) -> None:
    scenario = multi_symbol_partial_overlap(tmp_path)
    report = load_historical_snapshots(scenario.load_request())

    feed = build_backtest_feed(
        _datasets(report),
        alignment_mode=BacktestAlignmentMode.UNION,
    )

    assert feed.feed_status == BacktestFeedStatus.PARTIAL
    assert feed.frame_count == 4
    assert feed.total_bars == 6
    assert feed.missing_bars_by_symbol == {"SPY": 0, "AAPL": 2}
    assert feed.frames[0].bars_by_symbol["AAPL"] is None
    assert feed.frames[-1].bars_by_symbol["AAPL"] is None


def test_intersection_alignment_includes_only_shared_timestamps(tmp_path: Path) -> None:
    scenario = multi_symbol_partial_overlap(tmp_path)
    report = load_historical_snapshots(scenario.load_request())

    feed = build_backtest_feed(
        _datasets(report),
        alignment_mode=BacktestAlignmentMode.INTERSECTION,
    )

    assert feed.feed_status == BacktestFeedStatus.READY
    assert feed.frame_count == 2
    assert feed.total_bars == 4
    assert feed.missing_bars_by_symbol == {"SPY": 0, "AAPL": 0}
    assert all(not frame.missing_symbols for frame in feed.frames)


def test_missing_bars_are_explicit_in_union_mode(tmp_path: Path) -> None:
    scenario = multi_symbol_partial_overlap(tmp_path)
    report = load_historical_snapshots(scenario.load_request())

    feed = build_backtest_feed(_datasets(report))

    missing_frames = [frame for frame in feed.frames if "AAPL" in frame.missing_symbols]
    assert len(missing_frames) == 2
    assert all(frame.bars_by_symbol["AAPL"] is None for frame in missing_frames)
    assert all(
        point.missing
        for frame in missing_frames
        for point in frame.points
        if point.symbol == "AAPL"
    )


def test_partial_dataset_produces_partial_feed_status(tmp_path: Path) -> None:
    scenario = single_symbol_missing_bars(tmp_path)
    report = load_historical_snapshots(scenario.load_request())

    feed = build_backtest_feed(_datasets(report))

    assert feed.feed_status == BacktestFeedStatus.PARTIAL
    assert "SPY source dataset status is partial" in feed.warnings
    assert feed.broker_contacted is False


def test_failed_dataset_fails_feed_cleanly(tmp_path: Path) -> None:
    scenario = empty_dataset(tmp_path)
    report = load_historical_snapshots(scenario.load_request())

    feed = build_backtest_feed(_datasets(report))

    assert feed.feed_status == BacktestFeedStatus.FAILED
    assert "SPY source dataset status is failed" in feed.errors
    assert "SPY source dataset contains no bars" in feed.errors


def test_duplicate_dataset_records_feed_duplicate_count(tmp_path: Path) -> None:
    scenario = duplicate_timestamps(tmp_path)
    report = load_historical_snapshots(scenario.load_request())

    feed = build_backtest_feed(_datasets(report))

    assert feed.feed_status == BacktestFeedStatus.PARTIAL
    assert feed.duplicate_timestamps_by_symbol["SPY"] == 1
    assert "SPY duplicate timestamps detected: 1" in feed.warnings


def test_frame_ordering_remains_deterministic(tmp_path: Path) -> None:
    scenario = multi_symbol_partial_overlap(tmp_path)
    report = load_historical_snapshots(scenario.load_request())
    feed = build_backtest_feed(_datasets(report))

    timestamps = [frame.timestamp for frame in iter_feed_frames(feed)]

    assert timestamps == sorted(timestamps)
    assert timestamps == [frame.timestamp for frame in feed.frames]


def test_feed_stress_report_serializes_without_execution_flags(tmp_path: Path) -> None:
    scenario = multi_symbol_partial_overlap(tmp_path)
    loader_report = load_historical_snapshots(scenario.load_request())
    request = BacktestDataAdapterRequest(
        symbols=scenario.symbols,
        base_data_path=tmp_path.as_posix(),
    )

    report = build_backtest_feed_report(loader_report, request)
    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "backtest_feed"
    assert payload["broker_contacted"] is False
    assert payload["order_routing_enabled"] is False
    assert payload["no_order_guarantee"] is True
    assert "No strategy evaluation" in payload["no_strategy_execution_statement"]
