"""Offline, credential-free SPY research data vendor bake-off."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]

from trader.data.historical import parse_ibkr_bar_timestamp
from trader.models import (
    HistoricalSnapshotBar,
    ResearchDataBakeoffComparison,
    ResearchDataBakeoffManifest,
    ResearchDataBakeoffReport,
    ResearchDataBakeoffSample,
    ResearchDataBakeoffSampleResult,
    ResearchSampleFormat,
    ResearchSampleKind,
)

_BPS = Decimal("10000")
_PERCENT = Decimal("100")
_EASTERN = ZoneInfo("America/New_York")
_MASSIVE_COLUMNS = {
    "ticker",
    "volume",
    "open",
    "close",
    "high",
    "low",
    "window_start",
    "transactions",
}
_ALPACA_FIELDS = {"t", "o", "h", "l", "c", "v", "n", "vw"}
_CANONICAL_BAR_COLUMNS = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
_CANONICAL_ACTION_COLUMNS = {
    "symbol",
    "ex_date",
    "event_type",
    "factor",
    "cash_amount",
    "currency",
    "revision",
}


@dataclass(frozen=True)
class _BarRecord:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class _ActionRecord:
    ex_date: date
    event_type: str
    factor: Decimal | None
    cash_amount: Decimal | None


@dataclass(frozen=True)
class _ParsedSample:
    sample: ResearchDataBakeoffSample
    result: ResearchDataBakeoffSampleResult
    bars: list[_BarRecord]
    actions: list[_ActionRecord]


def load_research_data_bakeoff_manifest(path: Path) -> ResearchDataBakeoffManifest:
    """Load a strict JSON manifest without reading environment credentials."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research data bake-off manifest must contain a JSON object")
    return ResearchDataBakeoffManifest.model_validate(payload)


def run_research_data_bakeoff(manifest_path: Path) -> ResearchDataBakeoffReport:
    """Validate local vendor samples and licensing attestations offline."""

    resolved_manifest = manifest_path.expanduser().resolve()
    try:
        manifest = load_research_data_bakeoff_manifest(resolved_manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return ResearchDataBakeoffReport(
            ok=False,
            manifest_path=resolved_manifest.as_posix(),
            errors=[f"bake-off manifest could not be loaded: {exc}"],
            final_status="failed",
        )

    parsed = [
        _parse_sample(sample, base_path=resolved_manifest.parent)
        for sample in manifest.samples
    ]
    sample_results = [item.result for item in parsed]
    observed_tags = sorted({tag for sample in manifest.samples for tag in sample.case_tags})
    missing_tags = sorted(set(manifest.required_case_tags) - set(observed_tags))
    comparisons = [
        *_intraday_overlap_comparisons(parsed, manifest),
        *_daily_overlap_comparisons(parsed, manifest),
        *_correction_comparisons(parsed),
    ]
    rights_verified = sorted(item.vendor for item in manifest.rights if item.passed)
    rights_failed = sorted(item.vendor for item in manifest.rights if not item.passed)
    errors: list[str] = []
    if missing_tags:
        errors.append(f"missing required bake-off cases: {', '.join(missing_tags)}")
    if rights_failed:
        errors.append(f"vendor rights evidence failed: {', '.join(rights_failed)}")
    errors.extend(error for result in sample_results for error in result.errors)
    errors.extend(error for comparison in comparisons for error in comparison.errors)
    warnings = [warning for result in sample_results for warning in result.warnings]
    warnings.extend(warning for comparison in comparisons for warning in comparison.warnings)
    ok = not errors and all(result.ok for result in sample_results) and all(
        comparison.ok for comparison in comparisons
    )
    procurement_ready = []
    if ok:
        procurement_ready = sorted(
            vendor
            for vendor in rights_verified
            if (
                vendor_results := [
                    result
                    for result in sample_results
                    if result.vendor.strip().lower() == vendor.strip().lower()
                ]
            )
            and all(result.ok for result in vendor_results)
        )
    return ResearchDataBakeoffReport(
        ok=ok,
        manifest_path=resolved_manifest.as_posix(),
        manifest=manifest,
        sample_results=sample_results,
        comparisons=comparisons,
        observed_case_tags=observed_tags,
        missing_case_tags=missing_tags,
        rights_verified_vendors=rights_verified,
        rights_failed_vendors=rights_failed,
        procurement_ready_vendors=procurement_ready,
        warnings=_unique(warnings),
        errors=_unique(errors),
        final_status="completed" if ok else "failed",
    )


def _parse_sample(sample: ResearchDataBakeoffSample, *, base_path: Path) -> _ParsedSample:
    path = Path(sample.path).expanduser()
    if not path.is_absolute():
        path = base_path / path
    path = path.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    bars: list[_BarRecord] = []
    actions: list[_ActionRecord] = []
    digest: str | None = None
    if not path.is_file():
        errors.append(f"{sample.sample_id}: sample file not found")
    else:
        try:
            digest = _sha256(path)
            if sample.expected_sha256 and sample.expected_sha256.lower() != digest:
                errors.append(f"{sample.sample_id}: SHA-256 does not match manifest")
            bars, actions = _read_sample(path, sample)
            errors.extend(_sample_errors(sample, bars, actions))
            if sample.expected_rows is not None:
                observed_rows = (
                    len(actions)
                    if _kind(sample.kind) == "corporate_actions"
                    else len(bars)
                )
                if observed_rows != sample.expected_rows:
                    errors.append(
                        f"{sample.sample_id}: rows observed {observed_rows}; "
                        f"expected {sample.expected_rows}"
                    )
        except (OSError, ValueError, csv.Error) as exc:
            errors.append(f"{sample.sample_id}: sample could not be parsed: {exc}")

    timestamps = [bar.timestamp for bar in bars]
    duplicate_count = len(timestamps) - len(set(timestamps))
    if duplicate_count:
        errors.append(f"{sample.sample_id}: duplicate timestamps detected: {duplicate_count}")
    if timestamps != sorted(timestamps):
        errors.append(f"{sample.sample_id}: timestamps are not chronological")
    row_count = len(actions) if _kind(sample.kind) == "corporate_actions" else len(bars)
    result = ResearchDataBakeoffSampleResult(
        sample_id=sample.sample_id,
        vendor=sample.vendor,
        path=path.as_posix(),
        kind=sample.kind,
        source_format=sample.source_format,
        case_tags=sample.case_tags,
        ok=not errors,
        sha256=digest,
        row_count=row_count,
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        duplicate_count=duplicate_count,
        warnings=warnings,
        errors=_unique(errors),
    )
    return _ParsedSample(sample=sample, result=result, bars=bars, actions=actions)


def _read_sample(
    path: Path,
    sample: ResearchDataBakeoffSample,
) -> tuple[list[_BarRecord], list[_ActionRecord]]:
    source_format = _format(sample.source_format)
    if source_format == "alpaca_sip_json":
        return _read_alpaca_sip_rows(path), []
    if source_format == "ibkr_snapshot_jsonl":
        return _read_ibkr_snapshot_rows(path), []
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if source_format == "massive_minute":
            _require_columns(fields, _MASSIVE_COLUMNS)
            return _read_massive_rows(reader), []
        if source_format == "canonical_ohlcv":
            _require_columns(fields, _CANONICAL_BAR_COLUMNS)
            return _read_canonical_bars(reader), []
        if source_format == "canonical_actions":
            _require_columns(fields, _CANONICAL_ACTION_COLUMNS)
            return [], _read_canonical_actions(reader)
    raise ValueError(f"unsupported sample format: {sample.source_format}")


def _read_massive_rows(reader: csv.DictReader[str]) -> list[_BarRecord]:
    records: list[_BarRecord] = []
    for row in reader:
        if str(row.get("ticker", "")).strip().upper() != "SPY":
            continue
        raw_timestamp = int(str(row["window_start"]).strip())
        timestamp = datetime.fromtimestamp(raw_timestamp / 1_000_000_000, tz=UTC)
        records.append(_bar_from_row(row, timestamp=timestamp))
    return records


def _read_alpaca_sip_rows(path: Path) -> list[_BarRecord]:
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, mode="rt", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Alpaca SIP sample must contain a JSON object")
    if payload.get("source") != "alpaca_sip":
        raise ValueError("Alpaca SIP sample must declare source=alpaca_sip")
    if str(payload.get("symbol", "")).upper() != "SPY":
        raise ValueError("Alpaca SIP sample must contain SPY only")
    if payload.get("feed") != "sip" or payload.get("timeframe") != "1Min":
        raise ValueError("Alpaca sample must contain SIP one-minute bars")
    if payload.get("adjustment") != "raw" or payload.get("sort") != "asc":
        raise ValueError("Alpaca sample must be raw and ascending")
    bars = payload.get("bars")
    if not isinstance(bars, list):
        raise ValueError("Alpaca SIP sample must contain a bars array")
    records: list[_BarRecord] = []
    for index, row in enumerate(bars):
        if not isinstance(row, dict) or not _ALPACA_FIELDS.issubset(row):
            raise ValueError(f"Alpaca SIP bar {index} is missing required fields")
        timestamp = _parse_timestamp(str(row["t"]))
        _nonnegative_integer(row["n"], "trade count")
        vwap = _decimal(row["vw"])
        if not vwap.is_finite() or vwap <= 0:
            raise ValueError(f"invalid VWAP at {timestamp.isoformat()}")
        records.append(
            _bar_from_row(
                {
                    "open": str(row["o"]),
                    "high": str(row["h"]),
                    "low": str(row["l"]),
                    "close": str(row["c"]),
                    "volume": str(row["v"]),
                },
                timestamp=timestamp,
            )
        )
    return records


def _read_ibkr_snapshot_rows(path: Path) -> list[_BarRecord]:
    records: list[_BarRecord] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            bar = HistoricalSnapshotBar.model_validate_json(raw_line)
        except ValueError as exc:
            raise ValueError(f"invalid IBKR snapshot row {line_number}: {exc}") from exc
        if bar.symbol.upper() != "SPY":
            continue
        if (
            bar.source != "ibkr"
            or bar.bar_size != "5 mins"
            or bar.what_to_show != "TRADES"
            or bar.use_rth != 1
        ):
            raise ValueError("IBKR bake-off sample must be 5-minute RTH TRADES data")
        timestamp = parse_ibkr_bar_timestamp(bar.timestamp)
        if timestamp is None:
            raise ValueError(f"invalid IBKR timestamp at row {line_number}")
        if bar.volume is None:
            raise ValueError(f"missing IBKR volume at row {line_number}")
        records.append(
            _bar_from_row(
                {
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": str(bar.volume),
                },
                timestamp=timestamp,
            )
        )
    return records


def _read_canonical_bars(reader: csv.DictReader[str]) -> list[_BarRecord]:
    records: list[_BarRecord] = []
    for row in reader:
        if str(row.get("symbol", "")).strip().upper() != "SPY":
            continue
        timestamp = _parse_timestamp(str(row["timestamp"]))
        records.append(_bar_from_row(row, timestamp=timestamp))
    return records


def _read_canonical_actions(reader: csv.DictReader[str]) -> list[_ActionRecord]:
    records: list[_ActionRecord] = []
    for row in reader:
        if str(row.get("symbol", "")).strip().upper() != "SPY":
            continue
        records.append(
            _ActionRecord(
                ex_date=date.fromisoformat(str(row["ex_date"]).strip()),
                event_type=str(row["event_type"]).strip().lower(),
                factor=_optional_decimal(row.get("factor")),
                cash_amount=_optional_decimal(row.get("cash_amount")),
            )
        )
    return records


def _bar_from_row(row: dict[str, str], *, timestamp: datetime) -> _BarRecord:
    record = _BarRecord(
        timestamp=timestamp,
        open=_decimal(row["open"]),
        high=_decimal(row["high"]),
        low=_decimal(row["low"]),
        close=_decimal(row["close"]),
        volume=_decimal(row["volume"]),
    )
    ohlc = (record.open, record.high, record.low, record.close)
    if any(value <= 0 or not value.is_finite() for value in ohlc):
        raise ValueError(f"nonpositive or non-finite OHLC at {timestamp.isoformat()}")
    if record.high < max(record.open, record.close) or record.low > min(record.open, record.close):
        raise ValueError(f"inconsistent OHLC at {timestamp.isoformat()}")
    if (
        record.volume < 0
        or not record.volume.is_finite()
        or record.volume != record.volume.to_integral_value()
    ):
        raise ValueError(f"invalid volume at {timestamp.isoformat()}")
    return record


def _sample_errors(
    sample: ResearchDataBakeoffSample,
    bars: list[_BarRecord],
    actions: list[_ActionRecord],
) -> list[str]:
    errors: list[str] = []
    kind = _kind(sample.kind)
    if kind == "corporate_actions":
        if not actions:
            errors.append(f"{sample.sample_id}: no SPY corporate actions found")
        keys = [(action.ex_date, action.event_type) for action in actions]
        if len(keys) != len(set(keys)):
            errors.append(f"{sample.sample_id}: duplicate corporate actions found")
        for action in actions:
            if action.event_type not in {"split", "dividend"}:
                errors.append(
                    f"{sample.sample_id}: unsupported corporate action {action.event_type}"
                )
            elif action.event_type == "split" and (
                action.factor is None
                or action.factor <= 0
                or action.factor == Decimal("1")
            ):
                errors.append(f"{sample.sample_id}: invalid split factor")
            elif action.event_type == "dividend" and (
                action.cash_amount is None or action.cash_amount <= 0
            ):
                errors.append(f"{sample.sample_id}: invalid dividend amount")
        if "ex_dividend" in sample.case_tags and not any(
            action.event_type == "dividend" and (action.cash_amount or Decimal("0")) > 0
            for action in actions
        ):
            errors.append(f"{sample.sample_id}: ex-dividend case lacks a cash dividend")
        if "synthetic_split" in sample.case_tags and not any(
            action.event_type == "split"
            and action.factor is not None
            and action.factor > 0
            and action.factor != 1
            for action in actions
        ):
            errors.append(f"{sample.sample_id}: synthetic split case lacks a valid split")
        return errors

    if not bars:
        errors.append(f"{sample.sample_id}: no SPY bars found")
        return errors
    if kind in {"minute_bars", "five_minute_bars"} and set(sample.case_tags) & {
        "normal_session",
        "early_close",
    }:
        errors.extend(_intraday_session_errors(sample, bars, kind=kind))
    if kind == "daily_bars":
        calendar = xcals.get_calendar("XNYS")
        invalid_dates = sorted(
            {
                bar.timestamp.date()
                for bar in bars
                if not calendar.is_session(bar.timestamp.date())
            }
        )
        if invalid_dates:
            errors.append(
                f"{sample.sample_id}: daily bars contain non-XNYS sessions"
            )
    return errors


def _intraday_session_errors(
    sample: ResearchDataBakeoffSample,
    bars: list[_BarRecord],
    *,
    kind: str,
) -> list[str]:
    errors: list[str] = []
    session_dates = {bar.timestamp.astimezone(_EASTERN).date() for bar in bars}
    if len(session_dates) != 1:
        return [f"{sample.sample_id}: minute sample must contain exactly one XNYS session"]
    session_date = next(iter(session_dates))
    calendar = xcals.get_calendar("XNYS")
    if not calendar.is_session(session_date):
        return [f"{sample.sample_id}: minute sample date is not an XNYS session"]
    expected = [
        value.to_pydatetime().astimezone(UTC)
        for value in calendar.session_minutes(session_date)
    ]
    if kind == "five_minute_bars":
        expected = expected[::5]
    observed = [bar.timestamp.astimezone(UTC) for bar in bars]
    if observed != expected:
        errors.append(f"{sample.sample_id}: intraday timestamps do not match XNYS grid")
    normal_count = 78 if kind == "five_minute_bars" else 390
    early_count = 42 if kind == "five_minute_bars" else 210
    if "normal_session" in sample.case_tags and len(expected) != normal_count:
        errors.append(
            f"{sample.sample_id}: tagged normal session is not a {normal_count}-bar day"
        )
    if "early_close" in sample.case_tags and len(expected) != early_count:
        errors.append(
            f"{sample.sample_id}: tagged early close is not a {early_count}-bar day"
        )
    return errors


def _intraday_overlap_comparisons(
    parsed: list[_ParsedSample],
    manifest: ResearchDataBakeoffManifest,
) -> list[ResearchDataBakeoffComparison]:
    candidates = [
        item
        for item in parsed
        if "intraday_overlap" in item.sample.case_tags
        and item.bars
        and _kind(item.sample.kind) in {"minute_bars", "five_minute_bars"}
    ]
    comparisons: list[ResearchDataBakeoffComparison] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            if left.sample.vendor.strip().lower() == right.sample.vendor.strip().lower():
                continue
            comparisons.append(_compare_intraday_bars(left, right, manifest))
    if "intraday_overlap" in manifest.required_case_tags and not comparisons:
        comparisons.append(
            ResearchDataBakeoffComparison(
                comparison_type="intraday_overlap",
                left_sample_id="missing",
                right_sample_id="missing",
                ok=False,
                errors=["intraday overlap requires samples from two different vendors"],
            )
        )
    return comparisons


def _compare_intraday_bars(
    left: _ParsedSample,
    right: _ParsedSample,
    manifest: ResearchDataBakeoffManifest,
) -> ResearchDataBakeoffComparison:
    try:
        left_bars = _as_five_minute_bars(left)
        right_bars = _as_five_minute_bars(right)
    except ValueError as exc:
        return ResearchDataBakeoffComparison(
            comparison_type="intraday_overlap",
            left_sample_id=left.sample.sample_id,
            right_sample_id=right.sample.sample_id,
            ok=False,
            errors=[str(exc)],
        )
    left_by_time = {bar.timestamp: bar for bar in left_bars}
    right_by_time = {bar.timestamp: bar for bar in right_bars}
    overlap = sorted(set(left_by_time) & set(right_by_time))
    price_mismatches = 0
    volume_mismatches = 0
    for timestamp in overlap:
        left_bar = left_by_time[timestamp]
        right_bar = right_by_time[timestamp]
        if any(
            _difference_bps(left_value, right_value) > manifest.max_price_difference_bps
            for left_value, right_value in (
                (left_bar.open, right_bar.open),
                (left_bar.high, right_bar.high),
                (left_bar.low, right_bar.low),
                (left_bar.close, right_bar.close),
            )
        ):
            price_mismatches += 1
        if _difference_pct(left_bar.volume, right_bar.volume) > manifest.max_volume_difference_pct:
            volume_mismatches += 1
    errors: list[str] = []
    expected_overlap = min(len(left_bars), len(right_bars))
    if not overlap:
        errors.append("intraday vendor samples have no overlapping SPY timestamps")
    elif len(overlap) != expected_overlap:
        errors.append(
            f"intraday overlap is incomplete: {len(overlap)} of {expected_overlap} bars"
        )
    if price_mismatches:
        errors.append(f"intraday overlap price mismatches: {price_mismatches}")
    if volume_mismatches:
        errors.append(f"intraday overlap volume mismatches: {volume_mismatches}")
    return ResearchDataBakeoffComparison(
        comparison_type="intraday_overlap",
        left_sample_id=left.sample.sample_id,
        right_sample_id=right.sample.sample_id,
        overlap_count=len(overlap),
        price_mismatch_count=price_mismatches,
        volume_mismatch_count=volume_mismatches,
        ok=not errors,
        errors=errors,
    )


def _as_five_minute_bars(sample: _ParsedSample) -> list[_BarRecord]:
    if _kind(sample.sample.kind) == "five_minute_bars":
        return sample.bars
    by_session: dict[date, list[_BarRecord]] = {}
    for bar in sample.bars:
        by_session.setdefault(bar.timestamp.astimezone(_EASTERN).date(), []).append(bar)
    result: list[_BarRecord] = []
    for session_bars in by_session.values():
        grouped = [
            session_bars[index : index + 5]
            for index in range(0, len(session_bars), 5)
        ]
        if any(len(group) != 5 for group in grouped):
            raise ValueError(
                f"{sample.sample.sample_id}: incomplete five-minute aggregation group"
            )
        result.extend(
            _BarRecord(
                timestamp=group[0].timestamp,
                open=group[0].open,
                high=max(bar.high for bar in group),
                low=min(bar.low for bar in group),
                close=group[-1].close,
                volume=sum((bar.volume for bar in group), Decimal("0")),
            )
            for group in grouped
        )
    return result


def _daily_overlap_comparisons(
    parsed: list[_ParsedSample],
    manifest: ResearchDataBakeoffManifest,
) -> list[ResearchDataBakeoffComparison]:
    candidates = [
        item
        for item in parsed
        if "daily_overlap" in item.sample.case_tags and item.bars
    ]
    comparisons: list[ResearchDataBakeoffComparison] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            if left.sample.vendor.strip().lower() == right.sample.vendor.strip().lower():
                continue
            comparisons.append(_compare_daily_bars(left, right, manifest))
    if "daily_overlap" in manifest.required_case_tags and not comparisons:
        comparisons.append(
            ResearchDataBakeoffComparison(
                comparison_type="daily_overlap",
                left_sample_id="missing",
                right_sample_id="missing",
                ok=False,
                errors=["daily overlap requires bar samples from two different vendors"],
            )
        )
    return comparisons


def _compare_daily_bars(
    left: _ParsedSample,
    right: _ParsedSample,
    manifest: ResearchDataBakeoffManifest,
) -> ResearchDataBakeoffComparison:
    left_by_date = {bar.timestamp.date(): bar for bar in left.bars}
    right_by_date = {bar.timestamp.date(): bar for bar in right.bars}
    overlap = sorted(set(left_by_date) & set(right_by_date))
    price_mismatches = 0
    volume_mismatches = 0
    for session_date in overlap:
        left_bar = left_by_date[session_date]
        right_bar = right_by_date[session_date]
        if any(
            _difference_bps(left_value, right_value) > manifest.max_price_difference_bps
            for left_value, right_value in (
                (left_bar.open, right_bar.open),
                (left_bar.high, right_bar.high),
                (left_bar.low, right_bar.low),
                (left_bar.close, right_bar.close),
            )
        ):
            price_mismatches += 1
        if _difference_pct(left_bar.volume, right_bar.volume) > manifest.max_volume_difference_pct:
            volume_mismatches += 1
    errors: list[str] = []
    if not overlap:
        errors.append("daily vendor samples have no overlapping SPY dates")
    if price_mismatches:
        errors.append(f"daily overlap price mismatches: {price_mismatches}")
    if volume_mismatches:
        errors.append(f"daily overlap volume mismatches: {volume_mismatches}")
    return ResearchDataBakeoffComparison(
        comparison_type="daily_overlap",
        left_sample_id=left.sample.sample_id,
        right_sample_id=right.sample.sample_id,
        overlap_count=len(overlap),
        price_mismatch_count=price_mismatches,
        volume_mismatch_count=volume_mismatches,
        ok=not errors,
        errors=errors,
    )


def _correction_comparisons(parsed: list[_ParsedSample]) -> list[ResearchDataBakeoffComparison]:
    before = [item for item in parsed if "correction_before" in item.sample.case_tags]
    after = [item for item in parsed if "correction_after" in item.sample.case_tags]
    comparisons: list[ResearchDataBakeoffComparison] = []
    for left in before:
        matching = [
            right
            for right in after
            if right.sample.vendor.strip().lower() == left.sample.vendor.strip().lower()
            and right.bars
            and left.bars
        ]
        if matching:
            comparisons.append(_compare_correction(left, matching[0]))
    if before and not comparisons:
        comparisons.append(
            ResearchDataBakeoffComparison(
                comparison_type="correction_revision",
                left_sample_id=before[0].sample.sample_id,
                right_sample_id="missing",
                ok=False,
                errors=["correction cases require before/after bar samples from one vendor"],
            )
        )
    return comparisons


def _compare_correction(
    before: _ParsedSample,
    after: _ParsedSample,
) -> ResearchDataBakeoffComparison:
    before_by_time = {bar.timestamp: bar for bar in before.bars}
    after_by_time = {bar.timestamp: bar for bar in after.bars}
    overlap = sorted(set(before_by_time) & set(after_by_time))
    changes = sum(
        1
        for timestamp in overlap
        if before_by_time[timestamp] != after_by_time[timestamp]
    )
    errors: list[str] = []
    if not overlap:
        errors.append("correction samples have no overlapping timestamps")
    if changes == 0:
        errors.append("correction after-sample does not change any overlapping record")
    if before.result.sha256 == after.result.sha256:
        errors.append("correction before/after samples have identical checksums")
    return ResearchDataBakeoffComparison(
        comparison_type="correction_revision",
        left_sample_id=before.sample.sample_id,
        right_sample_id=after.sample.sample_id,
        overlap_count=len(overlap),
        price_mismatch_count=changes,
        ok=not errors,
        errors=errors,
    )


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if len(normalized) == 10:
        return datetime.combine(date.fromisoformat(normalized), datetime.min.time(), tzinfo=UTC)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    return _decimal(value)


def _nonnegative_integer(value: object, field_name: str) -> int:
    parsed = _decimal(value)
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        raise ValueError(f"{field_name} must be a nonnegative integer")
    return int(parsed)


def _difference_bps(left: Decimal, right: Decimal) -> Decimal:
    denominator = max(left.copy_abs(), right.copy_abs())
    if denominator == 0:
        return Decimal("0")
    return (left - right).copy_abs() / denominator * _BPS


def _difference_pct(left: Decimal, right: Decimal) -> Decimal:
    denominator = max(left.copy_abs(), right.copy_abs())
    if denominator == 0:
        return Decimal("0")
    return (left - right).copy_abs() / denominator * _PERCENT


def _require_columns(observed: set[str], required: set[str]) -> None:
    missing = sorted(required - observed)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _open_csv(path: Path) -> Iterator[IO[str]]:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            yield handle
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield handle


def _kind(value: ResearchSampleKind | str) -> str:
    return str(getattr(value, "value", value))


def _format(value: ResearchSampleFormat | str) -> str:
    return str(getattr(value, "value", value))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = ["load_research_data_bakeoff_manifest", "run_research_data_bakeoff"]
