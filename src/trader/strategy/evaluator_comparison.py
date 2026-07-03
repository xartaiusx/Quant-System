"""Broker-free analytical evaluator comparison diagnostics."""

from __future__ import annotations

from collections import Counter

from trader.backtest.data_adapter import build_backtest_feed
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    AnalyticalSignalConditionState,
    AnalyticalSignalEvaluationRequest,
    AnalyticalSignalObservation,
    BacktestDataFeed,
    EvaluatorComparisonReport,
    EvaluatorComparisonRequest,
    EvaluatorComparisonResult,
    EvaluatorComparisonSegmentSummary,
    EvaluatorComparisonStatus,
    EvaluatorWindowCandidate,
    HistoricalSnapshotLoadRequest,
)
from trader.strategy.signal_evaluation import build_analytical_signal_evaluation_report


def parse_window_candidates(raw: str) -> list[EvaluatorWindowCandidate]:
    """Parse comma-separated short:long candidate windows."""

    candidates: list[EvaluatorWindowCandidate] = []
    for item in raw.split(","):
        chunk = item.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"window candidate must use short:long format: {chunk}")
        short_raw, long_raw = chunk.split(":", 1)
        candidates.append(
            EvaluatorWindowCandidate(
                short_window=int(short_raw.strip()),
                long_window=int(long_raw.strip()),
            )
        )
    if not candidates:
        raise ValueError("at least one evaluator candidate is required")
    return candidates


def build_evaluator_comparison_report(
    request: EvaluatorComparisonRequest,
) -> EvaluatorComparisonReport:
    """Compare analytical evaluator parameter candidates on local snapshots only."""

    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    results = [_candidate_result(candidate, request, feed) for candidate in request.candidates]
    errors = list(dict.fromkeys([*loader_report.errors, *feed.errors]))
    warnings = _actionable_warnings([*loader_report.warnings, *feed.warnings])
    for result in results:
        warnings.extend(result.warnings)
        errors.extend(result.errors)
    final_status = _final_status(results)
    return EvaluatorComparisonReport(
        ok=final_status != EvaluatorComparisonStatus.FAILED,
        request=request,
        symbols_requested=request.symbols,
        results=results,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
        final_status=final_status,
    )


def _candidate_result(
    candidate: EvaluatorWindowCandidate,
    request: EvaluatorComparisonRequest,
    feed: BacktestDataFeed,
) -> EvaluatorComparisonResult:
    evaluation_request = AnalyticalSignalEvaluationRequest(
        symbols=request.symbols,
        alignment_mode=request.alignment_mode,
        requested_bar_size=request.requested_bar_size,
        requested_what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
        short_window=candidate.short_window,
        long_window=candidate.long_window,
    )
    report = build_analytical_signal_evaluation_report(feed, evaluation_request)
    split_frame = max(1, int(report.diagnostics.frame_count * request.train_fraction))
    train = _segment_summary(
        "train",
        report.observations,
        split_frame=split_frame,
        train=True,
    )
    test = _segment_summary(
        "test",
        report.observations,
        split_frame=split_frame,
        train=False,
    )
    delta = (
        abs(train.condition_met_rate - test.condition_met_rate)
        if train.condition_met_rate is not None and test.condition_met_rate is not None
        else None
    )
    status = (
        EvaluatorComparisonStatus.FAILED
        if not report.ok
        else EvaluatorComparisonStatus.COMPLETED_WITH_WARNINGS
        if _actionable_warnings(report.warnings)
        else EvaluatorComparisonStatus.COMPLETED
    )
    return EvaluatorComparisonResult(
        candidate=candidate,
        ok=report.ok,
        final_status=status,
        diagnostics_status=report.final_status,
        total_observations=report.diagnostics.observations_count,
        train=train,
        test=test,
        condition_met_rate_delta=delta,
        warnings=_actionable_warnings(report.warnings),
        errors=report.errors,
    )


def _segment_summary(
    segment: str,
    observations: list[AnalyticalSignalObservation],
    *,
    split_frame: int,
    train: bool,
) -> EvaluatorComparisonSegmentSummary:
    selected = [
        observation
        for observation in observations
        if (
            observation.frame_index < split_frame
            if train
            else observation.frame_index >= split_frame
        )
    ]
    counts = Counter(str(observation.condition_state) for observation in selected)
    met = counts[AnalyticalSignalConditionState.CONDITION_MET.value]
    not_met = counts[AnalyticalSignalConditionState.CONDITION_NOT_MET.value]
    denominator = met + not_met
    return EvaluatorComparisonSegmentSummary(
        segment=segment,
        frame_count=len({observation.frame_index for observation in selected}),
        observation_count=len(selected),
        condition_met_count=met,
        condition_not_met_count=not_met,
        insufficient_data_count=counts[
            AnalyticalSignalConditionState.INSUFFICIENT_DATA.value
        ],
        invalid_data_count=counts[AnalyticalSignalConditionState.INVALID_DATA.value],
        condition_met_rate=(met / denominator) if denominator else None,
    )


def _final_status(
    results: list[EvaluatorComparisonResult],
) -> EvaluatorComparisonStatus:
    if not results or any(
        result.final_status == EvaluatorComparisonStatus.FAILED for result in results
    ):
        return EvaluatorComparisonStatus.FAILED
    if any(
        result.final_status == EvaluatorComparisonStatus.COMPLETED_WITH_WARNINGS
        for result in results
    ):
        return EvaluatorComparisonStatus.COMPLETED_WITH_WARNINGS
    return EvaluatorComparisonStatus.COMPLETED


def _actionable_warnings(warnings: list[str]) -> list[str]:
    """Remove informational offline safety notes from comparison warning status."""

    return list(
        dict.fromkeys(
            warning
            for warning in warnings
            if not warning.startswith("No broker contacted;")
        )
    )
