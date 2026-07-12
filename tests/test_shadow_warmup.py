from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]

from trader.data.quality_gate import build_data_quality_gate_from_loader
from trader.data.shadow_warmup import assemble_shadow_warmup
from trader.models import (
    DataQualityGateRequest,
    HistoricalDatasetSummary,
    HistoricalLoadedBar,
    HistoricalLoadedDataset,
    HistoricalLoaderReport,
    HistoricalLoadResult,
    HistoricalLoadStatus,
    HistoricalSnapshotLoadRequest,
)
from trader.reporting.reports import markdown_summary


def test_prior_complete_session_satisfies_warmup_without_weakening_freshness() -> None:
    prior = _session_bars(date(2026, 7, 2))
    current = _session_bars(date(2026, 7, 6))[:5]
    latest = _loader([_dataset("latest", current)], latest=True)
    all_report = _loader(
        [_dataset("prior", prior), _dataset("latest", current)],
        latest=False,
    )

    report, assembled = assemble_shadow_warmup(
        latest,
        all_report,
        minimum_bars=50,
        stale_after_minutes=15,
        now=datetime(2026, 7, 6, 14, 0, tzinfo=UTC),
    )

    assert report.ok is True
    assert assembled is not None
    assert report.prior_complete_session_dates == ["2026-07-02"]
    assert report.current_live_bar_count == 5
    assert report.assembled_bar_count == 83
    assert report.newest_live_bar_age_minutes == Decimal("10.0000")
    assert report.current_session_starts_at_open is True
    assert report.current_session_contiguous is True
    assert report.completed_bars_only is True
    assert report.structural_boundary_agrees is True
    assert report.boundary_agreement_passed is True
    assert report.freshness_applied_to_current_live_only is True
    assert report.data_fingerprint is not None
    assert assembled.results[0].dataset is not None
    assert len(assembled.results[0].dataset.bars) == 83

    quality = build_data_quality_gate_from_loader(
        DataQualityGateRequest(
            symbols=["SPY"],
            bar_size="5 mins",
            what_to_show="TRADES",
            min_bars=50,
            min_average_volume=Decimal("100"),
            min_average_dollar_volume=Decimal("5000"),
        ),
        assembled,
    )
    assert quality.ok is True
    assert quality.results[0].bars_count == 83


def test_forming_bar_is_excluded_from_current_live_prefix() -> None:
    prior = _session_bars(date(2026, 7, 2))
    current = _session_bars(date(2026, 7, 6))[:7]
    latest = _loader([_dataset("latest", current)], latest=True)
    all_report = _loader(
        [_dataset("prior", prior), _dataset("latest", current)],
        latest=False,
    )

    report, assembled = assemble_shadow_warmup(
        latest,
        all_report,
        now=datetime(2026, 7, 6, 14, 0, tzinfo=UTC),
    )

    assert report.ok is True
    assert assembled is not None
    assert report.current_live_bar_count == 6
    assert report.newest_live_bar_timestamp == datetime(2026, 7, 6, 13, 55, tzinfo=UTC)
    assert all(
        bar.timestamp < datetime(2026, 7, 6, 14, 0, tzinfo=UTC)
        for bar in assembled.results[0].dataset.bars
    )


def test_conflicting_overlap_fails_boundary_agreement() -> None:
    prior = _session_bars(date(2026, 7, 2))
    current = _session_bars(date(2026, 7, 6))[:5]
    conflicting = current[0].model_copy(update={"close": current[0].close + 1})
    latest = _loader([_dataset("latest", current)], latest=True)
    all_report = _loader(
        [
            _dataset("prior", prior),
            _dataset("older-current", [conflicting]),
            _dataset("latest", current),
        ],
        latest=False,
    )

    report, assembled = assemble_shadow_warmup(
        latest,
        all_report,
        now=datetime(2026, 7, 6, 14, 0, tzinfo=UTC),
    )

    assert report.ok is False
    assert assembled is None
    assert report.boundary_agreement_passed is False
    assert any("overlap values disagree" in error for error in report.errors)


def test_missing_opening_bar_fails_current_session_prefix() -> None:
    prior = _session_bars(date(2026, 7, 2))
    current = _session_bars(date(2026, 7, 6))[1:6]
    latest = _loader([_dataset("latest", current)], latest=True)
    all_report = _loader(
        [_dataset("prior", prior), _dataset("latest", current)],
        latest=False,
    )

    report, assembled = assemble_shadow_warmup(
        latest,
        all_report,
        now=datetime(2026, 7, 6, 14, 5, tzinfo=UTC),
    )

    assert report.ok is False
    assert assembled is None
    assert report.current_session_starts_at_open is False
    assert any("does not start" in error for error in report.errors)


def test_stale_current_bar_fails_even_with_complete_prior_history() -> None:
    prior = _session_bars(date(2026, 7, 2))
    current = _session_bars(date(2026, 7, 6))[:5]
    latest = _loader([_dataset("latest", current)], latest=True)
    all_report = _loader(
        [_dataset("prior", prior), _dataset("latest", current)],
        latest=False,
    )

    report, assembled = assemble_shadow_warmup(
        latest,
        all_report,
        stale_after_minutes=15,
        now=datetime(2026, 7, 6, 14, 30, tzinfo=UTC),
    )

    assert report.ok is False
    assert assembled is None
    assert any("age" in error and "exceeds 15" in error for error in report.errors)


def test_warmup_report_serializes_and_module_is_broker_free() -> None:
    latest = _loader(
        [_dataset("latest", _session_bars(date(2026, 7, 6))[:5])],
        latest=True,
    )
    report, _ = assemble_shadow_warmup(
        latest,
        _loader([], latest=False),
        now=datetime(2026, 7, 6, 14, 0, tzinfo=UTC),
    )

    assert "Strict-live Warmup Assembly" in markdown_summary(
        report.model_dump(mode="json")
    )
    source = Path("src/trader/data/shadow_warmup.py").read_text(encoding="utf-8")
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "ibapi",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
    ):
        assert forbidden not in source


def _session_bars(session_date: date) -> list[HistoricalLoadedBar]:
    calendar = xcals.get_calendar("XNYS")
    bars: list[HistoricalLoadedBar] = []
    for index, timestamp in enumerate(calendar.session_minutes(session_date)[::5]):
        price = Decimal("500") + Decimal(index) / Decimal("10")
        bars.append(
            HistoricalLoadedBar(
                symbol="SPY",
                timestamp=timestamp.to_pydatetime(),
                raw_timestamp=timestamp.isoformat(),
                open=price,
                high=price + Decimal("0.10"),
                low=price - Decimal("0.10"),
                close=price + Decimal("0.05"),
                volume=Decimal("1000"),
                typical_price=price,
                dollar_volume=price * Decimal("1000"),
                interval_seconds=300,
                duration="1 D",
                bar_size="5 mins",
                what_to_show="TRADES",
                use_rth=1,
            )
        )
    return bars


def _dataset(name: str, bars: list[HistoricalLoadedBar]) -> HistoricalLoadedDataset:
    summary = HistoricalDatasetSummary(
        symbol="SPY",
        bar_size="5 mins",
        what_to_show="TRADES",
        snapshot_timestamp=name,
        bars_path=f"{name}_bars.jsonl",
        manifest_path=f"{name}_manifest.json",
        bars_count=len(bars),
        first_timestamp=bars[0].timestamp if bars else None,
        last_timestamp=bars[-1].timestamp if bars else None,
        load_status=HistoricalLoadStatus.LOADED,
    )
    return HistoricalLoadedDataset(
        symbol="SPY",
        bar_size="5 mins",
        what_to_show="TRADES",
        snapshot_timestamp=name,
        bars_path=f"{name}_bars.jsonl",
        manifest_path=f"{name}_manifest.json",
        bars=bars,
        summary=summary,
    )


def _loader(
    datasets: list[HistoricalLoadedDataset],
    *,
    latest: bool,
) -> HistoricalLoaderReport:
    request = HistoricalSnapshotLoadRequest(
        symbols=["SPY"],
        bar_size="5 mins",
        what_to_show="TRADES",
        latest=latest,
    )
    results = [
        HistoricalLoadResult(
            symbol="SPY",
            request=request,
            dataset=dataset,
            summary=dataset.summary,
            load_status=HistoricalLoadStatus.LOADED,
        )
        for dataset in datasets
    ]
    return HistoricalLoaderReport(
        command="history-load",
        ok=bool(results),
        request=request,
        base_data_path="data/historical",
        symbols_requested=["SPY"],
        results=results,
        summaries=[dataset.summary for dataset in datasets],
        final_status="loaded" if results else "failed",
    )
