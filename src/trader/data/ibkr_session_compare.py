"""Broker-free comparison of two ignored IBKR historical sessions."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from trader.data.historical import (
    load_manifest,
    load_snapshot_bars,
    parse_ibkr_bar_timestamp,
)
from trader.models import (
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    HistoricalVolumeUnit,
    IBKRSessionBarRevision,
    IBKRSessionCompareReport,
    IBKRSessionCompareRequest,
    IBKRSessionCompareStatus,
    utc_now,
)

_COMPARISON_FIELDS = ("open", "high", "low", "close", "volume", "wap", "bar_count")
_REVISION_SAMPLE_LIMIT = 100


def compare_ibkr_sessions(
    request: IBKRSessionCompareRequest,
    *,
    now: datetime | None = None,
) -> IBKRSessionCompareReport:
    """Compare two local snapshot revisions without importing broker code."""

    timestamp = now or utc_now()
    warnings: list[str] = []
    errors: list[str] = []
    try:
        baseline_manifest_path = Path(request.baseline_manifest_path)
        candidate_manifest_path = Path(request.candidate_manifest_path)
        baseline_manifest = load_manifest(baseline_manifest_path)
        candidate_manifest = load_manifest(candidate_manifest_path)
        baseline_bars = load_snapshot_bars(
            baseline_manifest,
            manifest_path=baseline_manifest_path,
        )
        candidate_bars = load_snapshot_bars(
            candidate_manifest,
            manifest_path=candidate_manifest_path,
        )
    except (OSError, ValueError) as exc:
        return IBKRSessionCompareReport(
            ok=False,
            request=request,
            errors=[f"session snapshots could not be loaded: {exc}"],
            final_status=IBKRSessionCompareStatus.FAILED,
            timestamp=timestamp,
        )

    parameter_errors = _parameter_errors(baseline_manifest, candidate_manifest)
    errors.extend(parameter_errors)
    baseline_by_time, baseline_duplicate_errors = _bars_by_timestamp(
        baseline_bars,
        label="baseline",
    )
    candidate_by_time, candidate_duplicate_errors = _bars_by_timestamp(
        candidate_bars,
        label="candidate",
    )
    errors.extend(baseline_duplicate_errors)
    errors.extend(candidate_duplicate_errors)

    volume_authoritative = (
        baseline_manifest.volume_unit != HistoricalVolumeUnit.UNKNOWN
        and baseline_manifest.volume_unit == candidate_manifest.volume_unit
    )
    if not volume_authoritative:
        warnings.append(
            "volume comparison is non-authoritative until both manifests attest the "
            "same non-unknown volume unit"
        )

    revisions: list[IBKRSessionBarRevision] = []
    matching = 0
    baseline_times = set(baseline_by_time)
    candidate_times = set(candidate_by_time)
    for bar_timestamp in sorted(baseline_times | candidate_times):
        baseline = baseline_by_time.get(bar_timestamp)
        candidate = candidate_by_time.get(bar_timestamp)
        if baseline is None or candidate is None:
            revisions.append(
                IBKRSessionBarRevision(
                    timestamp=bar_timestamp,
                    changed_fields=["missing_bar"],
                    baseline=_bar_values(baseline),
                    candidate=_bar_values(candidate),
                )
            )
            continue
        changed_fields = [
            field
            for field in _COMPARISON_FIELDS
            if getattr(baseline, field) != getattr(candidate, field)
        ]
        if baseline.timestamp != candidate.timestamp:
            changed_fields.insert(0, "raw_timestamp")
        if changed_fields:
            revisions.append(
                IBKRSessionBarRevision(
                    timestamp=bar_timestamp,
                    changed_fields=changed_fields,
                    baseline=_bar_values(baseline),
                    candidate=_bar_values(candidate),
                )
            )
        else:
            matching += 1

    if len(revisions) > _REVISION_SAMPLE_LIMIT:
        warnings.append(
            f"revision details truncated to {_REVISION_SAMPLE_LIMIT} rows"
        )

    parameters_compatible = not parameter_errors
    if errors:
        final_status = (
            IBKRSessionCompareStatus.INCOMPATIBLE
            if parameter_errors and not baseline_duplicate_errors and not candidate_duplicate_errors
            else IBKRSessionCompareStatus.FAILED
        )
    elif revisions:
        final_status = IBKRSessionCompareStatus.REVISED
    else:
        final_status = IBKRSessionCompareStatus.IDENTICAL

    return IBKRSessionCompareReport(
        ok=not errors,
        request=request,
        symbol=baseline_manifest.symbol,
        baseline_generated_at=baseline_manifest.generated_at,
        candidate_generated_at=candidate_manifest.generated_at,
        baseline_bar_count=len(baseline_bars),
        candidate_bar_count=len(candidate_bars),
        matching_bar_count=matching,
        revised_bar_count=sum(
            1 for revision in revisions if revision.changed_fields != ["missing_bar"]
        ),
        baseline_only_count=len(baseline_times - candidate_times),
        candidate_only_count=len(candidate_times - baseline_times),
        parameters_compatible=parameters_compatible,
        volume_comparison_authoritative=volume_authoritative,
        baseline_volume_unit=baseline_manifest.volume_unit,
        candidate_volume_unit=candidate_manifest.volume_unit,
        baseline_checksum_sha256=_bars_checksum(baseline_bars),
        candidate_checksum_sha256=_bars_checksum(candidate_bars),
        revisions=revisions[:_REVISION_SAMPLE_LIMIT],
        warnings=warnings,
        errors=errors,
        final_status=final_status,
        timestamp=timestamp,
    )


def _parameter_errors(
    baseline: HistoricalSnapshotManifest,
    candidate: HistoricalSnapshotManifest,
) -> list[str]:
    errors: list[str] = []
    fields = ("symbol", "contract_id", "duration", "bar_size", "what_to_show", "use_rth")
    for field in fields:
        if getattr(baseline, field) != getattr(candidate, field):
            errors.append(f"snapshot parameter mismatch: {field}")
    if baseline.end_datetime != candidate.end_datetime:
        errors.append("snapshot parameter mismatch: end_datetime")
    return errors


def _bars_by_timestamp(
    bars: list[HistoricalSnapshotBar],
    *,
    label: str,
) -> tuple[dict[str, HistoricalSnapshotBar], list[str]]:
    indexed: dict[str, HistoricalSnapshotBar] = {}
    errors: list[str] = []
    for bar in bars:
        parsed = parse_ibkr_bar_timestamp(bar.timestamp)
        if parsed is None:
            errors.append(f"{label} snapshot has unparseable timestamp {bar.timestamp}")
            continue
        normalized_timestamp = parsed.isoformat()
        if normalized_timestamp in indexed:
            errors.append(
                f"{label} snapshot contains duplicate timestamp {normalized_timestamp}"
            )
            continue
        indexed[normalized_timestamp] = bar
    return indexed, errors


def _bar_values(bar: HistoricalSnapshotBar | None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {
        field: getattr(bar, field)
        for field in _COMPARISON_FIELDS
    }


def _bars_checksum(bars: list[HistoricalSnapshotBar]) -> str:
    payload = [bar.model_dump(mode="json") for bar in bars]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()
