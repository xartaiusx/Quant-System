"""Broker-free inert no-op strategy runner diagnostics."""

from __future__ import annotations

from trader.backtest.data_adapter import iter_feed_frames, summarize_backtest_feed
from trader.models import (
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    InertStrategyFrameResult,
    InertStrategyRunnerDiagnostics,
    InertStrategyRunnerReport,
    InertStrategyRunnerRequest,
    InertStrategyRunnerResult,
    InertStrategyRunnerStatus,
    StrategyContractDiagnostic,
)
from trader.strategy.interface import NoOpStrategyContract, build_strategy_frame_context


def run_inert_strategy_runner(
    feed: BacktestDataFeed,
    request: InertStrategyRunnerRequest,
) -> InertStrategyRunnerResult:
    """Replay feed frames through the no-op diagnostic contract only."""

    contract = NoOpStrategyContract()
    feed_summary = summarize_backtest_feed(feed)
    warnings = list(feed.warnings)
    errors = list(feed.errors)
    frame_results: list[InertStrategyFrameResult] = []

    if feed.feed_status == BacktestFeedStatus.FAILED:
        errors.append("source feed status is failed")
    if not feed.frames:
        errors.append("source feed contains no frames")

    if not errors:
        for index, frame in enumerate(iter_feed_frames(feed)):
            context = build_strategy_frame_context(
                frame,
                feed_summary,
                frame_index=index,
            )
            diagnostic = contract.observe(context)
            frame_results.append(
                _frame_result(frame, index=index, diagnostic=diagnostic)
            )
            warnings.extend(diagnostic.warnings)
            errors.extend(diagnostic.errors)

    unique_warnings = list(dict.fromkeys(warnings))
    unique_errors = list(dict.fromkeys(errors))
    if unique_errors:
        runner_status = InertStrategyRunnerStatus.FAILED
    elif feed.feed_status == BacktestFeedStatus.PARTIAL:
        runner_status = InertStrategyRunnerStatus.PARTIAL
    else:
        runner_status = InertStrategyRunnerStatus.COMPLETED

    diagnostics = _diagnostics(
        feed,
        request,
        frame_results=frame_results,
        runner_status=runner_status,
        warnings=unique_warnings,
        errors=unique_errors,
        strategy_name=contract.metadata.strategy_name,
        strategy_version=contract.metadata.strategy_version,
    )
    return InertStrategyRunnerResult(
        ok=runner_status != InertStrategyRunnerStatus.FAILED,
        request=request,
        metadata=contract.metadata,
        feed_summary=feed_summary,
        diagnostics=diagnostics,
        frame_results=frame_results,
        warnings=unique_warnings,
        errors=unique_errors,
    )


def summarize_inert_strategy_runner(
    result: InertStrategyRunnerResult,
) -> InertStrategyRunnerDiagnostics:
    """Return runner diagnostics for report surfaces."""

    return result.diagnostics


def validate_inert_strategy_runner_result(result: InertStrategyRunnerResult) -> list[str]:
    """Validate inert runner output without invoking external systems."""

    errors = list(result.errors)
    timestamps = [frame_result.timestamp for frame_result in result.frame_results]
    if timestamps != sorted(timestamps):
        errors.append("strategy runner frame diagnostics are not sorted by timestamp")
    if result.ok and not result.frame_results:
        errors.append("successful strategy runner has no frame diagnostics")
    if result.diagnostics.contexts_built != len(result.frame_results):
        errors.append("strategy runner context count does not match frame diagnostics")
    if result.diagnostics.diagnostics_emitted != len(result.frame_results):
        errors.append("strategy runner diagnostic count does not match frame diagnostics")
    return list(dict.fromkeys(errors))


def build_inert_strategy_runner_report(
    feed: BacktestDataFeed,
    request: InertStrategyRunnerRequest,
) -> InertStrategyRunnerReport:
    """Run the no-op diagnostic runner and build a serializable report."""

    result = run_inert_strategy_runner(feed, request)
    validation_errors = validate_inert_strategy_runner_result(result)
    errors = list(dict.fromkeys([*result.errors, *validation_errors]))
    if errors and result.ok:
        result = result.model_copy(
            update={
                "ok": False,
                "errors": errors,
                "diagnostics": result.diagnostics.model_copy(
                    update={
                        "runner_status": InertStrategyRunnerStatus.FAILED,
                        "errors": errors,
                    }
                ),
            }
        )
    diagnostics = summarize_inert_strategy_runner(result)
    return InertStrategyRunnerReport(
        ok=result.ok,
        request=request,
        metadata=result.metadata,
        symbols_requested=request.symbols,
        feed_summary=result.feed_summary,
        result=result,
        diagnostics=diagnostics,
        frame_results=result.frame_results,
        warnings=result.warnings,
        errors=errors,
        final_status=_status_value(diagnostics.runner_status),
    )


class InertStrategyRunner:
    """Small wrapper around the broker-free no-op diagnostic runner."""

    def run(
        self,
        feed: BacktestDataFeed,
        request: InertStrategyRunnerRequest,
    ) -> InertStrategyRunnerResult:
        return run_inert_strategy_runner(feed, request)


def _frame_result(
    frame: BacktestFeedFrame,
    *,
    index: int,
    diagnostic: StrategyContractDiagnostic,
) -> InertStrategyFrameResult:
    available_symbols = [
        symbol for symbol, bar in sorted(frame.bars_by_symbol.items()) if bar is not None
    ]
    return InertStrategyFrameResult(
        strategy_name=diagnostic.strategy_name,
        strategy_version=diagnostic.strategy_version,
        timestamp=frame.timestamp,
        frame_index=index,
        available_symbols=available_symbols,
        missing_symbols=sorted(frame.missing_symbols),
        diagnostic=diagnostic,
    )


def _diagnostics(
    feed: BacktestDataFeed,
    request: InertStrategyRunnerRequest,
    *,
    frame_results: list[InertStrategyFrameResult],
    runner_status: InertStrategyRunnerStatus,
    warnings: list[str],
    errors: list[str],
    strategy_name: str,
    strategy_version: str,
) -> InertStrategyRunnerDiagnostics:
    missing_by_symbol = {
        symbol: sum(1 for item in frame_results if symbol in item.missing_symbols)
        for symbol in feed.symbols
    }
    return InertStrategyRunnerDiagnostics(
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        symbols=feed.symbols,
        alignment_mode=request.alignment_mode,
        feed_status=feed.feed_status,
        runner_status=runner_status,
        frame_count=len(frame_results),
        contexts_built=len(frame_results),
        diagnostics_emitted=len(frame_results),
        first_timestamp=frame_results[0].timestamp if frame_results else None,
        last_timestamp=frame_results[-1].timestamp if frame_results else None,
        missing_symbols_by_frame_count=sum(
            1 for item in frame_results if item.missing_symbols
        ),
        missing_symbols_by_symbol=missing_by_symbol,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )


def _status_value(value: InertStrategyRunnerStatus | str) -> str:
    return str(getattr(value, "value", value))
