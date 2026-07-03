"""Offline historical snapshot discovery and loading."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from trader.data.historical import DEFAULT_HISTORICAL_ROOT
from trader.models import (
    HistoricalDatasetSummary,
    HistoricalLoadedBar,
    HistoricalLoadedDataset,
    HistoricalLoaderReport,
    HistoricalLoadIssue,
    HistoricalLoadResult,
    HistoricalLoadStatus,
    HistoricalSnapshotBar,
    HistoricalSnapshotIndexEntry,
    HistoricalSnapshotLoadRequest,
    HistoricalSnapshotManifest,
    utc_now,
)

_SNAPSHOT_STALE_AFTER_SECONDS = 48 * 60 * 60
_MANIFEST_SUFFIX = "_manifest.json"
_BARS_SUFFIX = "_bars.jsonl"
_QUALITY_SAMPLE_LIMIT = 5


def discover_snapshots(
    *,
    base_dir: str | Path = DEFAULT_HISTORICAL_ROOT,
    symbols: Iterable[str] | None = None,
    bar_size: str | None = None,
    what_to_show: str | None = None,
    snapshot_timestamp: str | None = None,
) -> list[HistoricalSnapshotIndexEntry]:
    """Discover stored historical snapshot manifests without contacting a broker."""

    request = HistoricalSnapshotLoadRequest(
        symbols=list(symbols or []),
        bar_size=bar_size,
        what_to_show=what_to_show,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=Path(base_dir).as_posix(),
    )
    root = Path(base_dir)
    if not root.exists():
        return []

    entries: list[HistoricalSnapshotIndexEntry] = []
    for manifest_path in root.glob(f"*/*/*/*{_MANIFEST_SUFFIX}"):
        snapshot_stamp = _timestamp_from_manifest_path(manifest_path)
        try:
            manifest = HistoricalSnapshotManifest.model_validate_json(
                manifest_path.read_text()
            )
        except (OSError, ValidationError, ValueError):
            continue

        bars_path = _resolve_bars_path(manifest, manifest_path)
        entry = HistoricalSnapshotIndexEntry(
            symbol=manifest.symbol.strip().upper(),
            bar_size=manifest.bar_size,
            what_to_show=manifest.what_to_show.strip().upper(),
            snapshot_timestamp=snapshot_stamp,
            bars_path=bars_path.as_posix(),
            manifest_path=manifest_path.as_posix(),
            generated_at=manifest.generated_at,
            bars_count=_count_jsonl_records(bars_path),
            manifest_bar_count=manifest.bar_count,
        )
        if _entry_matches_request(entry, request):
            entries.append(entry)
    return sorted(entries, key=_entry_sort_key)


def select_snapshot_entries(
    entries: list[HistoricalSnapshotIndexEntry],
    request: HistoricalSnapshotLoadRequest,
) -> list[HistoricalSnapshotIndexEntry]:
    """Select entries for a load request."""

    filtered = [entry for entry in entries if _entry_matches_request(entry, request)]
    if request.latest:
        latest_by_symbol: dict[str, HistoricalSnapshotIndexEntry] = {}
        for entry in sorted(filtered, key=_entry_sort_key):
            latest_by_symbol[entry.symbol] = entry
        if request.symbols:
            return [
                latest_by_symbol[symbol]
                for symbol in request.symbols
                if symbol in latest_by_symbol
            ]
        return [latest_by_symbol[symbol] for symbol in sorted(latest_by_symbol)]
    return filtered


def build_history_index_report(
    *,
    base_dir: str | Path = DEFAULT_HISTORICAL_ROOT,
    symbols: Iterable[str] | None = None,
    bar_size: str | None = None,
    what_to_show: str | None = None,
    snapshot_timestamp: str | None = None,
) -> HistoricalLoaderReport:
    """Build an offline snapshot index report."""

    request = HistoricalSnapshotLoadRequest(
        symbols=list(symbols or []),
        bar_size=bar_size,
        what_to_show=what_to_show,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=Path(base_dir).as_posix(),
    )
    entries = discover_snapshots(
        base_dir=base_dir,
        symbols=request.symbols,
        bar_size=request.bar_size,
        what_to_show=request.what_to_show,
        snapshot_timestamp=request.snapshot_timestamp,
    )
    warnings = ["No broker contacted; offline snapshot index only"]
    errors: list[str] = []
    if not entries:
        errors.append("no historical snapshots found")
    return HistoricalLoaderReport(
        title="Offline Historical Snapshot Index",
        report_type="history_index",
        command="history-index",
        ok=bool(entries),
        request=request,
        base_data_path=Path(base_dir).as_posix(),
        symbols_requested=request.symbols,
        snapshots_discovered=entries,
        warnings=warnings,
        errors=errors,
        final_status="indexed" if entries else "failed",
    )


def load_historical_snapshots(
    request: HistoricalSnapshotLoadRequest,
) -> HistoricalLoaderReport:
    """Load offline historical snapshots into normalized datasets."""

    base_dir = Path(request.base_data_path)
    discovered = discover_snapshots(
        base_dir=base_dir,
        symbols=request.symbols,
        bar_size=request.bar_size,
        what_to_show=request.what_to_show,
        snapshot_timestamp=request.snapshot_timestamp,
    )
    selected = select_snapshot_entries(discovered, request)
    selected_symbols = {entry.symbol for entry in selected}
    results: list[HistoricalLoadResult] = [
        load_snapshot_entry(entry, request=request) for entry in selected
    ]

    for symbol in request.symbols:
        if symbol not in selected_symbols:
            message = f"no matching snapshot found for {symbol}"
            issue = HistoricalLoadIssue(
                symbol=symbol,
                severity="error",
                code="snapshot_not_found",
                message=message,
            )
            results.append(
                HistoricalLoadResult(
                    symbol=symbol,
                    request=request,
                    issues=[issue],
                    errors=[message],
                    load_status=HistoricalLoadStatus.FAILED,
                )
            )

    summaries = [result.summary for result in results if result.summary is not None]
    warnings = list(
        dict.fromkeys(
            [
                "No broker contacted; offline snapshot load only",
                *[warning for result in results for warning in result.warnings],
            ]
        )
    )
    errors = list(dict.fromkeys(error for result in results for error in result.errors))
    loaded_or_partial = any(
        result.load_status
        in {HistoricalLoadStatus.LOADED, HistoricalLoadStatus.PARTIAL}
        for result in results
    )
    all_loaded = bool(results) and all(
        result.load_status == HistoricalLoadStatus.LOADED for result in results
    )
    if all_loaded:
        final_status = "loaded"
    elif loaded_or_partial:
        final_status = "partial"
    else:
        final_status = "failed"
    if not discovered:
        errors.append("no historical snapshots found")

    return HistoricalLoaderReport(
        command="history-load",
        ok=loaded_or_partial,
        request=request,
        base_data_path=base_dir.as_posix(),
        symbols_requested=request.symbols,
        snapshots_discovered=discovered,
        results=results,
        summaries=summaries,
        warnings=warnings,
        errors=errors,
        final_status=final_status,
    )


def load_snapshot_entry(
    entry: HistoricalSnapshotIndexEntry,
    *,
    request: HistoricalSnapshotLoadRequest,
) -> HistoricalLoadResult:
    """Load one discovered snapshot entry."""

    manifest_path = Path(entry.manifest_path)
    bars_path = Path(entry.bars_path)
    issues: list[HistoricalLoadIssue] = []
    warnings: list[str] = []
    errors: list[str] = []

    if not manifest_path.exists():
        message = f"manifest file not found: {manifest_path}"
        issue = _issue(entry.symbol, "error", "missing_manifest", message, manifest_path)
        return _failed_result(entry, request, [issue], [message])

    try:
        manifest = HistoricalSnapshotManifest.model_validate_json(
            manifest_path.read_text()
        )
    except (OSError, ValidationError, ValueError) as exc:
        message = f"manifest could not be parsed: {exc}"
        issue = _issue(entry.symbol, "error", "manifest_parse_failed", message, manifest_path)
        return _failed_result(entry, request, [issue], [message])

    bars_path = _resolve_bars_path(manifest, manifest_path, fallback=bars_path)
    if not bars_path.exists():
        message = f"bars file not found: {bars_path}"
        issue = _issue(entry.symbol, "error", "missing_bars_file", message, bars_path)
        return _failed_result(entry, request, [issue], [message])

    issues.extend(_metadata_issues(entry, manifest, manifest_path, bars_path))
    raw_bars, parse_issues = _load_raw_bars(
        bars_path,
        symbol=entry.symbol,
        strict=request.strict,
    )
    issues.extend(parse_issues)

    loaded_bars: list[HistoricalLoadedBar] = []
    for raw_bar in raw_bars:
        loaded_bar, normalize_issues = _normalize_bar(
            raw_bar,
            snapshot_timestamp=entry.snapshot_timestamp,
        )
        issues.extend(normalize_issues)
        if loaded_bar is not None:
            loaded_bars.append(loaded_bar)

    loaded_bars = sorted(loaded_bars, key=lambda bar: bar.timestamp)
    summary = _dataset_summary(
        entry,
        manifest,
        loaded_bars,
        issues=issues,
        now=utc_now(),
    )
    warnings.extend(summary.warnings)
    errors.extend(summary.errors)
    dataset = HistoricalLoadedDataset(
        symbol=entry.symbol,
        bar_size=entry.bar_size,
        what_to_show=entry.what_to_show,
        snapshot_timestamp=entry.snapshot_timestamp,
        bars_path=bars_path.as_posix(),
        manifest_path=manifest_path.as_posix(),
        bars=loaded_bars,
        summary=summary,
        issues=issues,
    )
    return HistoricalLoadResult(
        symbol=entry.symbol,
        request=request,
        index_entry=entry.model_copy(update={"bars_path": bars_path.as_posix()}),
        dataset=dataset,
        summary=summary,
        issues=issues,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
        load_status=summary.load_status,
    )


def _load_raw_bars(
    bars_path: Path,
    *,
    symbol: str,
    strict: bool,
) -> tuple[list[HistoricalSnapshotBar], list[HistoricalLoadIssue]]:
    raw_bars: list[HistoricalSnapshotBar] = []
    issues: list[HistoricalLoadIssue] = []
    for line_number, line in enumerate(bars_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw_bars.append(HistoricalSnapshotBar.model_validate_json(line))
        except (ValidationError, ValueError) as exc:
            severity = "error" if strict else "warning"
            issues.append(
                HistoricalLoadIssue(
                    symbol=symbol,
                    severity=severity,
                    code="malformed_jsonl_line",
                    message=f"malformed JSONL line {line_number}: {exc}",
                    path=bars_path.as_posix(),
                    line_number=line_number,
                )
            )
    return raw_bars, issues


def _normalize_bar(
    bar: HistoricalSnapshotBar,
    *,
    snapshot_timestamp: str,
) -> tuple[HistoricalLoadedBar | None, list[HistoricalLoadIssue]]:
    issues: list[HistoricalLoadIssue] = []
    parsed_timestamp = _parse_bar_timestamp(bar.timestamp)
    if parsed_timestamp is None:
        issues.append(
            HistoricalLoadIssue(
                symbol=bar.symbol,
                severity="error",
                code="timestamp_parse_failed",
                message=f"timestamp could not be parsed: {bar.timestamp}",
                timestamp=bar.timestamp,
            )
        )
        return None, issues

    if not _ohlc_is_valid(bar):
        issues.append(
            HistoricalLoadIssue(
                symbol=bar.symbol,
                severity="error",
                code="invalid_ohlc",
                message="OHLC values are internally inconsistent",
                timestamp=bar.timestamp,
            )
        )
    if bar.volume is not None and bar.volume < 0:
        issues.append(
            HistoricalLoadIssue(
                symbol=bar.symbol,
                severity="error",
                code="negative_volume",
                message="volume is negative",
                timestamp=bar.timestamp,
            )
        )

    typical_price = (bar.high + bar.low + bar.close) / Decimal("3")
    dollar_volume = bar.close * bar.volume if bar.volume is not None else None
    del snapshot_timestamp
    return (
        HistoricalLoadedBar(
            symbol=bar.symbol,
            contract_id=bar.contract_id,
            timestamp=parsed_timestamp,
            raw_timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            wap=bar.wap,
            bar_count=bar.bar_count,
            typical_price=typical_price,
            dollar_volume=dollar_volume,
            interval_seconds=_bar_size_seconds(bar.bar_size),
            duration=bar.duration,
            bar_size=bar.bar_size,
            what_to_show=bar.what_to_show,
            use_rth=bar.use_rth,
        ),
        issues,
    )


def _dataset_summary(
    entry: HistoricalSnapshotIndexEntry,
    manifest: HistoricalSnapshotManifest,
    bars: list[HistoricalLoadedBar],
    *,
    issues: list[HistoricalLoadIssue],
    now: datetime,
) -> HistoricalDatasetSummary:
    timestamps = [bar.timestamp for bar in bars]
    duplicates = len(timestamps) - len(set(timestamps))
    expected_gap = _bar_size_seconds(manifest.bar_size)
    largest_gap: float | None = None
    missing_gap_count = 0
    for previous, current in zip(timestamps, timestamps[1:], strict=False):
        gap_seconds = (current - previous).total_seconds()
        largest_gap = gap_seconds if largest_gap is None else max(largest_gap, gap_seconds)
        if expected_gap and gap_seconds > expected_gap * 1.5:
            missing_gap_count += 1

    malformed_count = sum(1 for issue in issues if issue.code == "malformed_jsonl_line")
    invalid_ohlc_count = sum(1 for issue in issues if issue.code == "invalid_ohlc")
    negative_volume_count = sum(1 for issue in issues if issue.code == "negative_volume")
    zero_volume_timestamps = [
        bar.timestamp.isoformat()
        for bar in bars
        if bar.volume is not None and bar.volume == 0
    ]
    manifest_matches_bars = manifest.bar_count == len(bars)
    stale_snapshot = (
        now - manifest.generated_at
    ).total_seconds() > _SNAPSHOT_STALE_AFTER_SECONDS

    warnings: list[str] = []
    errors: list[str] = []
    if not bars:
        errors.append("dataset contains no loadable bars")
    if duplicates:
        warnings.append(f"duplicate timestamps detected: {duplicates}")
    if missing_gap_count:
        warnings.append(f"timestamp gaps detected: {missing_gap_count}")
    if malformed_count:
        target = errors if any(issue.severity == "error" for issue in issues) else warnings
        target.append(f"malformed JSONL lines detected: {malformed_count}")
    if invalid_ohlc_count:
        errors.append(f"invalid OHLC bars detected: {invalid_ohlc_count}")
    if negative_volume_count:
        errors.append(f"negative-volume bars detected: {negative_volume_count}")
    if not manifest_matches_bars:
        warnings.append(
            f"manifest bar_count {manifest.bar_count} does not match loaded bars {len(bars)}"
        )
    if stale_snapshot:
        warnings.append("snapshot is older than 48 hours")

    status = HistoricalLoadStatus.LOADED
    if errors:
        status = HistoricalLoadStatus.FAILED
    elif warnings:
        status = HistoricalLoadStatus.PARTIAL

    return HistoricalDatasetSummary(
        symbol=entry.symbol,
        bar_size=entry.bar_size,
        what_to_show=entry.what_to_show,
        snapshot_timestamp=entry.snapshot_timestamp,
        bars_path=entry.bars_path,
        manifest_path=entry.manifest_path,
        bars_count=len(bars),
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        duplicate_timestamps_count=duplicates,
        missing_gap_count=missing_gap_count,
        largest_gap_seconds=largest_gap,
        zero_volume_count=len(zero_volume_timestamps),
        zero_volume_sample_timestamps=zero_volume_timestamps[:_QUALITY_SAMPLE_LIMIT],
        malformed_line_count=malformed_count,
        invalid_ohlc_count=invalid_ohlc_count,
        negative_volume_count=negative_volume_count,
        stale_snapshot=stale_snapshot,
        manifest_bar_count=manifest.bar_count,
        manifest_matches_bars=manifest_matches_bars,
        load_status=status,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )


def _metadata_issues(
    entry: HistoricalSnapshotIndexEntry,
    manifest: HistoricalSnapshotManifest,
    manifest_path: Path,
    bars_path: Path,
) -> list[HistoricalLoadIssue]:
    issues: list[HistoricalLoadIssue] = []
    if manifest.symbol.strip().upper() != entry.symbol:
        issues.append(
            _issue(
                entry.symbol,
                "warning",
                "manifest_symbol_mismatch",
                f"manifest symbol {manifest.symbol} does not match index symbol {entry.symbol}",
                manifest_path,
            )
        )
    if manifest.bar_size != entry.bar_size:
        issues.append(
            _issue(
                entry.symbol,
                "warning",
                "manifest_bar_size_mismatch",
                f"manifest bar_size {manifest.bar_size} does not match index {entry.bar_size}",
                manifest_path,
            )
        )
    if manifest.what_to_show.strip().upper() != entry.what_to_show:
        issues.append(
            _issue(
                entry.symbol,
                "warning",
                "manifest_what_to_show_mismatch",
                "manifest what_to_show does not match index",
                manifest_path,
            )
        )
    if bars_path.name != f"{entry.snapshot_timestamp}{_BARS_SUFFIX}":
        issues.append(
            _issue(
                entry.symbol,
                "warning",
                "bars_path_timestamp_mismatch",
                "bars filename does not match selected snapshot timestamp",
                bars_path,
            )
        )
    return issues


def _failed_result(
    entry: HistoricalSnapshotIndexEntry,
    request: HistoricalSnapshotLoadRequest,
    issues: list[HistoricalLoadIssue],
    errors: list[str],
) -> HistoricalLoadResult:
    return HistoricalLoadResult(
        symbol=entry.symbol,
        request=request,
        index_entry=entry,
        issues=issues,
        errors=errors,
        load_status=HistoricalLoadStatus.FAILED,
    )


def _issue(
    symbol: str,
    severity: str,
    code: str,
    message: str,
    path: Path,
) -> HistoricalLoadIssue:
    return HistoricalLoadIssue(
        symbol=symbol,
        severity=severity,
        code=code,
        message=message,
        path=path.as_posix(),
    )


def _entry_matches_request(
    entry: HistoricalSnapshotIndexEntry,
    request: HistoricalSnapshotLoadRequest,
) -> bool:
    if request.symbols and entry.symbol not in request.symbols:
        return False
    if request.bar_size and _slugify(entry.bar_size) != _slugify(request.bar_size):
        return False
    if request.what_to_show and entry.what_to_show.upper() != request.what_to_show.upper():
        return False
    return not (
        request.snapshot_timestamp and entry.snapshot_timestamp != request.snapshot_timestamp
    )


def _entry_sort_key(entry: HistoricalSnapshotIndexEntry) -> tuple[str, datetime, str]:
    generated_at = entry.generated_at or _parse_snapshot_timestamp(entry.snapshot_timestamp)
    return (entry.symbol, generated_at, entry.snapshot_timestamp)


def _timestamp_from_manifest_path(path: Path) -> str:
    name = path.name
    if name.endswith(_MANIFEST_SUFFIX):
        return name[: -len(_MANIFEST_SUFFIX)]
    return path.stem


def _resolve_bars_path(
    manifest: HistoricalSnapshotManifest,
    manifest_path: Path,
    *,
    fallback: Path | None = None,
) -> Path:
    candidates: list[Path] = []
    if manifest.snapshot_path:
        configured = Path(manifest.snapshot_path)
        candidates.append(configured)
        if not configured.is_absolute():
            candidates.append(manifest_path.parent / configured.name)
    if fallback is not None:
        candidates.append(fallback)
    candidates.append(
        manifest_path.with_name(
            manifest_path.name.replace(_MANIFEST_SUFFIX, _BARS_SUFFIX)
        )
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _count_jsonl_records(path: Path) -> int | None:
    if not path.exists():
        return None
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def _parse_snapshot_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _parse_bar_timestamp(value: str) -> datetime | None:
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _bar_size_seconds(value: str) -> float | None:
    match = re.match(r"^\s*(\d+)\s*([A-Za-z]+)", value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("sec"):
        return amount
    if unit.startswith("min"):
        return amount * 60
    if unit.startswith("hour"):
        return amount * 60 * 60
    if unit.startswith("day"):
        return amount * 24 * 60 * 60
    return None


def _ohlc_is_valid(bar: HistoricalSnapshotBar) -> bool:
    try:
        open_ = Decimal(bar.open)
        high = Decimal(bar.high)
        low = Decimal(bar.low)
        close = Decimal(bar.close)
    except (InvalidOperation, TypeError, ValueError):
        return False
    return high >= max(open_, close, low) and low <= min(open_, close, high)


def _slugify(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_") or "unknown"
