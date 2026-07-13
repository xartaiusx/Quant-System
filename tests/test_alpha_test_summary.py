from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trader.alpha_summary import run_alpha_test_summary
from trader.models import (
    AlphaPaperRunReport,
    AlphaPaperRunRequest,
    AlphaPaperRunStatus,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaShadowRunStatus,
    AlphaTestSummaryRequest,
    AlphaTestSummaryStatus,
    BrokerOpenOrderSnapshot,
    PaperOrderSmokeReport,
    PaperOrderSmokeRequest,
    PaperOrderSmokeRunStatus,
    PaperReconcileReport,
    PaperReconcileRequest,
    PaperReconcileStatus,
    Signal,
    SignalDirection,
)
from trader.reporting.reports import markdown_summary

CAMPAIGN_ID = "campaign-001"


def now() -> datetime:
    return datetime(2026, 7, 4, 17, tzinfo=UTC)


def summary_request(tmp_path: Path) -> AlphaTestSummaryRequest:
    return AlphaTestSummaryRequest(
        campaign_id=CAMPAIGN_ID,
        alpha_shadow_report_path=(tmp_path / "shadow.json").as_posix(),
        paper_smoke_report_path=(tmp_path / "smoke.json").as_posix(),
        alpha_paper_report_path=(tmp_path / "alpha.json").as_posix(),
        paper_reconcile_report_path=(tmp_path / "reconcile.json").as_posix(),
        max_report_age_hours=24,
    )


def shadow_report(
    *,
    commit_sha: str = "abc123",
    campaign_id: str | None = CAMPAIGN_ID,
) -> AlphaShadowRunReport:
    return AlphaShadowRunReport(
        ok=True,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=AlphaShadowRunRequest(),
        selected_universe=["SPY"],
        broker_connected=True,
        account_summary_verified=True,
        account_ids_masked=["DUQ2****23"],
        history_snapshot_written=True,
        history_load_completed=True,
        data_quality_completed=True,
        signal_evaluation_completed=True,
        shadow_signals=[
            Signal(
                symbol="SPY",
                direction=SignalDirection.BUY,
                strategy="alpha_shadow_moving_average",
                reason="test",
            )
        ],
        shadow_signal_count=1,
        final_status=AlphaShadowRunStatus.COMPLETED,
        timestamp=now(),
    )


def smoke_report(
    *,
    commit_sha: str = "abc123",
    campaign_id: str | None = CAMPAIGN_ID,
    ok: bool = True,
) -> PaperOrderSmokeReport:
    return PaperOrderSmokeReport(
        ok=ok,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=PaperOrderSmokeRequest(
            confirm="PAPER_SMOKE_SPY_1",
            transmit=True,
            cancel_after_seconds=0,
        ),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=21,
        broker_kind="ib_gateway",
        broker_connected=True,
        account_summary_verified=True,
        account_ids_masked=["DUQ2****23"],
        submitted_orders=True,
        paper_orders_enabled=True,
        configured_allow_paper_orders=True,
        order_api_invoked=True,
        place_order_invoked=True,
        cancel_order_invoked=True,
        transmitted=True,
        order_id=31,
        perm_id=3100,
        order_status="Cancelled",
        fill_quantity=Decimal("0"),
        cancel_requested=True,
        canceled=True,
        final_status=PaperOrderSmokeRunStatus.COMPLETED
        if ok
        else PaperOrderSmokeRunStatus.FAILED,
        timestamp=now(),
    )


def alpha_report(
    *,
    commit_sha: str = "abc123",
    campaign_id: str | None = CAMPAIGN_ID,
) -> AlphaPaperRunReport:
    return AlphaPaperRunReport(
        ok=True,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=AlphaPaperRunRequest(
            confirm="ALPHA_PAPER_SPY_1",
            cancel_after_seconds=0,
        ),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=21,
        broker_kind="ib_gateway",
        account_ids_masked=["DUQ2****23"],
        alpha_shadow_report_verified=True,
        paper_smoke_report_verified=True,
        research_experiment_report_verified=True,
        strict_shadow_summary_report_verified=True,
        research_review_ready=True,
        strict_shadow_graduation_ready=True,
        strict_shadow_engineering_pilot_ready=True,
        submitted_orders=True,
        paper_orders_enabled=True,
        configured_allow_paper_orders=True,
        order_api_invoked=True,
        place_order_invoked=True,
        cancel_order_invoked=True,
        order_id=32,
        perm_id=3200,
        order_status="Cancelled",
        fill_quantity=Decimal("0"),
        cancel_requested=True,
        canceled=True,
        final_status=AlphaPaperRunStatus.COMPLETED,
        timestamp=now(),
    )


def reconcile_report(
    *,
    commit_sha: str = "abc123",
    campaign_id: str | None = CAMPAIGN_ID,
    open_order_count: int = 0,
    timestamp: datetime | None = None,
) -> PaperReconcileReport:
    open_orders = (
        [
            BrokerOpenOrderSnapshot(
                order_id=33,
                symbol="SPY",
                action="BUY",
                status="Submitted",
                perm_id=3300,
            )
        ]
        if open_order_count
        else []
    )
    return PaperReconcileReport(
        ok=True,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=PaperReconcileRequest(),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=11,
        broker_kind="ib_gateway",
        broker_connected=True,
        account_summary_verified=True,
        account_summary_source="broker_read_only_account_summary",
        account_ids_masked=["DUQ2****23"],
        account_snapshot={
            "DUQ2****23": {
                "NetLiquidation": {"value": "1000000", "currency": "USD"}
            }
        },
        positions_snapshot=[{"account": "DUQ2****23", "symbol": "SPY", "position": "0"}],
        positions_source="broker_read_only_positions",
        broker_positions_available=True,
        positions_query_completed=True,
        open_orders=open_orders,
        open_order_count=len(open_orders),
        open_orders_query_completed=True,
        zero_open_orders_confirmed=not open_orders,
        executions_available=True,
        executions_query_completed=True,
        zero_executions_confirmed=True,
        source_report_compatibility={
            "paper_smoke_report": "current",
            "alpha_paper_report": "current",
        },
        latest_order_ids=[31, 32],
        latest_perm_ids=[3100, 3200],
        final_status=PaperReconcileStatus.COMPLETED
        if not open_orders
        else PaperReconcileStatus.COMPLETED_WITH_WARNINGS,
        timestamp=timestamp or now(),
    )


def write_report(path: Path, report: object) -> None:
    path.write_text(json.dumps(report.model_dump(mode="json")))


def write_all_reports(
    tmp_path: Path,
    *,
    shadow: AlphaShadowRunReport | None = None,
    smoke: PaperOrderSmokeReport | None = None,
    alpha: AlphaPaperRunReport | None = None,
    reconcile: PaperReconcileReport | None = None,
) -> AlphaTestSummaryRequest:
    selected_request = summary_request(tmp_path)
    if shadow is not None:
        write_report(Path(selected_request.alpha_shadow_report_path), shadow)
    if smoke is not None:
        write_report(Path(selected_request.paper_smoke_report_path), smoke)
    if alpha is not None:
        write_report(Path(selected_request.alpha_paper_report_path), alpha)
    if reconcile is not None:
        write_report(Path(selected_request.paper_reconcile_report_path), reconcile)
    return selected_request


def test_alpha_test_summary_success_aggregates_campaign(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(),
        alpha=alpha_report(),
        reconcile=reconcile_report(),
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is True
    assert report.final_status == AlphaTestSummaryStatus.COMPLETED_WITH_WARNINGS
    assert report.campaign_id == CAMPAIGN_ID
    assert set(report.source_report_campaign_ids.values()) == {CAMPAIGN_ID}
    assert report.alpha_shadow_verified is True
    assert report.paper_smoke_verified is True
    assert report.alpha_paper_verified is True
    assert report.paper_reconcile_verified is True
    assert report.account_summary_verified is True
    assert report.open_order_count == 0
    assert report.latest_order_ids == [31, 32]
    assert report.latest_perm_ids == [3100, 3200]
    assert report.next_eligible_for_alpha_window is True
    assert report.order_api_invoked is False

    markdown = markdown_summary(report.model_dump(mode="json"))
    assert "IBKR Alpha Test Summary" in markdown
    assert CAMPAIGN_ID in markdown
    assert "Next eligible for alpha window" in markdown


def test_alpha_test_summary_missing_report_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(),
        alpha=alpha_report(),
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is False
    assert report.final_status == AlphaTestSummaryStatus.FAILED
    assert "paper-reconcile report not found" in " ".join(report.errors)


def test_alpha_test_summary_failed_source_report_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(ok=False),
        alpha=alpha_report(),
        reconcile=reconcile_report(),
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is False
    assert report.final_status == AlphaTestSummaryStatus.FAILED
    assert "paper-order-smoke report did not pass" in " ".join(report.errors)


def test_alpha_test_summary_mismatched_commit_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(commit_sha="def456"),
        smoke=smoke_report(),
        alpha=alpha_report(),
        reconcile=reconcile_report(),
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is False
    assert report.final_status == AlphaTestSummaryStatus.FAILED
    assert "different commit" in " ".join(report.errors)


def test_alpha_test_summary_mismatched_campaign_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(campaign_id="campaign-002"),
        alpha=alpha_report(),
        reconcile=reconcile_report(),
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is False
    assert report.final_status == AlphaTestSummaryStatus.FAILED
    assert "campaign_id" in " ".join(report.errors)


def test_alpha_test_summary_open_order_warns_and_blocks_next_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(),
        alpha=alpha_report(),
        reconcile=reconcile_report(open_order_count=1),
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is True
    assert report.final_status == AlphaTestSummaryStatus.COMPLETED_WITH_WARNINGS
    assert report.open_order_count == 1
    assert report.next_eligible_for_alpha_window is False
    assert "open broker orders" in " ".join(report.warnings)
    assert "open broker orders must be cleared" in " ".join(report.next_eligibility_reason)


def test_alpha_test_summary_rejects_legacy_reconciliation_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    legacy_reconcile = reconcile_report().model_copy(
        update={
            "source_report_compatibility": {
                "paper_smoke_report": "current",
                "alpha_paper_report": "legacy_incompatible",
            }
        }
    )
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(),
        alpha=alpha_report(),
        reconcile=legacy_reconcile,
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is False
    assert report.next_eligible_for_alpha_window is False
    assert "non-current source evidence" in " ".join(report.errors)


def test_alpha_test_summary_rejects_legacy_alpha_report_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(),
        reconcile=reconcile_report(),
    )
    legacy_alpha = alpha_report().model_dump(mode="json")
    legacy_alpha.pop("schema_version")
    Path(selected_request.alpha_paper_report_path).write_text(json.dumps(legacy_alpha))

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is False
    assert "legacy_incompatible" in " ".join(report.errors)


def test_alpha_test_summary_requires_reconcile_after_paper_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_summary._current_commit_sha", lambda: "abc123")
    selected_request = write_all_reports(
        tmp_path,
        shadow=shadow_report(),
        smoke=smoke_report(),
        alpha=alpha_report(),
        reconcile=reconcile_report(timestamp=now() - timedelta(minutes=5)),
    )

    report = run_alpha_test_summary(selected_request, now=now())

    assert report.ok is False
    assert report.final_status == AlphaTestSummaryStatus.FAILED
    assert report.next_eligible_for_alpha_window is False
    assert "older than the latest submitted paper order" in " ".join(report.errors)
