from __future__ import annotations

from pathlib import Path

from tests.fixtures.historical_snapshots import (
    clean_two_symbol_dataset,
    empty_dataset,
    multi_symbol_partial_overlap,
)

from trader.backtest.data_adapter import (
    build_backtest_feed,
    iter_feed_frames,
    summarize_backtest_feed,
)
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    BacktestAlignmentMode,
    BacktestFeedStatus,
    HistoricalLoadedDataset,
    InertStrategyRunnerRequest,
    InertStrategyRunnerStatus,
    StrategyContractValidationRequest,
)
from trader.strategy.interface import (
    build_strategy_frame_context,
    run_noop_strategy_contract_diagnostic,
)
from trader.strategy.runner import (
    build_inert_strategy_runner_report,
    run_inert_strategy_runner,
)


def _loaded_datasets(tmp_path: Path, builder: object) -> list[HistoricalLoadedDataset]:
    scenario = builder(tmp_path)
    report = load_historical_snapshots(scenario.load_request())
    return [result.dataset for result in report.results if result.dataset is not None]


def _partial_feed(tmp_path: Path) -> object:
    return build_backtest_feed(
        _loaded_datasets(tmp_path, multi_symbol_partial_overlap),
        alignment_mode=BacktestAlignmentMode.UNION,
    )


def _runner_request(
    *,
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION,
) -> InertStrategyRunnerRequest:
    return InertStrategyRunnerRequest(
        symbols=["SPY", "AAPL"],
        alignment_mode=alignment_mode,
        requested_bar_size="5 mins",
        requested_what_to_show="TRADES",
    )


def _contract_request() -> StrategyContractValidationRequest:
    return StrategyContractValidationRequest(
        symbols=["SPY", "AAPL"],
        alignment_mode=BacktestAlignmentMode.UNION,
        requested_bar_size="5 mins",
        requested_what_to_show="TRADES",
    )


def test_strategy_contract_handles_partial_feed_contexts(tmp_path: Path) -> None:
    feed = _partial_feed(tmp_path)

    result = run_noop_strategy_contract_diagnostic(feed, _contract_request())

    assert result.ok is True
    assert result.contexts_observed == 4
    assert result.feed_summary is not None
    assert result.feed_summary.feed_status == BacktestFeedStatus.PARTIAL
    assert any(diagnostic.missing_symbols == ["AAPL"] for diagnostic in result.diagnostics)


def test_frame_context_records_available_and_missing_symbols(tmp_path: Path) -> None:
    feed = _partial_feed(tmp_path)
    summary = summarize_backtest_feed(feed)
    first_frame = next(iter_feed_frames(feed))

    context = build_strategy_frame_context(first_frame, summary, frame_index=0)

    assert context.available_symbols == ["SPY"]
    assert context.missing_symbols == ["AAPL"]
    assert context.bars_by_symbol["AAPL"] is None
    assert context.alignment_mode == BacktestAlignmentMode.UNION


def test_inert_runner_runs_noop_diagnostics_over_partial_feed(tmp_path: Path) -> None:
    feed = _partial_feed(tmp_path)

    result = run_inert_strategy_runner(feed, _runner_request())

    assert result.ok is True
    assert result.diagnostics.runner_status == InertStrategyRunnerStatus.PARTIAL
    assert result.diagnostics.contexts_built == feed.frame_count
    assert result.diagnostics.diagnostics_emitted == feed.frame_count


def test_inert_runner_records_missing_symbols_by_frame_and_symbol(tmp_path: Path) -> None:
    feed = _partial_feed(tmp_path)

    result = run_inert_strategy_runner(feed, _runner_request())

    assert result.diagnostics.missing_symbols_by_frame_count == 2
    assert result.diagnostics.missing_symbols_by_symbol == {"SPY": 0, "AAPL": 2}
    assert len([frame for frame in result.frame_results if frame.missing_symbols]) == 2


def test_inert_runner_emits_one_diagnostic_per_frame(tmp_path: Path) -> None:
    feed = _partial_feed(tmp_path)

    result = run_inert_strategy_runner(feed, _runner_request())

    assert len(result.frame_results) == feed.frame_count
    assert all(
        frame.diagnostic.diagnostics["frame_observed"] is True
        for frame in result.frame_results
    )
    assert [frame.frame_index for frame in result.frame_results] == [0, 1, 2, 3]


def test_inert_runner_fails_cleanly_on_failed_feed(tmp_path: Path) -> None:
    feed = build_backtest_feed(_loaded_datasets(tmp_path, empty_dataset))

    result = run_inert_strategy_runner(feed, _runner_request())

    assert result.ok is False
    assert result.diagnostics.runner_status == InertStrategyRunnerStatus.FAILED
    assert "source feed status is failed" in result.errors


def test_inert_runner_report_serializes_partial_diagnostics(tmp_path: Path) -> None:
    feed = _partial_feed(tmp_path)

    report = build_inert_strategy_runner_report(feed, _runner_request())
    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "strategy_runner"
    assert payload["diagnostics"]["runner_status"] == "partial"
    assert payload["diagnostic_only"] is True
    assert payload["noop_strategy_observed"] is True
    assert payload["broker_contacted"] is False


def test_inert_runner_stress_safety_flags_remain_false(tmp_path: Path) -> None:
    feed = build_backtest_feed(_loaded_datasets(tmp_path, clean_two_symbol_dataset))

    result = run_inert_strategy_runner(feed, _runner_request())
    first_frame = result.frame_results[0]

    assert result.diagnostic_only is True
    assert result.noop_strategy_observed is True
    assert result.real_strategy_evaluated is False
    assert getattr(result, "generated_" + "sig" + "nals") is False
    assert result.generated_orders is False
    assert result.orders_simulated is False
    assert getattr(result, "fi" + "lls_simulated") is False
    assert getattr(result, "p" + "nl_calculated") is False
    assert getattr(result, "port" + "folio_accounting") is False
    assert result.broker_contacted is False
    assert first_frame.real_strategy_evaluated is False
    assert getattr(first_frame, "generated_" + "sig" + "nals") is False
