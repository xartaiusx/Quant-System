"""Broker-free backtest data-frame replay skeleton."""

from __future__ import annotations

from time import perf_counter

from trader.backtest.data_adapter import iter_feed_frames, summarize_backtest_feed
from trader.models import (
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    BacktestFrameObservation,
    BacktestRunDiagnostics,
    BacktestRunReport,
    BacktestRunRequest,
    BacktestRunResult,
    BacktestRunStatus,
)


def run_backtest_engine(
    feed: BacktestDataFeed,
    request: BacktestRunRequest,
) -> BacktestRunResult:
    """Replay feed frames and return diagnostics only."""

    started = perf_counter()
    warnings = list(feed.warnings)
    errors = list(feed.errors)
    observations: list[BacktestFrameObservation] = []

    if feed.feed_status == BacktestFeedStatus.FAILED:
        errors.append("source feed status is failed")
    if not feed.frames:
        errors.append("source feed contains no frames")

    if not errors:
        observations = [
            _observe_frame(frame, index=index)
            for index, frame in enumerate(iter_feed_frames(feed))
        ]

    if errors:
        run_status = BacktestRunStatus.FAILED
    elif feed.feed_status == BacktestFeedStatus.PARTIAL:
        run_status = BacktestRunStatus.PARTIAL
    else:
        run_status = BacktestRunStatus.COMPLETED

    diagnostics = _diagnostics(
        feed,
        request,
        observations=observations,
        run_status=run_status,
        elapsed_seconds=perf_counter() - started,
        warnings=warnings,
        errors=errors,
    )
    return BacktestRunResult(
        ok=run_status != BacktestRunStatus.FAILED,
        request=request,
        diagnostics=diagnostics,
        observations=observations,
        warnings=warnings,
        errors=errors,
    )


def summarize_backtest_run(result: BacktestRunResult) -> BacktestRunDiagnostics:
    """Return run diagnostics for report surfaces."""

    return result.diagnostics


def validate_backtest_run(result: BacktestRunResult) -> list[str]:
    """Validate replay result shape without invoking any external system."""

    errors = list(result.errors)
    observations = result.observations
    timestamps = [observation.timestamp for observation in observations]
    if timestamps != sorted(timestamps):
        errors.append("frame observations are not sorted by timestamp")
    if result.ok and not observations:
        errors.append("successful run has no frame observations")
    return list(dict.fromkeys(errors))


def build_backtest_run_report(
    feed: BacktestDataFeed,
    request: BacktestRunRequest,
) -> BacktestRunReport:
    """Run the frame replay skeleton and build a report."""

    result = run_backtest_engine(feed, request)
    validation_errors = validate_backtest_run(result)
    errors = list(dict.fromkeys([*result.errors, *validation_errors]))
    if errors and result.ok:
        result = result.model_copy(
            update={
                "ok": False,
                "errors": errors,
                "diagnostics": result.diagnostics.model_copy(
                    update={
                        "run_status": BacktestRunStatus.FAILED,
                        "errors": errors,
                    }
                ),
            }
        )
    diagnostics = summarize_backtest_run(result)
    return BacktestRunReport(
        ok=result.ok,
        request=request,
        symbols_requested=request.symbols,
        feed_summary=summarize_backtest_feed(feed),
        result=result,
        diagnostics=diagnostics,
        warnings=result.warnings,
        errors=errors,
        final_status=_status_value(diagnostics.run_status),
    )


class BacktestEngine:
    """Small wrapper around the broker-free frame replay skeleton."""

    def run(self, feed: BacktestDataFeed, request: BacktestRunRequest) -> BacktestRunResult:
        return run_backtest_engine(feed, request)


def _observe_frame(frame: BacktestFeedFrame, *, index: int) -> BacktestFrameObservation:
    present = [
        symbol
        for symbol, bar in sorted(frame.bars_by_symbol.items())
        if bar is not None
    ]
    missing = sorted(frame.missing_symbols)
    return BacktestFrameObservation(
        timestamp=frame.timestamp,
        frame_index=index,
        symbols_present=present,
        symbols_missing=missing,
        bar_count=len(present),
        missing_bar_count=len(missing),
    )


def _diagnostics(
    feed: BacktestDataFeed,
    request: BacktestRunRequest,
    *,
    observations: list[BacktestFrameObservation],
    run_status: BacktestRunStatus,
    elapsed_seconds: float,
    warnings: list[str],
    errors: list[str],
) -> BacktestRunDiagnostics:
    first_timestamp = observations[0].timestamp if observations else None
    last_timestamp = observations[-1].timestamp if observations else None
    return BacktestRunDiagnostics(
        symbols=feed.symbols,
        alignment_mode=feed.alignment_mode,
        requested_bar_size=request.requested_bar_size,
        requested_what_to_show=request.requested_what_to_show,
        feed_status=feed.feed_status,
        run_status=run_status,
        frame_count=len(observations),
        total_bars_observed=sum(observation.bar_count for observation in observations),
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        observations_count=len(observations),
        missing_bars_by_symbol=feed.missing_bars_by_symbol,
        frames_with_missing_bars=sum(
            1 for observation in observations if observation.missing_bar_count
        ),
        elapsed_seconds=elapsed_seconds,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )


def _status_value(value: BacktestRunStatus | str) -> str:
    return str(getattr(value, "value", value))
