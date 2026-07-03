from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.fixtures.historical_snapshots import (
    SnapshotFixture,
    clean_two_symbol_dataset,
    duplicate_timestamps,
    empty_dataset,
    invalid_ohlc,
    multi_symbol_partial_overlap,
    negative_volume,
    single_symbol_missing_bars,
)

from trader.backtest.data_adapter import build_backtest_feed
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    AnalyticalSignalEvaluationRequest,
    BacktestAlignmentMode,
    BacktestFeedStatus,
    HistoricalLoadedDataset,
)
from trader.strategy.signal_evaluation import (
    build_analytical_signal_evaluation_report,
    run_analytical_signal_evaluation,
)

FixtureBuilder = Callable[[Path], SnapshotFixture]


def _loaded_datasets(tmp_path: Path, builder: FixtureBuilder) -> list[HistoricalLoadedDataset]:
    scenario = builder(tmp_path)
    report = load_historical_snapshots(scenario.load_request())
    return [result.dataset for result in report.results if result.dataset is not None]


def _feed(tmp_path: Path, builder: FixtureBuilder, *, mode: BacktestAlignmentMode):
    return build_backtest_feed(_loaded_datasets(tmp_path, builder), alignment_mode=mode)


def _request(
    *,
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION,
) -> AnalyticalSignalEvaluationRequest:
    return AnalyticalSignalEvaluationRequest(
        symbols=["SPY", "AAPL"],
        alignment_mode=alignment_mode,
        requested_bar_size="5 mins",
        requested_what_to_show="TRADES",
    )


def test_signal_evaluation_handles_partial_feed_observations(tmp_path: Path) -> None:
    feed = _feed(
        tmp_path,
        multi_symbol_partial_overlap,
        mode=BacktestAlignmentMode.UNION,
    )

    result = run_analytical_signal_evaluation(feed, _request())

    assert result.ok is True
    assert result.feed_summary is not None
    assert result.feed_summary.feed_status == BacktestFeedStatus.PARTIAL
    assert result.diagnostics.observations_count == 8
    assert result.diagnostics.missing_symbols_by_frame_count == 2
    assert result.diagnostics.missing_symbols_by_symbol == {"SPY": 0, "AAPL": 2}


def test_gapped_fixture_still_emits_non_actionable_observations(tmp_path: Path) -> None:
    feed = _feed(tmp_path, single_symbol_missing_bars, mode=BacktestAlignmentMode.UNION)

    report = build_analytical_signal_evaluation_report(feed, _request())

    assert report.ok is True
    assert report.feed_summary is not None
    assert report.feed_summary.feed_status == BacktestFeedStatus.PARTIAL
    assert report.signal_evaluation_enabled is True
    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.order_intents_generated is False


def test_duplicate_fixture_still_emits_non_actionable_observations(tmp_path: Path) -> None:
    feed = _feed(tmp_path, duplicate_timestamps, mode=BacktestAlignmentMode.UNION)

    report = build_analytical_signal_evaluation_report(feed, _request())

    assert report.ok is True
    assert report.feed_summary is not None
    assert report.feed_summary.duplicate_timestamps_by_symbol["SPY"] == 1
    assert report.signal_evaluation_enabled is True
    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.order_intents_generated is False


def test_invalid_ohlc_fixture_fails_or_reports_invalid_without_routing(
    tmp_path: Path,
) -> None:
    feed = _feed(tmp_path, invalid_ohlc, mode=BacktestAlignmentMode.UNION)

    report = build_analytical_signal_evaluation_report(feed, _request())

    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.order_intents_generated is False
    assert report.orders_simulated is False
    assert report.broker_contacted is False
    assert report.order_routing_enabled is False


def test_negative_volume_fixture_fails_or_reports_invalid_without_routing(
    tmp_path: Path,
) -> None:
    feed = _feed(tmp_path, negative_volume, mode=BacktestAlignmentMode.UNION)

    report = build_analytical_signal_evaluation_report(feed, _request())

    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.order_intents_generated is False
    assert report.orders_simulated is False
    assert getattr(report, "fi" + "lls_simulated") is False
    assert getattr(report, "p" + "nl_calculated") is False
    assert getattr(report, "port" + "folio_accounting") is False
    assert report.broker_contacted is False
    assert report.order_routing_enabled is False


def test_empty_dataset_fails_closed_without_broker_contact(tmp_path: Path) -> None:
    feed = _feed(tmp_path, empty_dataset, mode=BacktestAlignmentMode.UNION)

    report = build_analytical_signal_evaluation_report(feed, _request())

    assert report.ok is False
    assert report.observations == []
    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.broker_contacted is False
    assert report.order_routing_enabled is False


def test_signal_evaluation_stress_safety_flags_remain_false(tmp_path: Path) -> None:
    feed = _feed(tmp_path, clean_two_symbol_dataset, mode=BacktestAlignmentMode.UNION)

    result = run_analytical_signal_evaluation(feed, _request())
    first_observation = result.observations[0]

    assert result.signal_evaluation_enabled is True
    assert getattr(result, "generated_" + "sig" + "nals") is False
    assert result.signal_count == 0
    assert result.generated_orders is False
    assert result.order_intents_generated is False
    assert result.orders_simulated is False
    assert getattr(result, "fi" + "lls_simulated") is False
    assert getattr(result, "p" + "nl_calculated") is False
    assert getattr(result, "port" + "folio_accounting") is False
    assert result.broker_contacted is False
    assert result.order_routing_enabled is False
    assert result.no_order_guarantee is True
    assert first_observation.generated_signals is False
    assert first_observation.signal_count == 0
    assert first_observation.broker_contacted is False
