from __future__ import annotations

from pathlib import Path

from tests.fixtures.historical_snapshots import (
    clean_two_symbol_dataset,
    empty_dataset,
    multi_symbol_partial_overlap,
)

from trader.backtest.data_adapter import build_backtest_feed
from trader.backtest.engine import run_backtest_engine, validate_backtest_run
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    BacktestAlignmentMode,
    BacktestRunRequest,
    BacktestRunStatus,
    HistoricalLoadedDataset,
)


def _loaded_datasets(tmp_path: Path, builder: object) -> list[HistoricalLoadedDataset]:
    scenario = builder(tmp_path)
    report = load_historical_snapshots(scenario.load_request())
    return [result.dataset for result in report.results if result.dataset is not None]


def _request(
    *,
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION,
) -> BacktestRunRequest:
    return BacktestRunRequest(
        symbols=["SPY", "AAPL"],
        alignment_mode=alignment_mode,
        requested_bar_size="5 mins",
        requested_what_to_show="TRADES",
    )


def test_ready_feed_completes(tmp_path: Path) -> None:
    feed = build_backtest_feed(_loaded_datasets(tmp_path, clean_two_symbol_dataset))

    result = run_backtest_engine(feed, _request())

    assert result.ok is True
    assert result.diagnostics.run_status == BacktestRunStatus.COMPLETED
    assert result.diagnostics.frame_count == 3
    assert result.diagnostics.total_bars_observed == 6
    assert result.broker_contacted is False


def test_partial_feed_completes_with_warnings(tmp_path: Path) -> None:
    feed = build_backtest_feed(
        _loaded_datasets(tmp_path, multi_symbol_partial_overlap),
        alignment_mode=BacktestAlignmentMode.UNION,
    )

    result = run_backtest_engine(feed, _request())

    assert result.ok is True
    assert result.diagnostics.run_status == BacktestRunStatus.PARTIAL
    assert result.diagnostics.frames_with_missing_bars == 2
    assert result.diagnostics.missing_bars_by_symbol["AAPL"] == 2
    assert "AAPL missing bars in aligned feed: 2" in result.warnings


def test_failed_feed_fails_cleanly(tmp_path: Path) -> None:
    feed = build_backtest_feed(_loaded_datasets(tmp_path, empty_dataset))

    result = run_backtest_engine(feed, _request())

    assert result.ok is False
    assert result.diagnostics.run_status == BacktestRunStatus.FAILED
    assert "source feed status is failed" in result.errors
    assert "source feed contains no frames" in result.errors


def test_run_observations_remain_deterministic(tmp_path: Path) -> None:
    feed = build_backtest_feed(_loaded_datasets(tmp_path, clean_two_symbol_dataset))

    result = run_backtest_engine(feed, _request())

    timestamps = [observation.timestamp for observation in result.observations]
    assert timestamps == sorted(timestamps)
    assert [observation.frame_index for observation in result.observations] == [0, 1, 2]
    assert validate_backtest_run(result) == []


def test_missing_bars_are_counted_in_observations(tmp_path: Path) -> None:
    feed = build_backtest_feed(
        _loaded_datasets(tmp_path, multi_symbol_partial_overlap),
        alignment_mode=BacktestAlignmentMode.UNION,
    )

    result = run_backtest_engine(feed, _request())
    missing_observations = [
        observation
        for observation in result.observations
        if observation.missing_bar_count
    ]

    assert len(missing_observations) == 2
    assert all(observation.symbols_missing == ["AAPL"] for observation in missing_observations)
    assert result.diagnostics.observations_count == 4


def test_intersection_feed_has_no_missing_observations(tmp_path: Path) -> None:
    feed = build_backtest_feed(
        _loaded_datasets(tmp_path, multi_symbol_partial_overlap),
        alignment_mode=BacktestAlignmentMode.INTERSECTION,
    )

    result = run_backtest_engine(
        feed,
        _request(alignment_mode=BacktestAlignmentMode.INTERSECTION),
    )

    assert result.diagnostics.run_status == BacktestRunStatus.COMPLETED
    assert result.diagnostics.frame_count == 2
    assert result.diagnostics.frames_with_missing_bars == 0


def test_engine_stress_safety_flags_remain_false(tmp_path: Path) -> None:
    feed = build_backtest_feed(_loaded_datasets(tmp_path, clean_two_symbol_dataset))

    result = run_backtest_engine(feed, _request())

    assert result.strategy_evaluated is False
    assert result.orders_simulated is False
    assert getattr(result, "p" + "nl_calculated") is False
    assert result.diagnostics.strategy_evaluated is False
    assert result.diagnostics.orders_simulated is False
    assert getattr(result.diagnostics, "p" + "nl_calculated") is False
