"""Broker-free data adapter for offline historical snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataAdapterIssue,
    BacktestDataAdapterReport,
    BacktestDataAdapterRequest,
    BacktestDataFeed,
    BacktestDataFeedSummary,
    BacktestFeedFrame,
    BacktestFeedPoint,
    BacktestFeedStatus,
    HistoricalDatasetSummary,
    HistoricalLoadedBar,
    HistoricalLoadedDataset,
    HistoricalLoaderReport,
    HistoricalLoadStatus,
)


def build_backtest_feed(
    datasets: Iterable[HistoricalLoadedDataset],
    *,
    alignment_mode: BacktestAlignmentMode | str = BacktestAlignmentMode.UNION,
) -> BacktestDataFeed:
    """Build a deterministic offline bar feed from loaded historical datasets."""

    mode = _alignment_mode(alignment_mode)
    dataset_list = list(datasets)
    issues: list[BacktestDataAdapterIssue] = []
    warnings: list[str] = []
    errors: list[str] = []

    if not dataset_list:
        message = "no historical datasets supplied"
        issues.append(_issue(None, "error", "empty_input", message))
        errors.append(message)
        return _feed(
            symbols=[],
            mode=mode,
            frames=[],
            source_summaries=[],
            duplicate_counts={},
            issues=issues,
            warnings=warnings,
            errors=errors,
        )

    symbols = _ordered_symbols(dataset.symbol for dataset in dataset_list)
    symbol_maps: dict[str, dict[datetime, BacktestBar]] = {symbol: {} for symbol in symbols}
    duplicate_counts: dict[str, int] = {symbol: 0 for symbol in symbols}

    for dataset in dataset_list:
        symbol = dataset.symbol.strip().upper()
        if dataset.summary.load_status == HistoricalLoadStatus.PARTIAL:
            warning = f"{symbol} source dataset status is partial"
            issues.append(_issue(symbol, "warning", "partial_dataset", warning))
            warnings.append(warning)
        elif dataset.summary.load_status == HistoricalLoadStatus.FAILED:
            error = f"{symbol} source dataset status is failed"
            issues.append(_issue(symbol, "error", "failed_dataset", error))
            errors.append(error)

        if not dataset.bars:
            error = f"{symbol} source dataset contains no bars"
            issues.append(_issue(symbol, "error", "empty_dataset", error))
            errors.append(error)
            continue

        seen: set[datetime] = set()
        for loaded_bar in sorted(dataset.bars, key=lambda bar: bar.timestamp):
            if loaded_bar.timestamp in seen:
                duplicate_counts[symbol] = duplicate_counts.get(symbol, 0) + 1
                continue
            seen.add(loaded_bar.timestamp)
            symbol_maps.setdefault(symbol, {})[loaded_bar.timestamp] = _to_backtest_bar(
                loaded_bar,
                dataset=dataset,
            )

    for symbol, count in duplicate_counts.items():
        if count:
            warning = f"{symbol} duplicate timestamps detected: {count}"
            issues.append(_issue(symbol, "warning", "duplicate_timestamps", warning))
            warnings.append(warning)

    timestamps = _aligned_timestamps(symbol_maps, mode)
    frames = [_frame_for_timestamp(timestamp, symbols, symbol_maps) for timestamp in timestamps]
    return _feed(
        symbols=symbols,
        mode=mode,
        frames=frames,
        source_summaries=[dataset.summary for dataset in dataset_list],
        duplicate_counts=duplicate_counts,
        issues=issues,
        warnings=warnings,
        errors=errors,
    )


def build_backtest_feed_report(
    loader_report: HistoricalLoaderReport,
    request: BacktestDataAdapterRequest,
) -> BacktestDataAdapterReport:
    """Build a serializable report from an offline loader report."""

    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    summary = summarize_backtest_feed(feed)
    warnings = list(
        dict.fromkeys(
            [
                "No broker contacted; offline backtest feed build only",
                *loader_report.warnings,
                *summary.warnings,
            ]
        )
    )
    errors = list(dict.fromkeys([*loader_report.errors, *summary.errors]))
    ok = bool(feed.frames) and summary.feed_status != BacktestFeedStatus.FAILED

    return BacktestDataAdapterReport(
        ok=ok,
        request=request,
        symbols_requested=request.symbols,
        source_datasets=feed.source_summaries,
        summary=summary,
        issues=feed.issues,
        warnings=warnings,
        errors=errors,
        final_status=_status_value(summary.feed_status),
    )


def summarize_backtest_feed(feed: BacktestDataFeed) -> BacktestDataFeedSummary:
    """Return a compact summary of a feed."""

    return BacktestDataFeedSummary(
        symbols=feed.symbols,
        total_bars=feed.total_bars,
        frame_count=feed.frame_count,
        first_timestamp=feed.first_timestamp,
        last_timestamp=feed.last_timestamp,
        missing_bars_by_symbol=feed.missing_bars_by_symbol,
        duplicate_timestamps_by_symbol=feed.duplicate_timestamps_by_symbol,
        alignment_mode=feed.alignment_mode,
        feed_status=feed.feed_status,
        warnings=feed.warnings,
        errors=feed.errors,
    )


def validate_backtest_feed(feed: BacktestDataFeed) -> list[BacktestDataAdapterIssue]:
    """Validate feed shape without running strategy or execution logic."""

    issues: list[BacktestDataAdapterIssue] = []
    if not feed.frames:
        issues.append(_issue(None, "error", "empty_feed", "feed contains no frames"))

    timestamps = [frame.timestamp for frame in feed.frames]
    if timestamps != sorted(timestamps):
        issues.append(
            _issue(None, "error", "unsorted_frames", "feed frames are not sorted")
        )

    expected = set(feed.symbols)
    for frame in feed.frames:
        actual = set(frame.bars_by_symbol)
        if actual != expected:
            issues.append(
                _issue(
                    None,
                    "error",
                    "frame_symbol_mismatch",
                    "feed frame symbols do not match feed symbols",
                    timestamp=frame.timestamp,
                )
            )
    return issues


def iter_feed_frames(feed: BacktestDataFeed) -> Iterator[BacktestFeedFrame]:
    """Yield feed frames in deterministic timestamp order."""

    yield from sorted(feed.frames, key=lambda frame: frame.timestamp)


def _feed(
    *,
    symbols: list[str],
    mode: BacktestAlignmentMode,
    frames: list[BacktestFeedFrame],
    source_summaries: list[HistoricalDatasetSummary],
    duplicate_counts: dict[str, int],
    issues: list[BacktestDataAdapterIssue],
    warnings: list[str],
    errors: list[str],
) -> BacktestDataFeed:
    missing_counts = {
        symbol: sum(1 for frame in frames if symbol in frame.missing_symbols)
        for symbol in symbols
    }
    if any(missing_counts.values()):
        for symbol, count in missing_counts.items():
            if count:
                warnings.append(f"{symbol} missing bars in aligned feed: {count}")

    total_bars = sum(
        1 for frame in frames for bar in frame.bars_by_symbol.values() if bar is not None
    )
    validation_issues = validate_backtest_feed(
        BacktestDataFeed(
            symbols=symbols,
            alignment_mode=mode,
            frames=frames,
            source_summaries=source_summaries,
            total_bars=total_bars,
            frame_count=len(frames),
            first_timestamp=frames[0].timestamp if frames else None,
            last_timestamp=frames[-1].timestamp if frames else None,
            missing_bars_by_symbol=missing_counts,
            duplicate_timestamps_by_symbol=duplicate_counts,
            feed_status=BacktestFeedStatus.READY,
            issues=issues,
            warnings=list(dict.fromkeys(warnings)),
            errors=list(dict.fromkeys(errors)),
        )
    )
    issues.extend(validation_issues)
    for issue in validation_issues:
        target = errors if issue.severity == "error" else warnings
        target.append(issue.message)

    if errors and not frames:
        status = BacktestFeedStatus.FAILED
    elif errors or warnings:
        status = BacktestFeedStatus.PARTIAL
    else:
        status = BacktestFeedStatus.READY

    return BacktestDataFeed(
        symbols=symbols,
        alignment_mode=mode,
        frames=frames,
        source_summaries=source_summaries,
        total_bars=total_bars,
        frame_count=len(frames),
        first_timestamp=frames[0].timestamp if frames else None,
        last_timestamp=frames[-1].timestamp if frames else None,
        missing_bars_by_symbol=missing_counts,
        duplicate_timestamps_by_symbol=duplicate_counts,
        feed_status=status,
        issues=issues,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )


def _aligned_timestamps(
    symbol_maps: dict[str, dict[datetime, BacktestBar]],
    mode: BacktestAlignmentMode,
) -> list[datetime]:
    timestamp_sets = [set(bars) for bars in symbol_maps.values()]
    if not timestamp_sets:
        return []
    if mode == BacktestAlignmentMode.INTERSECTION:
        return sorted(set.intersection(*timestamp_sets))
    return sorted(set.union(*timestamp_sets))


def _frame_for_timestamp(
    timestamp: datetime,
    symbols: list[str],
    symbol_maps: dict[str, dict[datetime, BacktestBar]],
) -> BacktestFeedFrame:
    bars_by_symbol: dict[str, BacktestBar | None] = {}
    points: list[BacktestFeedPoint] = []
    missing_symbols: list[str] = []
    for symbol in symbols:
        bar = symbol_maps.get(symbol, {}).get(timestamp)
        missing = bar is None
        if missing:
            missing_symbols.append(symbol)
        bars_by_symbol[symbol] = bar
        points.append(BacktestFeedPoint(symbol=symbol, bar=bar, missing=missing))
    return BacktestFeedFrame(
        timestamp=timestamp,
        bars_by_symbol=bars_by_symbol,
        points=points,
        missing_symbols=missing_symbols,
    )


def _to_backtest_bar(
    bar: HistoricalLoadedBar,
    *,
    dataset: HistoricalLoadedDataset,
) -> BacktestBar:
    return BacktestBar(
        symbol=bar.symbol,
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source_snapshot_timestamp=dataset.snapshot_timestamp,
        source_bars_path=dataset.bars_path,
        source_manifest_path=dataset.manifest_path,
    )


def _ordered_symbols(symbols: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    for symbol in symbols:
        normalized = symbol.strip().upper()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _alignment_mode(value: BacktestAlignmentMode | str) -> BacktestAlignmentMode:
    if isinstance(value, BacktestAlignmentMode):
        return value
    return BacktestAlignmentMode(value)


def _issue(
    symbol: str | None,
    severity: str,
    code: str,
    message: str,
    *,
    timestamp: datetime | None = None,
) -> BacktestDataAdapterIssue:
    return BacktestDataAdapterIssue(
        symbol=symbol,
        severity=severity,
        code=code,
        message=message,
        timestamp=timestamp,
    )


def _status_value(value: BacktestFeedStatus | str) -> str:
    return str(getattr(value, "value", value))
