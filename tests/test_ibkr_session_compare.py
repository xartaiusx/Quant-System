from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trader.data.historical import write_historical_snapshot_result
from trader.data.ibkr_session_compare import compare_ibkr_sessions
from trader.models import (
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    HistoricalSnapshotRequest,
    HistoricalSnapshotResult,
    HistoricalVolumeUnit,
    IBKRSessionCompareRequest,
    IBKRSessionCompareStatus,
)
from trader.reporting.reports import markdown_summary


def test_identical_session_snapshots_compare_cleanly(tmp_path: Path) -> None:
    baseline = stored_snapshot(tmp_path, "baseline", close=Decimal("100.5"))
    candidate = stored_snapshot(tmp_path, "candidate", close=Decimal("100.5"))

    report = compare_ibkr_sessions(compare_request(baseline, candidate))

    assert report.ok is True
    assert report.final_status == IBKRSessionCompareStatus.IDENTICAL
    assert report.matching_bar_count == 1
    assert report.revised_bar_count == 0
    assert report.volume_comparison_authoritative is True
    assert report.broker_contacted is False
    assert report.order_api_invoked is False


def test_session_compare_classifies_price_revision(tmp_path: Path) -> None:
    baseline = stored_snapshot(tmp_path, "baseline", close=Decimal("100.5"))
    candidate = stored_snapshot(tmp_path, "candidate", close=Decimal("100.6"))

    report = compare_ibkr_sessions(compare_request(baseline, candidate))

    assert report.ok is True
    assert report.final_status == IBKRSessionCompareStatus.REVISED
    assert report.revised_bar_count == 1
    assert report.revisions[0].changed_fields == ["close"]
    assert report.baseline_checksum_sha256 != report.candidate_checksum_sha256


def test_session_compare_fails_closed_on_parameter_mismatch(tmp_path: Path) -> None:
    baseline = stored_snapshot(tmp_path, "baseline", close=Decimal("100.5"))
    candidate = stored_snapshot(
        tmp_path,
        "candidate",
        close=Decimal("100.5"),
        bar_size="1 min",
    )

    report = compare_ibkr_sessions(compare_request(baseline, candidate))

    assert report.ok is False
    assert report.final_status == IBKRSessionCompareStatus.INCOMPATIBLE
    assert "bar_size" in " ".join(report.errors)


def test_session_compare_markdown_renders_evidence(tmp_path: Path) -> None:
    baseline = stored_snapshot(tmp_path, "baseline", close=Decimal("100.5"))
    candidate = stored_snapshot(tmp_path, "candidate", close=Decimal("100.6"))

    report = compare_ibkr_sessions(compare_request(baseline, candidate))
    rendered = markdown_summary(report.model_dump(mode="json"))

    assert "# IBKR Session Comparison" in rendered
    assert "Revised bars: `1`" in rendered
    assert "Broker contacted: `False`" in rendered


def stored_snapshot(
    tmp_path: Path,
    slug: str,
    *,
    close: Decimal,
    bar_size: str = "5 mins",
) -> HistoricalSnapshotResult:
    end_datetime = datetime(2026, 7, 13, 20, 0, tzinfo=UTC)
    request = HistoricalSnapshotRequest(
        symbols=["SPY"],
        duration="1 D",
        bar_size=bar_size,
        what_to_show="TRADES",
        use_rth=1,
        timeout_seconds=45,
        end_datetime=end_datetime,
        volume_unit=HistoricalVolumeUnit.SHARES,
    )
    bar = HistoricalSnapshotBar(
        symbol="SPY",
        contract_id=756733,
        timestamp="20260713 09:30:00 US/Eastern",
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=close,
        volume=Decimal("1000"),
        wap=Decimal("100.25"),
        bar_count=10,
        duration="1 D",
        bar_size=bar_size,
        what_to_show="TRADES",
        use_rth=1,
    )
    manifest = HistoricalSnapshotManifest(
        generated_at=datetime(2026, 7, 13, 21, 0, tzinfo=UTC),
        symbol="SPY",
        contract_id=756733,
        duration="1 D",
        bar_size=bar_size,
        what_to_show="TRADES",
        use_rth=1,
        end_datetime=end_datetime,
        volume_unit=HistoricalVolumeUnit.SHARES,
        bar_count=1,
        first_bar_time=bar.timestamp,
        last_bar_time=bar.timestamp,
        request_timeout=45,
    )
    result = HistoricalSnapshotResult(
        symbol="SPY",
        request=request,
        ok=True,
        bars=[bar],
        manifest=manifest,
    )
    return write_historical_snapshot_result(
        result,
        base_dir=tmp_path / slug,
        timestamp_slug=slug,
    )


def compare_request(
    baseline: HistoricalSnapshotResult,
    candidate: HistoricalSnapshotResult,
) -> IBKRSessionCompareRequest:
    assert baseline.manifest_path is not None
    assert candidate.manifest_path is not None
    return IBKRSessionCompareRequest(
        baseline_manifest_path=baseline.manifest_path,
        candidate_manifest_path=candidate.manifest_path,
    )
