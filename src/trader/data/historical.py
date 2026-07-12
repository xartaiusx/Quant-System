"""Local historical snapshot storage and readiness checks."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trader.config import TraderConfig
from trader.models import (
    HistoricalDataQualityIssue,
    HistoricalReadinessReport,
    HistoricalReadinessStatus,
    HistoricalReadinessSummary,
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    HistoricalSnapshotReport,
    HistoricalSnapshotRequest,
    HistoricalSnapshotResult,
    utc_now,
)

DEFAULT_HISTORICAL_ROOT = Path("data/historical")
_SNAPSHOT_STALE_AFTER_SECONDS = 48 * 60 * 60
_MIN_READY_BARS = 1
_QUALITY_SAMPLE_LIMIT = 5
_IBKR_TIMEZONE_ALIASES = {
    "GMT": "UTC",
    "US/Eastern": "America/New_York",
}


def write_historical_snapshot_result(
    result: HistoricalSnapshotResult,
    *,
    base_dir: str | Path = DEFAULT_HISTORICAL_ROOT,
    timestamp_slug: str | None = None,
) -> HistoricalSnapshotResult:
    """Write one successful snapshot result as JSONL plus a manifest."""

    if not result.bars or result.manifest is None:
        return result

    timestamp = timestamp_slug or utc_now().strftime("%Y%m%dT%H%M%SZ")
    base_path = Path(base_dir)
    snapshot_dir = (
        base_path
        / result.symbol
        / _slugify(result.request.bar_size)
        / _slugify(result.request.what_to_show.upper()).upper()
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{timestamp}_bars.jsonl"
    manifest_path = snapshot_dir / f"{timestamp}_manifest.json"

    snapshot_path.write_text(
        "".join(
            json.dumps(bar.model_dump(mode="json"), sort_keys=True) + "\n"
            for bar in result.bars
        )
    )

    manifest = result.manifest.model_copy(
        update={
            "snapshot_path": snapshot_path.as_posix(),
            "manifest_path": manifest_path.as_posix(),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return result.model_copy(
        update={
            "manifest": manifest,
            "snapshot_path": snapshot_path.as_posix(),
            "manifest_path": manifest_path.as_posix(),
        }
    )


def attach_snapshot_paths(report: HistoricalSnapshotReport) -> HistoricalSnapshotReport:
    """Refresh aggregate path lists after per-symbol snapshots are written."""

    snapshot_paths = [
        result.snapshot_path for result in report.results if result.snapshot_path is not None
    ]
    manifest_paths = [
        result.manifest_path for result in report.results if result.manifest_path is not None
    ]
    return report.model_copy(
        update={"snapshot_paths": snapshot_paths, "manifest_paths": manifest_paths}
    )


def latest_manifest_paths(
    *,
    base_dir: str | Path = DEFAULT_HISTORICAL_ROOT,
) -> list[Path]:
    """Return the latest manifest path for each symbol under the snapshot root."""

    root = Path(base_dir)
    if not root.exists():
        return []

    by_symbol: dict[str, list[tuple[datetime, Path]]] = defaultdict(list)
    for path in root.glob("*/*/*/*_manifest.json"):
        try:
            manifest = load_manifest(path)
        except (OSError, ValueError):
            continue
        by_symbol[manifest.symbol].append((manifest.generated_at, path))

    latest_paths = []
    for entries in by_symbol.values():
        latest_paths.append(sorted(entries, key=lambda item: item[0])[-1][1])
    return sorted(latest_paths)


def build_readiness_report(
    config: TraderConfig,
    *,
    manifest_paths: Iterable[str | Path] | None = None,
    base_dir: str | Path = DEFAULT_HISTORICAL_ROOT,
    latest: bool = False,
    now: datetime | None = None,
) -> HistoricalReadinessReport:
    """Build a readiness report from local snapshot manifests."""

    selected_paths = (
        latest_manifest_paths(base_dir=base_dir)
        if latest
        else [Path(path) for path in (manifest_paths or [])]
    )
    if not selected_paths:
        return HistoricalReadinessReport(
            ok=False,
            mode=config.trading_mode.value,
            host=config.ibkr_host,
            port=config.ibkr_port,
            client_id=config.ibkr_client_id,
            broker_kind=config.inferred_broker_kind,
            errors=["no historical snapshot manifests found"],
            final_status="failed",
        )

    summaries: list[HistoricalReadinessSummary] = []
    report_warnings: list[str] = []
    report_errors: list[str] = []
    requests: list[HistoricalSnapshotRequest] = []
    snapshot_paths: list[str] = []
    manifest_path_strings: list[str] = []

    for path in selected_paths:
        manifest_path = Path(path)
        try:
            manifest = load_manifest(manifest_path)
            bars = load_snapshot_bars(manifest, manifest_path=manifest_path)
            summary = readiness_summary_for_snapshot(manifest, bars, now=now)
            requests.append(
                HistoricalSnapshotRequest(
                    symbols=[manifest.symbol],
                    duration=manifest.duration,
                    bar_size=manifest.bar_size,
                    what_to_show=manifest.what_to_show,
                    use_rth=manifest.use_rth,
                    timeout_seconds=manifest.request_timeout,
                )
            )
            if manifest.snapshot_path:
                snapshot_paths.append(manifest.snapshot_path)
            manifest_path_strings.append(manifest_path.as_posix())
            summaries.append(summary)
        except (OSError, ValueError) as exc:
            report_errors.append(f"{manifest_path}: {exc}")

    ready_or_partial = any(
        summary.readiness_status
        in {HistoricalReadinessStatus.READY, HistoricalReadinessStatus.PARTIAL}
        for summary in summaries
    )
    failed = any(
        summary.readiness_status == HistoricalReadinessStatus.FAILED
        for summary in summaries
    )
    final_status = "ready"
    if failed and ready_or_partial:
        final_status = "partial"
    elif not ready_or_partial:
        final_status = "failed"
    elif any(
        summary.readiness_status == HistoricalReadinessStatus.PARTIAL
        for summary in summaries
    ):
        final_status = "partial"

    report_warnings.extend(
        warning for summary in summaries for warning in summary.warnings
    )
    report_errors.extend(error for summary in summaries for error in summary.errors)

    return HistoricalReadinessReport(
        ok=ready_or_partial,
        mode=config.trading_mode.value,
        host=config.ibkr_host,
        port=config.ibkr_port,
        client_id=config.ibkr_client_id,
        broker_kind=config.inferred_broker_kind,
        requests=requests,
        symbols_requested=[summary.symbol for summary in summaries],
        snapshot_paths=snapshot_paths,
        manifest_paths=manifest_path_strings,
        summaries=summaries,
        errors=list(dict.fromkeys(report_errors)),
        warnings=list(
            dict.fromkeys(
                [
                    *report_warnings,
                    "No order APIs invoked; order routing: disabled",
                ]
            )
        ),
        final_status=final_status,
    )


def load_manifest(path: str | Path) -> HistoricalSnapshotManifest:
    """Load a snapshot manifest from disk."""

    return HistoricalSnapshotManifest.model_validate_json(Path(path).read_text())


def load_snapshot_bars(
    manifest: HistoricalSnapshotManifest,
    *,
    manifest_path: str | Path | None = None,
) -> list[HistoricalSnapshotBar]:
    """Load snapshot bars from the manifest's JSONL path."""

    snapshot_path = _resolve_snapshot_path(manifest, manifest_path=manifest_path)
    bars: list[HistoricalSnapshotBar] = []
    if not snapshot_path.exists():
        raise ValueError(f"snapshot file not found: {snapshot_path}")
    for line in snapshot_path.read_text().splitlines():
        if not line.strip():
            continue
        bars.append(HistoricalSnapshotBar.model_validate_json(line))
    return bars


def readiness_summary_for_snapshot(
    manifest: HistoricalSnapshotManifest,
    bars: list[HistoricalSnapshotBar],
    *,
    now: datetime | None = None,
) -> HistoricalReadinessSummary:
    """Validate one historical snapshot and return a readiness summary."""

    reference = now or utc_now()
    issues: list[HistoricalDataQualityIssue] = []
    warnings: list[str] = list(manifest.warnings)
    errors: list[str] = [error.message for error in manifest.errors]
    parsed: list[tuple[datetime, HistoricalSnapshotBar]] = []

    for bar in bars:
        parsed_timestamp = parse_ibkr_bar_timestamp(bar.timestamp)
        if parsed_timestamp is None:
            issues.append(
                HistoricalDataQualityIssue(
                    symbol=manifest.symbol,
                    severity="error",
                    code="timestamp_parse_failed",
                    message=f"timestamp could not be parsed: {bar.timestamp}",
                    timestamp=bar.timestamp,
                )
            )
            continue
        parsed.append((parsed_timestamp, bar))

    timestamps = [timestamp for timestamp, _bar in parsed]
    sorted_timestamps = timestamps == sorted(timestamps)
    duplicate_timestamps_count = len(timestamps) - len(set(timestamps))
    expected_gap_seconds = _bar_size_seconds(manifest.bar_size)
    largest_gap_seconds: float | None = None
    missing_timestamp_gaps: list[str] = []
    sorted_values = sorted(timestamps)
    for previous, current in zip(sorted_values, sorted_values[1:], strict=False):
        gap_seconds = (current - previous).total_seconds()
        largest_gap_seconds = (
            gap_seconds
            if largest_gap_seconds is None
            else max(largest_gap_seconds, gap_seconds)
        )
        if expected_gap_seconds and gap_seconds > expected_gap_seconds * 1.5:
            missing_timestamp_gaps.append(
                f"{previous.isoformat()} to {current.isoformat()} gap {gap_seconds:g}s"
            )

    zero_volume_timestamps = [
        timestamp.isoformat()
        for timestamp, bar in parsed
        if bar.volume is not None and bar.volume == 0
    ]
    zero_volume_bars = len(zero_volume_timestamps)
    negative_volume_bars = sum(
        1 for _timestamp, bar in parsed if bar.volume is not None and bar.volume < 0
    )
    invalid_ohlc_bars = 0
    for _timestamp, bar in parsed:
        if not _ohlc_is_valid(bar):
            invalid_ohlc_bars += 1

    stale_snapshot = (
        reference - manifest.generated_at
    ).total_seconds() > _SNAPSHOT_STALE_AFTER_SECONDS

    if not bars:
        errors.append("snapshot contains no bars")
    if len(bars) < _MIN_READY_BARS:
        warnings.append(f"bar count below minimum threshold {_MIN_READY_BARS}")
    if not parsed and bars:
        errors.append("no parseable timestamps found")
    if not sorted_timestamps:
        warnings.append("timestamps are not sorted")
    if duplicate_timestamps_count:
        warnings.append(f"duplicate timestamps detected: {duplicate_timestamps_count}")
    if missing_timestamp_gaps:
        warnings.append(f"timestamp gaps detected: {len(missing_timestamp_gaps)}")
    if zero_volume_bars:
        warnings.append(f"zero-volume bars detected: {zero_volume_bars}")
    if negative_volume_bars:
        errors.append(f"negative-volume bars detected: {negative_volume_bars}")
    if invalid_ohlc_bars:
        errors.append(f"invalid OHLC bars detected: {invalid_ohlc_bars}")
    if stale_snapshot:
        warnings.append("snapshot is older than 48 hours")

    first_timestamp = min(timestamps).isoformat() if timestamps else None
    last_timestamp = max(timestamps).isoformat() if timestamps else None
    if first_timestamp is None or last_timestamp is None:
        errors.append("first or last timestamp is missing")

    status = HistoricalReadinessStatus.READY
    if errors:
        status = HistoricalReadinessStatus.FAILED
    elif warnings or issues:
        status = HistoricalReadinessStatus.PARTIAL

    return HistoricalReadinessSummary(
        symbol=manifest.symbol,
        resolved_contract_id=manifest.contract_id,
        requested_duration=manifest.duration,
        requested_bar_size=manifest.bar_size,
        requested_what_to_show=manifest.what_to_show,
        use_rth=manifest.use_rth,
        bars_count=len(bars),
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        sorted_timestamps=sorted_timestamps,
        duplicate_timestamps_count=duplicate_timestamps_count,
        missing_timestamp_gaps=missing_timestamp_gaps,
        largest_gap_seconds=largest_gap_seconds,
        zero_volume_bars=zero_volume_bars,
        zero_volume_sample_timestamps=zero_volume_timestamps[:_QUALITY_SAMPLE_LIMIT],
        negative_volume_bars=negative_volume_bars,
        invalid_ohlc_bars=invalid_ohlc_bars,
        stale_snapshot=stale_snapshot,
        readiness_status=status,
        snapshot_path=manifest.snapshot_path,
        manifest_path=manifest.manifest_path,
        issues=issues,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )


def _resolve_snapshot_path(
    manifest: HistoricalSnapshotManifest,
    *,
    manifest_path: str | Path | None,
) -> Path:
    if manifest.snapshot_path:
        configured = Path(manifest.snapshot_path)
        if configured.is_absolute() or manifest_path is None:
            return configured
        manifest_parent = Path(manifest_path).parent
        candidates = [
            manifest_parent / configured.name,
            manifest_parent / configured,
            configured,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]
    if manifest_path is None:
        raise ValueError("manifest has no snapshot_path")
    inferred_name = Path(manifest_path).name.replace("_manifest.json", "_bars.jsonl")
    return Path(manifest_path).with_name(inferred_name)


def parse_ibkr_bar_timestamp(value: str) -> datetime | None:
    """Normalize supported IBKR bar timestamps to UTC or fail closed."""
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    zoned_match = re.fullmatch(
        r"(?P<timestamp>\d{8} \d{2}:\d{2}:\d{2}) (?P<timezone>[A-Za-z0-9_+\-/]+)",
        normalized,
    )
    if zoned_match is not None:
        try:
            parsed = datetime.strptime(zoned_match.group("timestamp"), "%Y%m%d %H:%M:%S")
            timezone_name = _IBKR_TIMEZONE_ALIASES.get(
                zoned_match.group("timezone"),
                zoned_match.group("timezone"),
            )
            timezone = ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError):
            return None
        return parsed.replace(tzinfo=timezone).astimezone(UTC)
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
