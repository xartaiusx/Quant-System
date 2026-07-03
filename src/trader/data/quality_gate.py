"""Broker-free data-quality gates for local historical snapshots."""

from __future__ import annotations

from pathlib import Path

from trader.config import TraderConfig
from trader.data.historical import build_readiness_report
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    DataQualityGateIssue,
    DataQualityGateReport,
    DataQualityGateRequest,
    DataQualityGateStatus,
    DataQualityGateSymbolResult,
    HistoricalDatasetSummary,
    HistoricalLoaderReport,
    HistoricalLoadResult,
    HistoricalReadinessReport,
    HistoricalReadinessSummary,
    HistoricalSnapshotLoadRequest,
)


def build_data_quality_gate_report(
    config: TraderConfig,
    request: DataQualityGateRequest,
) -> DataQualityGateReport:
    """Evaluate local historical snapshots against explicit data-quality gates."""

    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.bar_size,
        what_to_show=request.what_to_show,
        latest=request.latest,
        strict=request.strict,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    manifest_paths = [
        path
        for result in loader_report.results
        if (path := _manifest_path_for_readiness(result)) is not None
    ]
    readiness_report = build_readiness_report(
        config,
        manifest_paths=manifest_paths,
        base_dir=Path(request.base_data_path),
    )

    results = [
        _symbol_result(
            symbol,
            request,
            loader_report,
            readiness_report,
        )
        for symbol in request.symbols
    ]
    errors = [error for result in results for error in result.errors]
    warnings = list(
        dict.fromkeys(
            [
                "No broker contacted; offline data-quality gate only",
                *loader_report.warnings,
                *readiness_report.warnings,
                *[warning for result in results for warning in result.warnings],
            ]
        )
    )
    final_status = _final_status(results)
    return DataQualityGateReport(
        ok=final_status != DataQualityGateStatus.FAILED,
        request=request,
        symbols_requested=request.symbols,
        results=results,
        readiness_final_status=readiness_report.final_status,
        loader_final_status=loader_report.final_status,
        warnings=warnings,
        errors=list(dict.fromkeys(errors)),
        final_status=final_status,
    )


def _symbol_result(
    symbol: str,
    request: DataQualityGateRequest,
    loader_report: HistoricalLoaderReport,
    readiness_report: HistoricalReadinessReport,
) -> DataQualityGateSymbolResult:
    load_result = next(
        (result for result in loader_report.results if result.symbol == symbol),
        None,
    )
    readiness_summary = next(
        (summary for summary in readiness_report.summaries if summary.symbol == symbol),
        None,
    )
    summary = load_result.summary if load_result is not None else None
    issues = _quality_issues(symbol, request, summary, readiness_summary)
    errors = [issue.message for issue in issues if issue.severity == "error"]
    warnings = [issue.message for issue in issues if issue.severity == "warning"]
    status = (
        DataQualityGateStatus.FAILED
        if errors
        else DataQualityGateStatus.PASSED_WITH_WARNINGS
        if warnings
        else DataQualityGateStatus.PASSED
    )
    return DataQualityGateSymbolResult(
        symbol=symbol,
        status=status,
        bars_count=summary.bars_count if summary else 0,
        zero_volume_bars=readiness_summary.zero_volume_bars if readiness_summary else 0,
        duplicate_timestamps_count=summary.duplicate_timestamps_count if summary else 0,
        missing_gap_count=summary.missing_gap_count if summary else 0,
        malformed_line_count=summary.malformed_line_count if summary else 0,
        invalid_ohlc_count=summary.invalid_ohlc_count if summary else 0,
        negative_volume_count=summary.negative_volume_count if summary else 0,
        stale_snapshot=bool(
            (summary and summary.stale_snapshot)
            or (readiness_summary and readiness_summary.stale_snapshot)
        ),
        load_status=str(load_result.load_status) if load_result else "missing",
        readiness_status=str(readiness_summary.readiness_status)
        if readiness_summary
        else "missing",
        snapshot_path=summary.bars_path if summary else None,
        manifest_path=summary.manifest_path if summary else None,
        issues=issues,
        warnings=warnings,
        errors=errors,
    )


def _manifest_path_for_readiness(result: HistoricalLoadResult) -> str | None:
    if result.index_entry is not None and result.index_entry.manifest_path is not None:
        return result.index_entry.manifest_path
    if result.summary is not None and result.summary.manifest_path is not None:
        return result.summary.manifest_path
    return None


def _quality_issues(
    symbol: str,
    request: DataQualityGateRequest,
    summary: HistoricalDatasetSummary | None,
    readiness_summary: HistoricalReadinessSummary | None,
) -> list[DataQualityGateIssue]:
    issues: list[DataQualityGateIssue] = []
    if summary is None:
        issues.append(_issue(symbol, "error", "missing_dataset", "no loaded dataset"))
        return issues
    if readiness_summary is None:
        issues.append(
            _issue(symbol, "error", "missing_readiness", "no readiness summary")
        )
        return issues

    _max_issue(
        issues,
        symbol,
        code="min_bars",
        label="bars",
        observed=summary.bars_count,
        threshold=request.min_bars,
        comparison="min",
    )
    _max_issue(
        issues,
        symbol,
        code="zero_volume_bars",
        label="zero-volume bars",
        observed=readiness_summary.zero_volume_bars,
        threshold=request.max_zero_volume_bars,
    )
    _max_issue(
        issues,
        symbol,
        code="duplicate_timestamps",
        label="duplicate timestamps",
        observed=summary.duplicate_timestamps_count,
        threshold=request.max_duplicate_timestamps,
    )
    _max_issue(
        issues,
        symbol,
        code="missing_gaps",
        label="missing timestamp gaps",
        observed=summary.missing_gap_count,
        threshold=request.max_missing_gap_count,
    )
    _max_issue(
        issues,
        symbol,
        code="malformed_lines",
        label="malformed JSONL lines",
        observed=summary.malformed_line_count,
        threshold=request.max_malformed_lines,
    )
    _max_issue(
        issues,
        symbol,
        code="invalid_ohlc",
        label="invalid OHLC bars",
        observed=summary.invalid_ohlc_count,
        threshold=request.max_invalid_ohlc_count,
    )
    _max_issue(
        issues,
        symbol,
        code="negative_volume",
        label="negative-volume bars",
        observed=summary.negative_volume_count,
        threshold=request.max_negative_volume_count,
    )
    if not request.allow_stale_snapshot and (
        summary.stale_snapshot or readiness_summary.stale_snapshot
    ):
        issues.append(
            _issue(
                symbol,
                "error",
                "stale_snapshot",
                "snapshot is stale",
                observed=True,
                threshold=False,
            )
        )
    return issues


def _max_issue(
    issues: list[DataQualityGateIssue],
    symbol: str,
    *,
    code: str,
    label: str,
    observed: int,
    threshold: int,
    comparison: str = "max",
) -> None:
    failed = observed < threshold if comparison == "min" else observed > threshold
    if failed:
        operator = "at least" if comparison == "min" else "no more than"
        issues.append(
            _issue(
                symbol,
                "error",
                code,
                f"{label} observed {observed}; expected {operator} {threshold}",
                observed=observed,
                threshold=threshold,
            )
        )


def _issue(
    symbol: str,
    severity: str,
    code: str,
    message: str,
    *,
    observed: int | float | str | bool | None = None,
    threshold: int | float | str | bool | None = None,
) -> DataQualityGateIssue:
    return DataQualityGateIssue(
        symbol=symbol,
        severity=severity,
        code=code,
        message=message,
        observed_value=observed,
        threshold_value=threshold,
    )


def _final_status(
    results: list[DataQualityGateSymbolResult],
) -> DataQualityGateStatus:
    if not results or any(result.status == DataQualityGateStatus.FAILED for result in results):
        return DataQualityGateStatus.FAILED
    if any(result.status == DataQualityGateStatus.PASSED_WITH_WARNINGS for result in results):
        return DataQualityGateStatus.PASSED_WITH_WARNINGS
    return DataQualityGateStatus.PASSED
