from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trader.alpha_campaign import READ_ONLY_OFF_CONFIRMATION, run_alpha_campaign_run
from trader.config import BrokerKind, TraderConfig, TradingMode
from trader.models import (
    AlphaCampaignRunRequest,
    AlphaCampaignRunStatus,
    AlphaPaperRunReport,
    AlphaPaperRunRequest,
    AlphaPaperRunStatus,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaShadowRunStatus,
    AlphaTestSummaryReport,
    AlphaTestSummaryRequest,
    AlphaTestSummaryStatus,
    PaperReconcileReport,
    PaperReconcileRequest,
    PaperReconcileStatus,
)
from trader.reporting.journal import Journal
from trader.reporting.reports import markdown_summary

CAMPAIGN_ID = "campaign-001"


def now() -> datetime:
    return datetime(2026, 7, 5, 10, tzinfo=UTC)


def config(**overrides: object) -> TraderConfig:
    values: dict[str, object] = {
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 4002,
        "ibkr_client_id": 21,
        "broker_kind": BrokerKind.IB_GATEWAY,
        "trading_mode": TradingMode.PAPER,
        "allow_paper_orders": False,
        "allow_live_orders": False,
        "max_trade_notional": Decimal("1000"),
        "max_open_positions": 1,
    }
    values.update(overrides)
    return TraderConfig(**values)


def shadow_report() -> AlphaShadowRunReport:
    return AlphaShadowRunReport(
        ok=True,
        commit_sha="abc123",
        campaign_id=CAMPAIGN_ID,
        request=AlphaShadowRunRequest(campaign_id=CAMPAIGN_ID),
        selected_universe=["SPY"],
        account_summary_verified=True,
        history_snapshot_written=True,
        history_load_completed=True,
        data_quality_completed=True,
        signal_evaluation_completed=True,
        final_status=AlphaShadowRunStatus.COMPLETED,
        timestamp=now(),
    )


def alpha_paper_report() -> AlphaPaperRunReport:
    return AlphaPaperRunReport(
        ok=True,
        commit_sha="abc123",
        campaign_id=CAMPAIGN_ID,
        request=AlphaPaperRunRequest(campaign_id=CAMPAIGN_ID, confirm="ALPHA_PAPER_SPY_1"),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=21,
        broker_kind="ib_gateway",
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
        order_routing_enabled=True,
        paper_execution_enabled=True,
        order_api_invoked=True,
        place_order_invoked=True,
        cancel_order_invoked=True,
        order_id=101,
        perm_id=202,
        order_status="Cancelled",
        fill_quantity=Decimal("0"),
        cancel_requested=True,
        canceled=True,
        final_status=AlphaPaperRunStatus.COMPLETED,
        timestamp=now(),
    )


def reconcile_report() -> PaperReconcileReport:
    return PaperReconcileReport(
        ok=True,
        commit_sha="abc123",
        campaign_id=CAMPAIGN_ID,
        request=PaperReconcileRequest(campaign_id=CAMPAIGN_ID),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=11,
        broker_kind="ib_gateway",
        broker_connected=True,
        account_summary_verified=True,
        account_summary_source="broker_read_only_account_summary",
        account_ids_masked=["DUQ2****23"],
        positions_query_completed=True,
        zero_positions_confirmed=True,
        broker_positions_available=True,
        latest_order_ids=[101],
        latest_perm_ids=[202],
        final_status=PaperReconcileStatus.COMPLETED,
        timestamp=now(),
    )


def summary_report() -> AlphaTestSummaryReport:
    return AlphaTestSummaryReport(
        ok=True,
        commit_sha="abc123",
        campaign_id=CAMPAIGN_ID,
        request=AlphaTestSummaryRequest(campaign_id=CAMPAIGN_ID),
        alpha_shadow_verified=True,
        paper_smoke_verified=True,
        alpha_paper_verified=True,
        paper_reconcile_verified=True,
        account_summary_verified=True,
        open_order_count=0,
        latest_order_ids=[101],
        latest_perm_ids=[202],
        next_eligible_for_alpha_window=True,
        next_eligibility_reason=["ready_for_next_read_only_shadow"],
        submitted_orders=True,
        final_status=AlphaTestSummaryStatus.COMPLETED,
        timestamp=now(),
    )


def test_alpha_campaign_shadow_runs_shadow_stage(tmp_path) -> None:
    calls: list[str] = []

    def fake_shadow(_config: TraderConfig, request: AlphaShadowRunRequest) -> AlphaShadowRunReport:
        calls.append(request.campaign_id or "")
        return shadow_report()

    report = run_alpha_campaign_run(
        config(),
        AlphaCampaignRunRequest(campaign_id=CAMPAIGN_ID, mode="shadow"),
        journal=Journal(tmp_path),
        alpha_shadow_runner=fake_shadow,
    )

    assert report.ok is True
    assert report.final_status == AlphaCampaignRunStatus.COMPLETED_WITH_WARNINGS
    assert report.campaign_id == CAMPAIGN_ID
    assert calls == [CAMPAIGN_ID]
    assert report.alpha_shadow_completed is True
    assert report.submitted_orders is False
    assert "alpha_shadow_run_json" in report.report_paths

    markdown = markdown_summary(report.model_dump(mode="json"))
    assert "IBKR Alpha Campaign Run" in markdown
    assert CAMPAIGN_ID in markdown


def test_alpha_campaign_paper_requires_read_only_off_confirmation(tmp_path) -> None:
    report = run_alpha_campaign_run(
        config(allow_paper_orders=True),
        AlphaCampaignRunRequest(campaign_id=CAMPAIGN_ID, mode="paper"),
        journal=Journal(tmp_path),
    )

    assert report.ok is False
    assert report.final_status == AlphaCampaignRunStatus.FAILED
    assert "READ_ONLY_OFF_FOR_ALPHA_PAPER" in " ".join(report.errors)
    assert report.order_api_invoked is False


def test_alpha_campaign_paper_runs_alpha_reconcile_and_summary(tmp_path) -> None:
    seen: dict[str, object] = {}

    def fake_alpha_paper(
        run_config: TraderConfig,
        request: AlphaPaperRunRequest,
    ) -> AlphaPaperRunReport:
        seen["paper_config_allow"] = run_config.allow_paper_orders
        seen["paper_request_campaign"] = request.campaign_id
        return alpha_paper_report()

    def fake_reconcile(
        run_config: TraderConfig,
        request: PaperReconcileRequest,
    ) -> PaperReconcileReport:
        seen["reconcile_config_allow"] = run_config.allow_paper_orders
        seen["reconcile_client_id"] = run_config.ibkr_client_id
        seen["reconcile_alpha_path"] = request.alpha_paper_report_path
        return reconcile_report()

    def fake_summary(request: AlphaTestSummaryRequest) -> AlphaTestSummaryReport:
        seen["summary_campaign"] = request.campaign_id
        seen["summary_reconcile_path"] = request.paper_reconcile_report_path
        return summary_report()

    report = run_alpha_campaign_run(
        config(allow_paper_orders=True),
        AlphaCampaignRunRequest(
            campaign_id=CAMPAIGN_ID,
            mode="paper",
            alpha_shadow_report_path="reports/latest_alpha_shadow_run.json",
            paper_smoke_report_path="reports/latest_paper_order_smoke.json",
            read_only_off_confirm=READ_ONLY_OFF_CONFIRMATION,
            cancel_after_seconds=0,
        ),
        journal=Journal(tmp_path),
        alpha_paper_runner=fake_alpha_paper,
        paper_reconcile_runner=fake_reconcile,
        alpha_summary_runner=fake_summary,
    )

    assert report.ok is True
    assert report.final_status == AlphaCampaignRunStatus.COMPLETED_WITH_WARNINGS
    assert report.submitted_orders is True
    assert report.order_api_invoked is True
    assert report.paper_orders_enabled is False
    assert report.read_only_restore_required is True
    assert report.alpha_paper_completed is True
    assert report.paper_reconcile_completed is True
    assert report.alpha_test_summary_completed is True
    assert seen["paper_config_allow"] is True
    assert seen["paper_request_campaign"] == CAMPAIGN_ID
    assert seen["reconcile_config_allow"] is False
    assert seen["reconcile_client_id"] == 11
    assert str(seen["reconcile_alpha_path"]).endswith(".json")
    assert seen["summary_campaign"] == CAMPAIGN_ID
    assert str(seen["summary_reconcile_path"]).endswith(".json")
