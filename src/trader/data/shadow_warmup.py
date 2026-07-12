"""Strict-live SPY warmup assembly from ignored local IBKR snapshots."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]

from trader.models import (
    HistoricalDatasetSummary,
    HistoricalLoadedBar,
    HistoricalLoadedDataset,
    HistoricalLoaderReport,
    HistoricalLoadResult,
    HistoricalLoadStatus,
    ShadowWarmupAssemblyReport,
    utc_now,
)

_EASTERN = ZoneInfo("America/New_York")


def assemble_shadow_warmup(
    latest_report: HistoricalLoaderReport,
    all_report: HistoricalLoaderReport,
    *,
    minimum_bars: int = 50,
    stale_after_minutes: int = 15,
    prior_session_limit: int = 2,
    now: datetime | None = None,
) -> tuple[ShadowWarmupAssemblyReport, HistoricalLoaderReport | None]:
    """Assemble complete prior sessions and a fresh current-session prefix."""

    current_time = (now or utc_now()).astimezone(UTC)
    warnings = [
        "Warmup assembly is offline; freshness applies only to current live bars"
    ]
    errors: list[str] = []
    latest_dataset = _first_dataset(latest_report)
    all_datasets = [
        result.dataset for result in all_report.results if result.dataset is not None
    ]
    if latest_dataset is None or not latest_dataset.bars:
        errors.append("latest SPY snapshot has no loaded bars")
    if not all_datasets:
        errors.append("no local SPY snapshots are available for warmup assembly")
    if errors or latest_dataset is None:
        return _failed_report(
            errors,
            warnings=warnings,
            source_snapshot_count=len(all_datasets),
            minimum_bars=minimum_bars,
            stale_after_minutes=stale_after_minutes,
        ), None

    interval_seconds = _interval_seconds(latest_dataset.bars)
    if interval_seconds != 300:
        errors.append("strict shadow warmup currently requires exact five-minute bars")
    completed_latest = [
        bar
        for bar in latest_dataset.bars
        if bar.timestamp.astimezone(UTC) + timedelta(seconds=interval_seconds)
        <= current_time
    ]
    if not completed_latest:
        errors.append("latest snapshot contains no completed five-minute bars")
        return _failed_report(
            errors,
            warnings=warnings,
            source_snapshot_count=len(all_datasets),
            minimum_bars=minimum_bars,
            stale_after_minutes=stale_after_minutes,
        ), None

    newest_live = completed_latest[-1]
    current_session_date = newest_live.timestamp.astimezone(_EASTERN).date()
    calendar = xcals.get_calendar("XNYS")
    if not calendar.is_session(current_session_date):
        errors.append(f"latest SPY bar is not on an XNYS session: {current_session_date}")
    current_bars = [
        bar
        for bar in completed_latest
        if bar.timestamp.astimezone(_EASTERN).date() == current_session_date
    ]
    expected_current = _expected_five_minute_timestamps(current_session_date)
    current_timestamps = [bar.timestamp.astimezone(UTC) for bar in current_bars]
    current_starts_at_open = bool(
        current_timestamps and current_timestamps[0] == expected_current[0]
    )
    current_contiguous = current_timestamps == expected_current[: len(current_timestamps)]
    completed_only = all(
        timestamp + timedelta(seconds=interval_seconds) <= current_time
        for timestamp in current_timestamps
    )
    if not current_starts_at_open:
        errors.append("current SPY snapshot does not start at the XNYS session open")
    if not current_contiguous:
        errors.append("current SPY snapshot is not a contiguous five-minute session prefix")
    if not completed_only:
        errors.append("current SPY warmup contains an incomplete forming bar")

    bars_by_timestamp: dict[datetime, HistoricalLoadedBar] = {}
    conflicts: list[str] = []
    all_bars_by_session: dict[date, list[HistoricalLoadedBar]] = defaultdict(list)
    latest_path = latest_dataset.bars_path
    older_values: dict[datetime, HistoricalLoadedBar] = {}
    for dataset in all_datasets:
        for bar in dataset.bars:
            timestamp = bar.timestamp.astimezone(UTC)
            existing = bars_by_timestamp.get(timestamp)
            if existing is not None and not _bar_values_equal(existing, bar):
                conflicts.append(timestamp.isoformat())
                continue
            bars_by_timestamp[timestamp] = bar
            session_date = timestamp.astimezone(_EASTERN).date()
            all_bars_by_session[session_date].append(bar)
            if dataset.bars_path != latest_path:
                older_values[timestamp] = bar
    if conflicts:
        errors.append(
            f"snapshot overlap values disagree at {len(set(conflicts))} timestamp(s)"
        )
    overlap_timestamps = {
        bar.timestamp.astimezone(UTC)
        for bar in current_bars
        if bar.timestamp.astimezone(UTC) in older_values
    }
    overlap_values_agree = all(
        _bar_values_equal(
            next(
                bar
                for bar in current_bars
                if bar.timestamp.astimezone(UTC) == timestamp
            ),
            older_values[timestamp],
        )
        for timestamp in overlap_timestamps
    )

    selected_prior: list[tuple[date, list[HistoricalLoadedBar]]] = []
    prior_date = calendar.previous_session(current_session_date).date()
    examined = 0
    while examined < 10 and len(selected_prior) < prior_session_limit:
        candidates = _deduplicate_bars(all_bars_by_session.get(prior_date, []))
        expected = _expected_five_minute_timestamps(prior_date)
        timestamps = [bar.timestamp.astimezone(UTC) for bar in candidates]
        if timestamps == expected:
            selected_prior.append((prior_date, candidates))
        elif not selected_prior:
            errors.append(f"most recent prior XNYS session is incomplete: {prior_date}")
            break
        prior_date = calendar.previous_session(prior_date).date()
        examined += 1
    if not selected_prior:
        errors.append("no complete prior XNYS session is available for warmup")

    structural_boundary_agrees = bool(
        selected_prior
        and current_timestamps
        and selected_prior[0][0] == calendar.previous_session(current_session_date).date()
        and current_timestamps[0] == expected_current[0]
        and selected_prior[0][1][-1].timestamp.astimezone(UTC)
        == _expected_five_minute_timestamps(selected_prior[0][0])[-1]
    )
    boundary_agreement = bool(
        not conflicts
        and (
            overlap_values_agree if overlap_timestamps else structural_boundary_agrees
        )
    )
    if not boundary_agreement:
        errors.append("prior-session/current-live boundary agreement failed")

    selected_prior.reverse()
    assembled_bars = [
        *[bar for _, bars in selected_prior for bar in bars],
        *current_bars,
    ]
    assembled_bars = _deduplicate_bars(assembled_bars)
    if len(assembled_bars) < minimum_bars:
        errors.append(
            f"assembled SPY bars observed {len(assembled_bars)}; expected at least {minimum_bars}"
        )
    newest_age = Decimal(
        str((current_time - newest_live.timestamp.astimezone(UTC)).total_seconds() / 60)
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if newest_age < 0:
        errors.append("newest current-live SPY bar is in the future")
    elif newest_age > stale_after_minutes:
        errors.append(
            f"newest current-live SPY bar age {newest_age} minutes exceeds "
            f"{stale_after_minutes}"
        )

    data_fingerprint = _bars_fingerprint(assembled_bars) if assembled_bars else None
    report = ShadowWarmupAssemblyReport(
        ok=not errors,
        source_snapshot_count=len(all_datasets),
        prior_complete_session_dates=[item[0].isoformat() for item in selected_prior],
        current_session_date=current_session_date.isoformat(),
        current_live_bar_count=len(current_bars),
        assembled_bar_count=len(assembled_bars),
        minimum_bar_count=minimum_bars,
        newest_live_bar_timestamp=newest_live.timestamp,
        newest_live_bar_age_minutes=newest_age,
        freshness_threshold_minutes=stale_after_minutes,
        overlap_bar_count=len(overlap_timestamps),
        overlap_values_agree=overlap_values_agree,
        structural_boundary_agrees=structural_boundary_agrees,
        boundary_agreement_passed=boundary_agreement,
        current_session_starts_at_open=current_starts_at_open,
        current_session_contiguous=current_contiguous,
        completed_bars_only=completed_only,
        data_fingerprint=data_fingerprint,
        warnings=warnings,
        errors=list(dict.fromkeys(errors)),
        final_status="completed" if not errors else "failed",
    )
    if errors:
        return report, None
    return report, _assembled_loader_report(
        latest_report,
        all_report,
        latest_dataset,
        assembled_bars,
    )


def _assembled_loader_report(
    latest_report: HistoricalLoaderReport,
    all_report: HistoricalLoaderReport,
    latest_dataset: HistoricalLoadedDataset,
    bars: list[HistoricalLoadedBar],
) -> HistoricalLoaderReport:
    volumes = [bar.volume for bar in bars if bar.volume is not None]
    dollar_volumes = [bar.dollar_volume for bar in bars if bar.dollar_volume is not None]
    zero_volume = [
        bar.timestamp.isoformat()
        for bar in bars
        if bar.volume is not None and bar.volume == 0
    ]
    summary = HistoricalDatasetSummary(
        symbol="SPY",
        bar_size=latest_dataset.bar_size,
        what_to_show=latest_dataset.what_to_show,
        snapshot_timestamp=latest_dataset.snapshot_timestamp,
        bars_path="assembled://strict-live-warmup",
        manifest_path="assembled://strict-live-warmup",
        bars_count=len(bars),
        first_timestamp=bars[0].timestamp,
        last_timestamp=bars[-1].timestamp,
        zero_volume_count=len(zero_volume),
        zero_volume_sample_timestamps=zero_volume[:5],
        volume_count=len(volumes),
        total_volume=sum(volumes, Decimal("0")),
        average_volume=(
            sum(volumes, Decimal("0")) / Decimal(len(volumes)) if volumes else None
        ),
        dollar_volume_count=len(dollar_volumes),
        total_dollar_volume=sum(dollar_volumes, Decimal("0")),
        average_dollar_volume=(
            sum(dollar_volumes, Decimal("0")) / Decimal(len(dollar_volumes))
            if dollar_volumes
            else None
        ),
        manifest_bar_count=len(bars),
        manifest_matches_bars=True,
        load_status=HistoricalLoadStatus.LOADED,
        source="shadow_warmup_assembly",
    )
    dataset = HistoricalLoadedDataset(
        symbol="SPY",
        bar_size=latest_dataset.bar_size,
        what_to_show=latest_dataset.what_to_show,
        snapshot_timestamp=latest_dataset.snapshot_timestamp,
        bars_path="assembled://strict-live-warmup",
        manifest_path="assembled://strict-live-warmup",
        bars=bars,
        summary=summary,
        source="shadow_warmup_assembly",
    )
    result = HistoricalLoadResult(
        symbol="SPY",
        request=latest_report.request,
        dataset=dataset,
        summary=summary,
        load_status=HistoricalLoadStatus.LOADED,
    )
    return HistoricalLoaderReport(
        command="shadow-warmup-assemble",
        ok=True,
        request=latest_report.request,
        base_data_path=latest_report.base_data_path,
        symbols_requested=["SPY"],
        snapshots_discovered=all_report.snapshots_discovered,
        results=[result],
        summaries=[summary],
        warnings=[
            "Complete prior XNYS sessions were joined to current completed live bars"
        ],
        final_status="loaded",
    )


def _first_dataset(report: HistoricalLoaderReport) -> HistoricalLoadedDataset | None:
    return next(
        (
            result.dataset
            for result in report.results
            if result.symbol == "SPY" and result.dataset is not None
        ),
        None,
    )


def _interval_seconds(bars: list[HistoricalLoadedBar]) -> int:
    values = {int(bar.interval_seconds or 0) for bar in bars}
    return next(iter(values)) if len(values) == 1 else 0


def _expected_five_minute_timestamps(session_date: date) -> list[datetime]:
    calendar = xcals.get_calendar("XNYS")
    return [
        value.to_pydatetime().astimezone(UTC)
        for value in calendar.session_minutes(session_date)[::5]
    ]


def _deduplicate_bars(bars: list[HistoricalLoadedBar]) -> list[HistoricalLoadedBar]:
    by_timestamp: dict[datetime, HistoricalLoadedBar] = {}
    for bar in sorted(bars, key=lambda item: item.timestamp):
        by_timestamp[bar.timestamp.astimezone(UTC)] = bar
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def _bar_values_equal(left: HistoricalLoadedBar, right: HistoricalLoadedBar) -> bool:
    return (
        left.open,
        left.high,
        left.low,
        left.close,
        left.volume,
        left.wap,
        left.bar_count,
    ) == (
        right.open,
        right.high,
        right.low,
        right.close,
        right.volume,
        right.wap,
        right.bar_count,
    )


def _bars_fingerprint(bars: list[HistoricalLoadedBar]) -> str:
    payload = [
        {
            "close": str(bar.close),
            "high": str(bar.high),
            "low": str(bar.low),
            "open": str(bar.open),
            "timestamp": bar.timestamp.astimezone(UTC).isoformat(),
            "volume": str(bar.volume),
        }
        for bar in bars
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _failed_report(
    errors: list[str],
    *,
    warnings: list[str],
    source_snapshot_count: int,
    minimum_bars: int,
    stale_after_minutes: int,
) -> ShadowWarmupAssemblyReport:
    return ShadowWarmupAssemblyReport(
        ok=False,
        source_snapshot_count=source_snapshot_count,
        minimum_bar_count=minimum_bars,
        freshness_threshold_minutes=stale_after_minutes,
        warnings=warnings,
        errors=list(dict.fromkeys(errors)),
        final_status="failed",
    )


__all__ = ["assemble_shadow_warmup"]
