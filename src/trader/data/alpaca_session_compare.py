"""Offline correction comparison for immutable Alpaca SPY session captures."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from trader.data.alpaca_session_artifacts import (
    AlpacaSessionArtifactError,
    LoadedAlpacaSession,
    load_alpaca_session,
)
from trader.models import (
    AlpacaSessionBarRevision,
    AlpacaSessionCompareReport,
    AlpacaSessionCompareRequest,
    AlpacaSessionCompareStatus,
    utc_now,
)

_FIELDS = ("o", "h", "l", "c", "v", "n", "vw")
_REVISION_SAMPLE_LIMIT = 100


def compare_alpaca_sessions(
    request: AlpacaSessionCompareRequest,
    *,
    now: datetime | None = None,
) -> AlpacaSessionCompareReport:
    """Compare two local captures without credentials, network, broker, or orders."""

    timestamp = now or utc_now()
    try:
        baseline = load_alpaca_session(Path(request.baseline_manifest_path))
        candidate = load_alpaca_session(Path(request.candidate_manifest_path))
    except (OSError, AlpacaSessionArtifactError, ValueError) as exc:
        return AlpacaSessionCompareReport(
            ok=False,
            request=request,
            errors=[f"Alpaca session artifacts could not be loaded: {exc}"],
            final_status=AlpacaSessionCompareStatus.FAILED,
            timestamp=timestamp,
        )

    parameter_errors = _parameter_errors(baseline, candidate)
    revisions: list[AlpacaSessionBarRevision] = []
    matching = 0
    baseline_times = set(baseline.canonical_bars)
    candidate_times = set(candidate.canonical_bars)
    for bar_timestamp in sorted(baseline_times | candidate_times):
        baseline_bar = baseline.canonical_bars.get(bar_timestamp)
        candidate_bar = candidate.canonical_bars.get(bar_timestamp)
        if baseline_bar is None:
            revisions.append(
                AlpacaSessionBarRevision(
                    timestamp=bar_timestamp,
                    classification="added",
                    changed_fields=["added_bar"],
                    candidate=_plain_values(candidate_bar),
                )
            )
            continue
        if candidate_bar is None:
            revisions.append(
                AlpacaSessionBarRevision(
                    timestamp=bar_timestamp,
                    classification="missing",
                    changed_fields=["missing_bar"],
                    baseline=_plain_values(baseline_bar),
                )
            )
            continue
        changed = [field for field in _FIELDS if baseline_bar[field] != candidate_bar[field]]
        if changed:
            revisions.append(
                AlpacaSessionBarRevision(
                    timestamp=bar_timestamp,
                    classification="revised",
                    changed_fields=changed,
                    baseline=_plain_values(baseline_bar),
                    candidate=_plain_values(candidate_bar),
                )
            )
        else:
            matching += 1

    warnings: list[str] = []
    if len(revisions) > _REVISION_SAMPLE_LIMIT:
        warnings.append(f"revision details truncated to {_REVISION_SAMPLE_LIMIT} rows")
    if parameter_errors:
        final_status = AlpacaSessionCompareStatus.INCOMPATIBLE
    elif revisions:
        final_status = AlpacaSessionCompareStatus.REVISED
    else:
        final_status = AlpacaSessionCompareStatus.IDENTICAL
    baseline_manifest = baseline.manifest
    candidate_manifest = candidate.manifest
    return AlpacaSessionCompareReport(
        ok=not parameter_errors,
        request=request,
        symbol="SPY",
        session_date=_parse_date(str(baseline_manifest["session_date"])),
        baseline_acquired_at=_parse_datetime(str(baseline_manifest["acquired_at"])),
        candidate_acquired_at=_parse_datetime(str(candidate_manifest["acquired_at"])),
        baseline_bar_count=len(baseline.canonical_bars),
        candidate_bar_count=len(candidate.canonical_bars),
        matching_bar_count=matching,
        revised_bar_count=sum(
            revision.classification == "revised" for revision in revisions
        ),
        missing_bar_count=len(baseline_times - candidate_times),
        added_bar_count=len(candidate_times - baseline_times),
        parameters_compatible=not parameter_errors,
        baseline_manifest_sha256=baseline.manifest_sha256,
        candidate_manifest_sha256=candidate.manifest_sha256,
        baseline_data_sha256=str(baseline_manifest["data_sha256"]),
        candidate_data_sha256=str(candidate_manifest["data_sha256"]),
        revisions=revisions[:_REVISION_SAMPLE_LIMIT],
        warnings=warnings,
        errors=parameter_errors,
        final_status=final_status,
        timestamp=timestamp,
    )


def _parameter_errors(
    baseline: LoadedAlpacaSession,
    candidate: LoadedAlpacaSession,
) -> list[str]:
    fields = (
        "source",
        "capture_mode",
        "session_calendar",
        "session_date",
        "session_open",
        "session_close",
        "last_minute_start",
        "expected_bar_count",
        "expected_timestamp_sha256",
    )
    errors = [
        f"session parameter mismatch: {field}"
        for field in fields
        if baseline.manifest.get(field) != candidate.manifest.get(field)
    ]
    request_fields = ("symbol", "feed", "timeframe", "adjustment", "sort", "start", "end")
    for field in request_fields:
        if baseline.manifest["request"].get(field) != candidate.manifest["request"].get(field):
            errors.append(f"session request mismatch: {field}")
    return errors


def _plain_values(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {field: values[field] for field in _FIELDS}


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("acquisition timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


__all__ = ["compare_alpaca_sessions"]
