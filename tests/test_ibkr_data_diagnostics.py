from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import trader.data.ibkr_data_diagnostics as diagnostics
from trader.models import (
    BrokerDiagnosticReport,
    BrokerErrorEvent,
    HistoricalReadinessReport,
    HistoricalReadinessStatus,
    HistoricalReadinessSummary,
    HistoricalSnapshotManifest,
    HistoricalSnapshotReport,
    HistoricalSnapshotRequest,
    HistoricalSnapshotResult,
    IBKRDataDiagnosticsRequest,
    IBKRDataDiagnosticsStatus,
    ManagedAccountInfo,
    MarketDataDiagnosticReport,
    MarketDataRequestType,
    ShadowDataPolicy,
)
from trader.reporting.reports import markdown_summary

COMMIT_SHA = "411ef65"
NOW = datetime(2026, 7, 6, 18, 33, 22, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostics, "_current_commit_sha", lambda: COMMIT_SHA)


def test_strict_precheck_passes_with_fresh_spy_data(tmp_path: Path) -> None:
    paths = write_source_reports(tmp_path, latest_bar_age_minutes=10, bar_count=58)

    report = diagnostics.build_ibkr_data_diagnostics_report(request(paths), now=NOW)

    assert report.ok is True
    assert report.final_status == IBKRDataDiagnosticsStatus.COMPLETED
    assert report.strict_shadow_precheck_passed is True
    assert report.broker_connected is True
    assert report.broker_account_verified is True
    assert report.bar_count == 58
    assert report.bar_count_passed is True
    assert report.freshness_passed is True
    assert report.next_recommended_action == "run_alpha_shadow_daemon"
    assert report.submitted_orders is False
    assert report.order_api_invoked is False
    assert report.broker_contacted is False


def test_strict_precheck_fails_closed_on_stale_spy_data(tmp_path: Path) -> None:
    paths = write_source_reports(tmp_path, latest_bar_age_minutes=18.37, bar_count=58)

    report = diagnostics.build_ibkr_data_diagnostics_report(request(paths), now=NOW)

    assert report.ok is False
    assert report.final_status == IBKRDataDiagnosticsStatus.FAILED
    assert report.strict_shadow_precheck_passed is False
    assert report.bar_count_passed is True
    assert report.freshness_passed is False
    assert report.latest_bar_age_minutes == pytest.approx(18.37, abs=0.01)
    assert (
        report.next_recommended_action
        == "keep_shadow_daemon_blocked_and_investigate_ibkr_data_lag"
    )
    assert any("latest bar age" in error for error in report.errors)
    assert any("common delayed-market-data range" in hint for hint in report.operator_hints)
    assert report.submitted_orders is False
    assert report.paper_orders_enabled is False


def test_strict_precheck_fails_without_broker_account_evidence(tmp_path: Path) -> None:
    paths = write_source_reports(
        tmp_path,
        latest_bar_age_minutes=10,
        bar_count=58,
        broker_managed_accounts=False,
    )

    report = diagnostics.build_ibkr_data_diagnostics_report(request(paths), now=NOW)

    assert report.ok is False
    assert report.broker_probe_ok is True
    assert report.broker_connected is True
    assert report.broker_account_verified is False
    assert report.strict_shadow_precheck_passed is False
    assert report.next_recommended_action == (
        "rerun_broker_probe_with_fresh_client_id_or_longer_timeout"
    )
    assert "broker-probe lacks managed-account evidence" in report.errors


def test_strict_precheck_fails_when_source_reports_are_missing(tmp_path: Path) -> None:
    report = diagnostics.build_ibkr_data_diagnostics_report(
        IBKRDataDiagnosticsRequest(
            broker_probe_report_path=(tmp_path / "missing-broker.json").as_posix(),
            history_snapshot_report_path=(tmp_path / "missing-snapshot.json").as_posix(),
            history_readiness_report_path=(tmp_path / "missing-readiness.json").as_posix(),
            market_probe_report_path=None,
        ),
        now=NOW,
    )

    assert report.ok is False
    assert report.broker_probe_ok is False
    assert report.history_snapshot_ok is False
    assert report.history_readiness_ok is False
    assert report.bar_count == 0
    assert report.freshness_passed is False
    assert report.strict_shadow_precheck_passed is False
    assert any("not found" in error for error in report.errors)


def test_request_mismatch_fails_closed(tmp_path: Path) -> None:
    paths = write_source_reports(
        tmp_path,
        latest_bar_age_minutes=10,
        bar_count=58,
        duration="2 D",
    )

    report = diagnostics.build_ibkr_data_diagnostics_report(request(paths), now=NOW)

    assert report.ok is False
    assert report.strict_shadow_precheck_passed is False
    assert any("duration" in error for error in report.errors)


def test_live_market_data_permission_blocker_fails_closed(tmp_path: Path) -> None:
    paths = write_source_reports(
        tmp_path,
        latest_bar_age_minutes=10,
        bar_count=58,
        include_market_probe=True,
    )

    report = diagnostics.build_ibkr_data_diagnostics_report(request(paths), now=NOW)

    assert report.ok is False
    assert report.strict_shadow_precheck_passed is False
    assert report.freshness_passed is True
    assert report.market_probe_ok is False
    assert report.market_probe_final_status == "partial"
    assert report.market_data_type_requested == "live"
    assert report.market_data_permission_blocker is True
    assert (
        report.market_data_permission_hint
        == "live_market_data_subscription_missing_for_spy_api"
    )
    assert (
        report.market_data_type_hint
        == "live_market_data_subscription_missing_for_strict_shadow"
    )
    assert any("IBKR 10089" in error for error in report.market_probe_errors)
    assert any("market-probe indicates" in error for error in report.errors)


def test_delayed_engineering_precheck_passes_non_graduating(tmp_path: Path) -> None:
    paths = write_source_reports(
        tmp_path,
        latest_bar_age_minutes=18.37,
        bar_count=58,
        include_delayed_market_probe=True,
    )

    report = diagnostics.build_ibkr_data_diagnostics_report(
        request(
            paths,
            data_policy=ShadowDataPolicy.DELAYED_ENGINEERING,
            stale_after_minutes=30,
        ),
        now=NOW,
    )

    assert report.ok is True
    assert report.final_status == IBKRDataDiagnosticsStatus.COMPLETED_WITH_WARNINGS
    assert report.data_policy == ShadowDataPolicy.DELAYED_ENGINEERING
    assert report.delayed_data_mode is True
    assert report.strict_shadow_precheck_passed is False
    assert report.delayed_shadow_precheck_passed is True
    assert report.freshness_passed is True
    assert report.graduation_eligible is False
    assert (
        report.non_graduating_reason
        == "delayed_data_engineering_mode_cannot_graduate_to_paper_execution"
    )
    assert (
        report.next_recommended_action
        == "run_alpha_shadow_daemon_delayed_non_graduating"
    )
    assert report.market_data_type_requested == "delayed"
    assert "non-graduating" in " ".join(report.warnings)


def test_delayed_engineering_requires_delayed_market_probe(tmp_path: Path) -> None:
    paths = write_source_reports(tmp_path, latest_bar_age_minutes=18.37, bar_count=58)

    report = diagnostics.build_ibkr_data_diagnostics_report(
        request(
            paths,
            data_policy=ShadowDataPolicy.DELAYED_ENGINEERING,
            stale_after_minutes=30,
        ),
        now=NOW,
    )

    assert report.ok is False
    assert report.delayed_shadow_precheck_passed is False
    assert any("delayed market-probe" in error for error in report.errors)


def test_markdown_renders_safety_and_blocker(tmp_path: Path) -> None:
    paths = write_source_reports(
        tmp_path,
        latest_bar_age_minutes=18.37,
        bar_count=58,
        include_market_probe=True,
    )
    report = diagnostics.build_ibkr_data_diagnostics_report(request(paths), now=NOW)

    rendered = markdown_summary(report.model_dump(mode="json"))

    assert "# IBKR Data Freshness Diagnostics" in rendered
    assert "Order API invoked: `False`" in rendered
    assert "Broker contacted by diagnostics: `False`" in rendered
    assert "keep_shadow_daemon_blocked_and_investigate_ibkr_data_lag" in rendered
    assert "Market-data permission blocker: `True`" in rendered
    assert "IBKR 10089" in rendered
    assert "latest bar age" in rendered


def request(paths: dict[str, Path], **overrides: Any) -> IBKRDataDiagnosticsRequest:
    values: dict[str, Any] = {
        "broker_probe_report_path": paths["broker"].as_posix(),
        "history_snapshot_report_path": paths["snapshot"].as_posix(),
        "history_readiness_report_path": paths["readiness"].as_posix(),
        "market_probe_report_path": (
            paths["market"].as_posix() if "market" in paths else None
        ),
    }
    values.update(overrides)
    return IBKRDataDiagnosticsRequest(**values)


def write_source_reports(
    tmp_path: Path,
    *,
    latest_bar_age_minutes: float,
    bar_count: int,
    broker_managed_accounts: bool = True,
    duration: str = "1 D",
    include_market_probe: bool = False,
    include_delayed_market_probe: bool = False,
) -> dict[str, Path]:
    snapshot_path = tmp_path / "spy-snapshot.jsonl"
    bars = snapshot_rows(bar_count=bar_count, latest_bar_age_minutes=latest_bar_age_minutes)
    snapshot_path.write_text("\n".join(json.dumps(row) for row in bars) + "\n")

    broker_path = tmp_path / "broker.json"
    snapshot_report_path = tmp_path / "snapshot.json"
    readiness_path = tmp_path / "readiness.json"
    market_path = tmp_path / "market.json"

    write_report(
        broker_path,
        broker_report(managed_accounts=broker_managed_accounts),
    )
    write_report(
        snapshot_report_path,
        snapshot_report(
            snapshot_path=snapshot_path,
            bars=bars,
            duration=duration,
        ),
    )
    write_report(
        readiness_path,
        readiness_report(
            bars=bars,
            snapshot_path=snapshot_path,
            duration=duration,
        ),
    )
    paths = {
        "broker": broker_path,
        "snapshot": snapshot_report_path,
        "readiness": readiness_path,
    }
    if include_market_probe:
        write_report(market_path, market_probe_report())
        paths["market"] = market_path
    if include_delayed_market_probe:
        write_report(market_path, delayed_market_probe_report())
        paths["market"] = market_path
    return paths


def snapshot_rows(*, bar_count: int, latest_bar_age_minutes: float) -> list[dict[str, str]]:
    latest = NOW - timedelta(minutes=latest_bar_age_minutes)
    start = latest - timedelta(minutes=5 * (bar_count - 1))
    rows: list[dict[str, str]] = []
    for index in range(bar_count):
        timestamp = start + timedelta(minutes=5 * index)
        price = Decimal("550") + Decimal(index) / Decimal("100")
        rows.append(
            {
                "symbol": "SPY",
                "timestamp": timestamp.isoformat(),
                "open": str(price),
                "high": str(price + Decimal("1")),
                "low": str(price - Decimal("1")),
                "close": str(price + Decimal("0.25")),
                "volume": "100000",
                "duration": "1 D",
                "bar_size": "5 mins",
                "what_to_show": "TRADES",
                "use_rth": "1",
            }
        )
    return rows


def broker_report(*, managed_accounts: bool) -> BrokerDiagnosticReport:
    return BrokerDiagnosticReport(
        ok=True,
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=601,
        broker_kind="ib_gateway",
        connected=True,
        ibapi_available=True,
        connection_attempted=True,
        managed_accounts_masked=(
            [ManagedAccountInfo(account_id_masked="DUQ2****23")]
            if managed_accounts
            else []
        ),
        final_status="connected",
        timestamp=NOW,
    )


def snapshot_report(
    *,
    snapshot_path: Path,
    bars: list[dict[str, str]],
    duration: str,
) -> HistoricalSnapshotReport:
    request = HistoricalSnapshotRequest(
        symbols=["SPY"],
        duration=duration,
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,
        timeout_seconds=45,
    )
    manifest = HistoricalSnapshotManifest(
        symbol="SPY",
        contract_id=756733,
        duration=duration,
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,
        bar_count=len(bars),
        first_bar_time=bars[0]["timestamp"] if bars else None,
        last_bar_time=bars[-1]["timestamp"] if bars else None,
        request_timeout=45,
        snapshot_path=snapshot_path.as_posix(),
    )
    result = HistoricalSnapshotResult(
        symbol="SPY",
        request=request,
        ok=True,
        manifest=manifest,
        snapshot_path=snapshot_path.as_posix(),
    )
    return HistoricalSnapshotReport(
        ok=True,
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=602,
        broker_kind="ib_gateway",
        connected=True,
        ibapi_available=True,
        connection_attempted=True,
        request=request,
        symbols_requested=["SPY"],
        results=[result],
        snapshot_paths=[snapshot_path.as_posix()],
        final_status="completed",
        timestamp=NOW,
    )


def readiness_report(
    *,
    bars: list[dict[str, str]],
    snapshot_path: Path,
    duration: str,
) -> HistoricalReadinessReport:
    summary = HistoricalReadinessSummary(
        symbol="SPY",
        resolved_contract_id=756733,
        requested_duration=duration,
        requested_bar_size="5 mins",
        requested_what_to_show="TRADES",
        use_rth=1,
        bars_count=len(bars),
        first_timestamp=bars[0]["timestamp"] if bars else None,
        last_timestamp=bars[-1]["timestamp"] if bars else None,
        sorted_timestamps=True,
        readiness_status=HistoricalReadinessStatus.READY,
        snapshot_path=snapshot_path.as_posix(),
    )
    return HistoricalReadinessReport(
        ok=True,
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=602,
        broker_kind="ib_gateway",
        requests=[
            HistoricalSnapshotRequest(
                symbols=["SPY"],
                duration=duration,
                bar_size="5 mins",
                what_to_show="TRADES",
                use_rth=1,
                timeout_seconds=45,
            )
        ],
        symbols_requested=["SPY"],
        snapshot_paths=[snapshot_path.as_posix()],
        summaries=[summary],
        final_status="ready",
        timestamp=NOW,
    )


def market_probe_report() -> MarketDataDiagnosticReport:
    return MarketDataDiagnosticReport(
        ok=False,
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=603,
        broker_kind="ib_gateway",
        connected=True,
        ibapi_available=True,
        connection_attempted=True,
        symbols_requested=["SPY"],
        market_data_type_requested=MarketDataRequestType.LIVE,
        market_data_type_requested_code=1,
        include_historical=True,
        errors=[
            BrokerErrorEvent(
                code=10089,
                req_id=10002,
                message=(
                    "Requested market data requires additional subscription for API. "
                    "Delayed market data is available.SPY ARCA/TOP/ALL"
                ),
                timestamp=NOW,
            )
        ],
        warnings=["live data unavailable; retry with --data-type delayed"],
        final_status="partial",
        timestamp=NOW,
    )


def delayed_market_probe_report() -> MarketDataDiagnosticReport:
    return MarketDataDiagnosticReport(
        ok=True,
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=604,
        broker_kind="ib_gateway",
        connected=True,
        ibapi_available=True,
        connection_attempted=True,
        symbols_requested=["SPY"],
        market_data_type_requested=MarketDataRequestType.DELAYED,
        market_data_type_requested_code=3,
        include_historical=True,
        final_status="connected",
        timestamp=NOW,
    )


def write_report(path: Path, report: Any) -> None:
    payload = report.model_dump(mode="json")
    payload["commit_sha"] = COMMIT_SHA
    path.write_text(json.dumps(payload))
