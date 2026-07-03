"""Broker-free analytical signal evaluation diagnostics."""

from __future__ import annotations

from decimal import Decimal

from trader.backtest.data_adapter import iter_feed_frames, summarize_backtest_feed
from trader.models import (
    AnalyticalSignalConditionState,
    AnalyticalSignalEvaluationDiagnostics,
    AnalyticalSignalEvaluationReport,
    AnalyticalSignalEvaluationRequest,
    AnalyticalSignalEvaluationResult,
    AnalyticalSignalEvaluationStatus,
    AnalyticalSignalEvaluatorMetadata,
    AnalyticalSignalObservation,
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedStatus,
    SignalEvaluationContext,
)
from trader.strategy.signals import build_signal_evaluation_context

EVALUATOR_NAME = "moving_average_relationship_diagnostic"
EVALUATOR_VERSION = "0.1.0"


def default_moving_average_relationship_metadata(
    *,
    short_window: int = 5,
    long_window: int = 20,
) -> AnalyticalSignalEvaluatorMetadata:
    """Return metadata for the first broker-free analytical evaluator."""

    return AnalyticalSignalEvaluatorMetadata(
        name=EVALUATOR_NAME,
        version=EVALUATOR_VERSION,
        description="Compares fast and slow close-price averages for diagnostics.",
        required_lookback_bars=max(short_window, long_window),
        supported_bar_sizes=["5 mins"],
    )


def validate_analytical_signal_evaluator_metadata(
    metadata: AnalyticalSignalEvaluatorMetadata,
) -> list[str]:
    """Validate analytical evaluator metadata without external systems."""

    errors: list[str] = []
    if metadata.name != EVALUATOR_NAME:
        errors.append(f"unsupported analytical evaluator: {metadata.name}")
    if metadata.broker_required:
        errors.append("broker_required must remain false")
    if metadata.emits_trading_actions:
        errors.append("emits_trading_actions must remain false")
    if metadata.emits_order_intents:
        errors.append("emits_order_intents must remain false")
    if not metadata.required_fields:
        errors.append("required_fields must not be empty")
    if not metadata.supported_bar_sizes:
        errors.append("supported_bar_sizes must not be empty")
    if metadata.required_lookback_bars <= 0:
        errors.append("required_lookback_bars must be positive")
    return errors


def evaluate_moving_average_relationship(
    context: SignalEvaluationContext,
    history_by_symbol: dict[str, list[BacktestBar]],
    metadata: AnalyticalSignalEvaluatorMetadata,
    *,
    short_window: int,
    long_window: int,
) -> list[AnalyticalSignalObservation]:
    """Evaluate non-actionable observations for one feed frame."""

    required = max(short_window, long_window)
    observations: list[AnalyticalSignalObservation] = []
    symbols = sorted(context.feed_symbols or context.available_symbols)
    for symbol in symbols:
        visible = [
            bar
            for bar in history_by_symbol.get(symbol, [])
            if bar.timestamp <= context.timestamp
        ]
        observations.append(
            _symbol_observation(
                context,
                symbol,
                visible,
                metadata,
                short_window=short_window,
                long_window=long_window,
                required=required,
            )
        )
    return observations


def run_analytical_signal_evaluation(
    feed: BacktestDataFeed,
    request: AnalyticalSignalEvaluationRequest,
) -> AnalyticalSignalEvaluationResult:
    """Replay feed frames through a broker-free analytical evaluator."""

    metadata = default_moving_average_relationship_metadata(
        short_window=request.short_window,
        long_window=request.long_window,
    )
    feed_summary = summarize_backtest_feed(feed)
    metadata_errors = validate_analytical_signal_evaluator_metadata(metadata)
    warnings = list(feed.warnings)
    errors = list(dict.fromkeys([*feed.errors, *metadata_errors]))
    observations: list[AnalyticalSignalObservation] = []
    history_by_symbol: dict[str, list[BacktestBar]] = {symbol: [] for symbol in feed.symbols}

    if feed.feed_status == BacktestFeedStatus.FAILED:
        errors.append("source feed status is failed")
    if not feed.frames:
        errors.append("source feed contains no frames")

    if not errors:
        for index, frame in enumerate(iter_feed_frames(feed)):
            for symbol, bar in sorted(frame.bars_by_symbol.items()):
                if bar is not None:
                    history_by_symbol.setdefault(symbol, []).append(bar)
            context = build_signal_evaluation_context(
                frame,
                feed_summary,
                frame_index=index,
            )
            observations.extend(
                evaluate_moving_average_relationship(
                    context,
                    history_by_symbol,
                    metadata,
                    short_window=request.short_window,
                    long_window=request.long_window,
                )
            )

    unique_warnings = list(dict.fromkeys(warnings))
    unique_errors = list(dict.fromkeys(errors))
    evaluation_status = _evaluation_status(feed, observations, unique_errors)
    diagnostics = _diagnostics(
        feed,
        request,
        metadata,
        observations=observations,
        evaluation_status=evaluation_status,
        warnings=unique_warnings,
        errors=unique_errors,
    )
    return AnalyticalSignalEvaluationResult(
        ok=evaluation_status != AnalyticalSignalEvaluationStatus.FAILED,
        request=request,
        metadata=metadata,
        feed_summary=feed_summary,
        diagnostics=diagnostics,
        observations=observations,
        warnings=unique_warnings,
        errors=unique_errors,
    )


def summarize_analytical_signal_evaluation(
    result: AnalyticalSignalEvaluationResult,
) -> AnalyticalSignalEvaluationDiagnostics:
    """Return analytical evaluation diagnostics for report surfaces."""

    return result.diagnostics


def validate_analytical_signal_evaluation_result(
    result: AnalyticalSignalEvaluationResult,
) -> list[str]:
    """Validate analytical evaluation output without external systems."""

    errors = list(result.errors)
    ordering = [(item.timestamp, item.frame_index, item.symbol) for item in result.observations]
    if ordering != sorted(ordering):
        errors.append("analytical observations are not sorted by timestamp and symbol")
    if result.ok and not result.observations:
        errors.append("successful analytical evaluation has no observations")
    if result.diagnostics.observations_count != len(result.observations):
        errors.append("analytical observation count does not match diagnostics")
    if result.signal_count != 0:
        errors.append("analytical evaluation signal_count must remain 0")
    if any(item.signal_count != 0 for item in result.observations):
        errors.append("analytical observation signal_count must remain 0")
    return list(dict.fromkeys(errors))


def build_analytical_signal_evaluation_report(
    feed: BacktestDataFeed,
    request: AnalyticalSignalEvaluationRequest,
) -> AnalyticalSignalEvaluationReport:
    """Run analytical evaluation and build a serializable report."""

    result = run_analytical_signal_evaluation(feed, request)
    validation_errors = validate_analytical_signal_evaluation_result(result)
    errors = list(dict.fromkeys([*result.errors, *validation_errors]))
    if errors != result.errors:
        result = result.model_copy(
            update={
                "ok": False,
                "errors": errors,
                "diagnostics": result.diagnostics.model_copy(
                    update={
                        "evaluation_status": AnalyticalSignalEvaluationStatus.FAILED,
                        "errors": errors,
                    }
                ),
            }
        )
    diagnostics = summarize_analytical_signal_evaluation(result)
    return AnalyticalSignalEvaluationReport(
        ok=result.ok,
        request=request,
        metadata=result.metadata,
        symbols_requested=request.symbols,
        feed_summary=result.feed_summary,
        result=result,
        diagnostics=diagnostics,
        observations=result.observations,
        warnings=result.warnings,
        errors=errors,
        final_status=_status_value(diagnostics.evaluation_status),
    )


class AnalyticalSignalEvaluator:
    """Small wrapper around the broker-free analytical signal evaluator."""

    def run(
        self,
        feed: BacktestDataFeed,
        request: AnalyticalSignalEvaluationRequest,
    ) -> AnalyticalSignalEvaluationResult:
        return run_analytical_signal_evaluation(feed, request)


def _symbol_observation(
    context: SignalEvaluationContext,
    symbol: str,
    visible_bars: list[BacktestBar],
    metadata: AnalyticalSignalEvaluatorMetadata,
    *,
    short_window: int,
    long_window: int,
    required: int,
) -> AnalyticalSignalObservation:
    current_bar = context.bars_by_symbol.get(symbol)
    if current_bar is None:
        return _observation(
            context,
            symbol,
            metadata,
            state=AnalyticalSignalConditionState.INSUFFICIENT_DATA,
            required=required,
            available=len(visible_bars),
            used=0,
            warmup_complete=False,
            data_valid=True,
            explanation="current frame bar is unavailable",
        )

    candidate_bars = visible_bars[-required:] if len(visible_bars) >= required else visible_bars
    if any(not _bar_data_valid(bar) for bar in candidate_bars):
        return _observation(
            context,
            symbol,
            metadata,
            state=AnalyticalSignalConditionState.INVALID_DATA,
            required=required,
            available=len(visible_bars),
            used=0,
            warmup_complete=len(visible_bars) >= required,
            data_valid=False,
            explanation="required lookback window contains invalid bar data",
        )

    if len(visible_bars) < required:
        return _observation(
            context,
            symbol,
            metadata,
            state=AnalyticalSignalConditionState.INSUFFICIENT_DATA,
            required=required,
            available=len(visible_bars),
            used=len(visible_bars),
            warmup_complete=False,
            data_valid=True,
            explanation="required lookback window is not complete",
        )

    fast_average = _average_close(visible_bars[-short_window:])
    slow_average = _average_close(visible_bars[-long_window:])
    difference = fast_average - slow_average
    state = (
        AnalyticalSignalConditionState.CONDITION_MET
        if fast_average > slow_average
        else AnalyticalSignalConditionState.CONDITION_NOT_MET
    )
    explanation = (
        "fast average exceeds slow average"
        if state == AnalyticalSignalConditionState.CONDITION_MET
        else "fast average does not exceed slow average"
    )
    return _observation(
        context,
        symbol,
        metadata,
        state=state,
        required=required,
        available=len(visible_bars),
        used=required,
        warmup_complete=True,
        data_valid=True,
        numeric_value=difference,
        threshold_or_reference_value=slow_average,
        explanation=explanation,
    )


def _observation(
    context: SignalEvaluationContext,
    symbol: str,
    metadata: AnalyticalSignalEvaluatorMetadata,
    *,
    state: AnalyticalSignalConditionState,
    required: int,
    available: int,
    used: int,
    warmup_complete: bool,
    data_valid: bool,
    explanation: str,
    numeric_value: Decimal | None = None,
    threshold_or_reference_value: Decimal | None = None,
) -> AnalyticalSignalObservation:
    return AnalyticalSignalObservation(
        evaluator_name=metadata.name,
        evaluator_version=metadata.version,
        symbol=symbol,
        timestamp=context.timestamp,
        frame_index=context.frame_index,
        condition_name=metadata.name,
        condition_state=state,
        numeric_value=numeric_value,
        threshold_or_reference_value=threshold_or_reference_value,
        required_lookback_bars=required,
        available_bars=available,
        used_bars=used,
        warmup_complete=warmup_complete,
        data_valid=data_valid,
        explanation=explanation,
    )


def _average_close(bars: list[BacktestBar]) -> Decimal:
    return sum((bar.close for bar in bars), Decimal("0")) / Decimal(len(bars))


def _bar_data_valid(bar: BacktestBar) -> bool:
    values = (bar.open, bar.high, bar.low, bar.close)
    if any(not _finite_decimal(value) for value in values):
        return False
    if bar.volume is None or not _finite_decimal(bar.volume) or bar.volume < 0:
        return False
    if bar.high < bar.low:
        return False
    if bar.high < max(bar.open, bar.close):
        return False
    return not bar.low > min(bar.open, bar.close)


def _finite_decimal(value: Decimal) -> bool:
    return value.is_finite()


def _evaluation_status(
    feed: BacktestDataFeed,
    observations: list[AnalyticalSignalObservation],
    errors: list[str],
) -> AnalyticalSignalEvaluationStatus:
    if errors:
        return AnalyticalSignalEvaluationStatus.FAILED
    if feed.feed_status == BacktestFeedStatus.PARTIAL or any(
        item.condition_state == AnalyticalSignalConditionState.INVALID_DATA
        for item in observations
    ):
        return AnalyticalSignalEvaluationStatus.PARTIAL
    return AnalyticalSignalEvaluationStatus.COMPLETED


def _diagnostics(
    feed: BacktestDataFeed,
    request: AnalyticalSignalEvaluationRequest,
    metadata: AnalyticalSignalEvaluatorMetadata,
    *,
    observations: list[AnalyticalSignalObservation],
    evaluation_status: AnalyticalSignalEvaluationStatus,
    warnings: list[str],
    errors: list[str],
) -> AnalyticalSignalEvaluationDiagnostics:
    state_counts: dict[str, int] = {}
    for item in observations:
        state = _status_value(item.condition_state)
        state_counts[state] = state_counts.get(state, 0) + 1
    missing_by_symbol = {
        symbol: sum(1 for frame in feed.frames if symbol in frame.missing_symbols)
        for symbol in feed.symbols
    }
    return AnalyticalSignalEvaluationDiagnostics(
        evaluator_name=metadata.name,
        evaluator_version=metadata.version,
        symbols=feed.symbols,
        alignment_mode=request.alignment_mode,
        feed_status=feed.feed_status,
        evaluation_status=evaluation_status,
        frame_count=feed.frame_count,
        contexts_built=len({(item.timestamp, item.frame_index) for item in observations}),
        observations_count=len(observations),
        observations_by_state=state_counts,
        first_timestamp=observations[0].timestamp if observations else None,
        last_timestamp=observations[-1].timestamp if observations else None,
        warmup_observations=state_counts.get(
            AnalyticalSignalConditionState.INSUFFICIENT_DATA.value,
            0,
        ),
        invalid_data_observations=state_counts.get(
            AnalyticalSignalConditionState.INVALID_DATA.value,
            0,
        ),
        missing_symbols_by_frame_count=sum(1 for frame in feed.frames if frame.missing_symbols),
        missing_symbols_by_symbol=missing_by_symbol,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )


def _status_value(
    value: AnalyticalSignalConditionState | AnalyticalSignalEvaluationStatus | str,
) -> str:
    return str(getattr(value, "value", value))
