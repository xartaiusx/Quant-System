"""Pure offline validation for immutable Alpaca SPY session captures."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]

_BAR_FIELDS = ("o", "h", "l", "c", "v", "n", "vw")
_PRICE_FIELDS = ("o", "h", "l", "c", "vw")


class AlpacaSessionArtifactError(ValueError):
    """An immutable session artifact failed an offline integrity check."""


@dataclass(frozen=True)
class LoadedAlpacaSession:
    manifest_path: Path
    manifest_sha256: str
    manifest: dict[str, Any]
    bars: list[dict[str, Any]]
    canonical_bars: dict[str, dict[str, Decimal | int]]


def load_alpaca_session(manifest_path: Path) -> LoadedAlpacaSession:
    """Load and revalidate a complete session manifest, raw pages, and data file."""

    resolved = manifest_path.expanduser().resolve()
    try:
        manifest = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlpacaSessionArtifactError(f"manifest could not be loaded: {exc}") from exc
    if not isinstance(manifest, dict):
        raise AlpacaSessionArtifactError("manifest must be a JSON object")
    _validate_manifest_contract(manifest)
    run_dir = resolved.parent
    _validate_response_attempts(run_dir, manifest)
    raw_bars = _validate_raw_pages(run_dir, manifest)

    data_path = _contained_file(run_dir, manifest.get("data_file"), "data file")
    if _sha256_file(data_path) != manifest.get("data_sha256"):
        raise AlpacaSessionArtifactError("session data checksum mismatch")
    try:
        with gzip.open(data_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlpacaSessionArtifactError(f"session data could not be loaded: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
        raise AlpacaSessionArtifactError("session data must contain a bars array")

    session_date, expected = _expected_session(manifest)
    _validate_payload_metadata(payload, manifest, session_date=session_date)
    bars = payload["bars"]
    if raw_bars != bars:
        raise AlpacaSessionArtifactError(
            "assembled raw pages do not match the immutable session data"
        )
    canonical = _canonical_bars(bars, expected=expected)
    timestamps = list(canonical)
    if int(manifest.get("bar_count", -1)) != len(timestamps):
        raise AlpacaSessionArtifactError("manifest bar count does not match session data")
    if _normalized_timestamp(manifest.get("first_timestamp")) != timestamps[0]:
        raise AlpacaSessionArtifactError("manifest first timestamp does not match session data")
    if _normalized_timestamp(manifest.get("last_timestamp")) != timestamps[-1]:
        raise AlpacaSessionArtifactError("manifest last timestamp does not match session data")
    return LoadedAlpacaSession(
        manifest_path=resolved,
        manifest_sha256=_sha256_file(resolved),
        manifest=manifest,
        bars=bars,
        canonical_bars=canonical,
    )


def discover_valid_session_manifests(output_root: Path) -> dict[date, list[Path]]:
    """Return checksum-valid immutable manifests grouped by XNYS session date."""

    grouped: dict[date, list[tuple[datetime, Path]]] = {}
    pattern = "symbol=SPY/session_date=*/runs/*/acquisition_manifest.json"
    for path in output_root.expanduser().resolve().glob(pattern):
        try:
            loaded = load_alpaca_session(path)
            session_date = date.fromisoformat(str(loaded.manifest["session_date"]))
            acquired_at = _parse_timestamp(loaded.manifest["acquired_at"])
        except (AlpacaSessionArtifactError, ValueError):
            continue
        grouped.setdefault(session_date, []).append((acquired_at, loaded.manifest_path))
    return {
        key: [path for _, path in sorted(values, key=lambda item: (item[0], item[1]))]
        for key, values in sorted(grouped.items())
    }


def _validate_manifest_contract(manifest: Mapping[str, Any]) -> None:
    if manifest.get("manifest_version") != 2:
        raise AlpacaSessionArtifactError("unsupported Alpaca session manifest version")
    expected_values = {
        "source": "alpaca_sip",
        "capture_mode": "session",
        "session_calendar": "XNYS",
        "rights_status": "written_rights_unverified",
    }
    for field, expected in expected_values.items():
        if manifest.get(field) != expected:
            raise AlpacaSessionArtifactError(f"manifest {field} must be {expected}")
    if manifest.get("session_complete") is not True:
        raise AlpacaSessionArtifactError("session manifest is not complete")
    if manifest.get("network_accessed") is not True:
        raise AlpacaSessionArtifactError("session manifest must attest network acquisition")
    false_fields = (
        "broker_contacted",
        "submitted_orders",
        "paper_orders_enabled",
        "order_api_invoked",
        "research_eligible",
        "promotion_eligible",
        "graduation_eligible",
        "automatically_activated",
        "automatically_derived",
        "automatically_backtested",
    )
    if any(manifest.get(field) is not False for field in false_fields):
        raise AlpacaSessionArtifactError("session manifest safety flags must remain false")
    request = manifest.get("request")
    if not isinstance(request, dict):
        raise AlpacaSessionArtifactError("session manifest request is missing")
    required_request = {
        "symbol": "SPY",
        "feed": "sip",
        "timeframe": "1Min",
        "adjustment": "raw",
        "sort": "asc",
        "capture_mode": "session",
        "session_calendar": "XNYS",
        "endpoint": "https://data.alpaca.markets/v2/stocks/SPY/bars",
    }
    for field, expected in required_request.items():
        if request.get(field) != expected:
            raise AlpacaSessionArtifactError(f"request {field} must be {expected}")
    if _json_sha256(request) != manifest.get("request_fingerprint"):
        raise AlpacaSessionArtifactError("session request fingerprint mismatch")


def _expected_session(
    manifest: Mapping[str, Any],
) -> tuple[date, tuple[datetime, ...]]:
    try:
        session_date = date.fromisoformat(str(manifest["session_date"]))
    except (KeyError, ValueError) as exc:
        raise AlpacaSessionArtifactError("manifest session date is invalid") from exc
    calendar = xcals.get_calendar("XNYS")
    if not calendar.is_session(session_date):
        raise AlpacaSessionArtifactError("manifest date is not an XNYS session")
    expected = tuple(
        value.to_pydatetime().astimezone(UTC)
        for value in calendar.session_minutes(session_date)
    )
    open_ = expected[0]
    close = calendar.session_close(session_date).to_pydatetime().astimezone(UTC)
    expected_hash = _timestamp_set_sha256(expected)
    checks = {
        "session_open": _iso_z(open_),
        "session_close": _iso_z(close),
        "last_minute_start": _iso_z(expected[-1]),
        "expected_bar_count": len(expected),
        "expected_timestamp_sha256": expected_hash,
    }
    for field, value in checks.items():
        if manifest.get(field) != value:
            raise AlpacaSessionArtifactError(f"manifest {field} does not match XNYS")
    request = manifest["request"]
    request_checks = {
        "session_date": session_date.isoformat(),
        "session_open": _iso_z(open_),
        "session_close": _iso_z(close),
        "start": _iso_z(open_),
        "end": _iso_z(expected[-1]),
        "expected_bar_count": str(len(expected)),
    }
    for field, value in request_checks.items():
        if request.get(field) != value:
            raise AlpacaSessionArtifactError(f"request {field} does not match XNYS")
    return session_date, expected


def _validate_payload_metadata(
    payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    session_date: date,
) -> None:
    expected = {
        "schema_version": 1,
        "source": "alpaca_sip",
        "symbol": "SPY",
        "feed": "sip",
        "timeframe": "1Min",
        "adjustment": "raw",
        "sort": "asc",
        "capture_mode": "session",
        "session_calendar": "XNYS",
        "session_date": session_date.isoformat(),
        "session_open": manifest["session_open"],
        "session_close": manifest["session_close"],
        "expected_bar_count": manifest["expected_bar_count"],
        "expected_timestamp_sha256": manifest["expected_timestamp_sha256"],
        "session_complete": True,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise AlpacaSessionArtifactError(f"session data {field} mismatch")


def _validate_raw_pages(
    run_dir: Path,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not pages:
        raise AlpacaSessionArtifactError("session manifest has no raw pages")
    raw_bars: list[dict[str, Any]] = []
    response_ids: list[str] = []
    for page in pages:
        if not isinstance(page, dict):
            raise AlpacaSessionArtifactError("session page metadata is invalid")
        page_path = _contained_file(run_dir, page.get("path"), "raw page")
        if _sha256_file(page_path) != page.get("sha256"):
            raise AlpacaSessionArtifactError("raw page checksum mismatch")
        try:
            payload = json.loads(page_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AlpacaSessionArtifactError("raw page could not be loaded") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
            raise AlpacaSessionArtifactError("raw page must contain a bars array")
        if payload.get("symbol") not in {None, "SPY"}:
            raise AlpacaSessionArtifactError("raw page symbol does not match SPY")
        bars = payload["bars"]
        if any(not isinstance(bar, dict) for bar in bars):
            raise AlpacaSessionArtifactError("raw page contains an invalid bar")
        if page.get("bar_count") != len(bars):
            raise AlpacaSessionArtifactError("raw page count metadata mismatch")
        first = bars[0].get("t") if bars else None
        last = bars[-1].get("t") if bars else None
        if page.get("first_timestamp") != first or page.get("last_timestamp") != last:
            raise AlpacaSessionArtifactError("raw page timestamp metadata mismatch")
        retrieved_at = page.get("retrieved_at")
        if not isinstance(retrieved_at, str):
            raise AlpacaSessionArtifactError("raw page retrieval time is missing")
        _parse_timestamp(retrieved_at)
        response_id = page.get("source_response_id")
        if response_id is not None:
            if not isinstance(response_id, str) or not response_id.strip():
                raise AlpacaSessionArtifactError("raw page response ID is invalid")
            response_ids.append(response_id)
        raw_bars.extend(bars)
    if manifest.get("source_response_ids") != response_ids:
        raise AlpacaSessionArtifactError("manifest response IDs do not match raw pages")
    return raw_bars


def _validate_response_attempts(
    run_dir: Path,
    manifest: Mapping[str, Any],
) -> None:
    attempts = manifest.get("response_attempts")
    if not isinstance(attempts, list) or not attempts:
        raise AlpacaSessionArtifactError("session manifest has no response attempts")
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise AlpacaSessionArtifactError("session manifest pages are invalid")
    pages_by_path = {str(page.get("path")): page for page in pages}
    accepted_raw_paths: list[str] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise AlpacaSessionArtifactError("response attempt metadata is invalid")
        attempt_path = _contained_file(run_dir, attempt.get("path"), "response attempt")
        if _sha256_file(attempt_path) != attempt.get("sha256"):
            raise AlpacaSessionArtifactError("response attempt checksum mismatch")
        if not isinstance(attempt.get("http_status"), int):
            raise AlpacaSessionArtifactError("response attempt HTTP status is invalid")
        retrieved_at = attempt.get("retrieved_at")
        if not isinstance(retrieved_at, str):
            raise AlpacaSessionArtifactError("response attempt retrieval time is missing")
        _parse_timestamp(retrieved_at)
        outcome = attempt.get("outcome")
        if outcome not in {
            "accepted",
            "interrupted",
            "rejected_http",
            "rejected_validation",
        }:
            raise AlpacaSessionArtifactError("response attempt outcome is invalid")
        if outcome == "accepted":
            if attempt.get("http_status") != 200:
                raise AlpacaSessionArtifactError(
                    "accepted response attempt must have HTTP status 200"
                )
            raw_page_path = attempt.get("raw_page_path")
            if not isinstance(raw_page_path, str):
                raise AlpacaSessionArtifactError("accepted response attempt has no raw page")
            page = pages_by_path.get(raw_page_path)
            if page is None:
                raise AlpacaSessionArtifactError(
                    "accepted response attempt references an unknown raw page"
                )
            if attempt.get("sha256") != page.get("sha256"):
                raise AlpacaSessionArtifactError(
                    "accepted response attempt checksum does not match its raw page"
                )
            if attempt.get("source_response_id") != page.get("source_response_id"):
                raise AlpacaSessionArtifactError(
                    "accepted response attempt ID does not match its raw page"
                )
            if attempt.get("retrieved_at") != page.get("retrieved_at"):
                raise AlpacaSessionArtifactError(
                    "accepted response retrieval time does not match its raw page"
                )
            accepted_raw_paths.append(raw_page_path)
    page_paths = [str(page.get("path")) for page in pages]
    if accepted_raw_paths != page_paths:
        raise AlpacaSessionArtifactError("accepted response attempts do not match raw pages")


def _contained_file(run_dir: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise AlpacaSessionArtifactError(f"{label} path is missing")
    path = (run_dir / value).resolve()
    if not path.is_relative_to(run_dir.resolve()) or not path.is_file():
        raise AlpacaSessionArtifactError(f"{label} path escapes or is missing")
    return path


def _canonical_bars(
    bars: list[Any],
    *,
    expected: tuple[datetime, ...],
) -> dict[str, dict[str, Decimal | int]]:
    indexed: dict[str, dict[str, Decimal | int]] = {}
    for index, bar in enumerate(bars):
        if not isinstance(bar, dict) or not {"t", *_BAR_FIELDS}.issubset(bar):
            raise AlpacaSessionArtifactError(f"bar {index} is missing required fields")
        timestamp = _normalized_timestamp(bar["t"])
        if timestamp in indexed:
            raise AlpacaSessionArtifactError("session data contains duplicate timestamps")
        values = _canonical_values(bar, index=index)
        indexed[timestamp] = values
    received = list(indexed)
    wanted = [_iso_z(value) for value in expected]
    if received != wanted:
        raise AlpacaSessionArtifactError("session timestamps do not match the XNYS grid")
    return indexed


def _canonical_values(
    bar: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, Decimal | int]:
    try:
        values: dict[str, Decimal | int] = {
            field: Decimal(str(bar[field])) for field in _PRICE_FIELDS
        }
        volume = Decimal(str(bar["v"]))
        trades = Decimal(str(bar["n"]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaSessionArtifactError(f"bar {index} has invalid numeric fields") from exc
    prices = [values[field] for field in _PRICE_FIELDS]
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value <= 0
        for value in prices
    ):
        raise AlpacaSessionArtifactError(f"bar {index} has invalid prices")
    open_, high, low, close = (values[field] for field in ("o", "h", "l", "c"))
    if not all(isinstance(value, Decimal) for value in (open_, high, low, close)):
        raise AlpacaSessionArtifactError(f"bar {index} has invalid OHLC values")
    if high < max(open_, close, low) or low > min(open_, close, high):
        raise AlpacaSessionArtifactError(f"bar {index} has inconsistent OHLC")
    if (
        not volume.is_finite()
        or not trades.is_finite()
        or volume != volume.to_integral_value()
        or trades != trades.to_integral_value()
    ):
        raise AlpacaSessionArtifactError(f"bar {index} has non-integral activity")
    if volume < 0 or trades < 0:
        raise AlpacaSessionArtifactError(f"bar {index} has negative activity")
    values["v"] = int(volume)
    values["n"] = int(trades)
    return values


def _normalized_timestamp(value: object) -> str:
    return _iso_z(_parse_timestamp(value))


def _parse_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlpacaSessionArtifactError("timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise AlpacaSessionArtifactError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _json_sha256(payload: Mapping[str, Any]) -> str:
    content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(content).hexdigest()


def _timestamp_set_sha256(values: tuple[datetime, ...]) -> str:
    content = ("\n".join(_iso_z(value) for value in values) + "\n").encode()
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "AlpacaSessionArtifactError",
    "LoadedAlpacaSession",
    "discover_valid_session_manifests",
    "load_alpaca_session",
]
