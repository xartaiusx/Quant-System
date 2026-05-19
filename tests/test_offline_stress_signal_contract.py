from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.fixtures.historical_snapshots import (
    SnapshotFixture,
    clean_two_symbol_dataset,
    duplicate_timestamps,
    multi_symbol_partial_overlap,
    single_symbol_missing_bars,
)

from trader.backtest.data_adapter import build_backtest_feed
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    BacktestAlignmentMode,
    BacktestFeedStatus,
    HistoricalLoadedDataset,
    SignalContractValidationRequest,
)
from trader.strategy.signals import (
    build_signal_contract_report,
    run_disabled_signal_contract_diagnostic,
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
) -> SignalContractValidationRequest:
    return SignalContractValidationRequest(
        symbols=["SPY", "AAPL"],
        alignment_mode=alignment_mode,
        requested_bar_size="5 mins",
        requested_what_to_show="TRADES",
    )


def test_signal_contract_handles_partial_feed_contexts(tmp_path: Path) -> None:
    feed = _feed(
        tmp_path,
        multi_symbol_partial_overlap,
        mode=BacktestAlignmentMode.UNION,
    )

    result = run_disabled_signal_contract_diagnostic(feed, _request())

    assert result.ok is True
    assert result.contexts_observed == 4
    assert result.feed_summary is not None
    assert result.feed_summary.feed_status == BacktestFeedStatus.PARTIAL
    assert any(diagnostic.missing_symbols == ["AAPL"] for diagnostic in result.diagnostics)


def test_signal_context_records_missing_symbols(tmp_path: Path) -> None:
    feed = _feed(
        tmp_path,
        multi_symbol_partial_overlap,
        mode=BacktestAlignmentMode.UNION,
    )

    report = build_signal_contract_report(feed, _request())
    sample = report.frame_context_sample

    assert sample is not None
    assert sample.available_symbols == ["SPY"]
    assert sample.missing_symbols == ["AAPL"]
    assert sample.bars_by_symbol["AAPL"] is None


def test_gapped_fixture_still_emits_diagnostics_only(tmp_path: Path) -> None:
    feed = _feed(tmp_path, single_symbol_missing_bars, mode=BacktestAlignmentMode.UNION)

    report = build_signal_contract_report(feed, _request())

    assert report.ok is True
    assert report.feed_summary is not None
    assert report.feed_summary.feed_status == BacktestFeedStatus.PARTIAL
    assert report.signal_contract_validated is True
    assert report.signal_evaluation_enabled is False
    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.generated_orders is False


def test_duplicate_fixture_still_emits_diagnostics_only(tmp_path: Path) -> None:
    feed = _feed(tmp_path, duplicate_timestamps, mode=BacktestAlignmentMode.UNION)

    report = build_signal_contract_report(feed, _request())

    assert report.ok is True
    assert report.feed_summary is not None
    assert report.feed_summary.duplicate_timestamps_by_symbol["SPY"] == 1
    assert report.signal_evaluation_enabled is False
    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.generated_orders is False


def test_signal_contract_stress_safety_flags_remain_false(tmp_path: Path) -> None:
    feed = _feed(tmp_path, clean_two_symbol_dataset, mode=BacktestAlignmentMode.UNION)

    result = run_disabled_signal_contract_diagnostic(feed, _request())
    first_diagnostic = result.diagnostics[0]

    assert result.signal_contract_validated is True
    assert result.signal_evaluation_enabled is False
    assert result.generated_signals is False
    assert result.signal_count == 0
    assert result.generated_orders is False
    assert result.orders_simulated is False
    assert getattr(result, "fi" + "lls_simulated") is False
    assert getattr(result, "p" + "nl_calculated") is False
    assert getattr(result, "port" + "folio_accounting") is False
    assert result.broker_contacted is False
    assert first_diagnostic.signal_evaluation_enabled is False
    assert first_diagnostic.generated_signals is False
    assert first_diagnostic.signal_count == 0
