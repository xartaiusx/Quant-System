from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trader.models import (
    AlphaTestSummaryReport,
    AlphaTestSummaryRequest,
    AlphaTestSummaryStatus,
    BrokerOpenOrderSnapshot,
    PaperLedgerUpdateRequest,
    PaperLedgerUpdateStatus,
    PaperReconcileReport,
    PaperReconcileRequest,
    PaperReconcileStatus,
)
from trader.paper_ledger import run_paper_ledger_update
from trader.reporting.reports import markdown_summary

CAMPAIGN_ID = "campaign-001"
COMMIT_SHA = "abc123"


def now() -> datetime:
    return datetime(2026, 7, 5, 10, tzinfo=UTC)


def summary_report(
    *,
    campaign_id: str | None = CAMPAIGN_ID,
    commit_sha: str | None = COMMIT_SHA,
    open_order_count: int = 0,
    account_summary_verified: bool = True,
    next_eligible: bool = True,
) -> AlphaTestSummaryReport:
    return AlphaTestSummaryReport(
        ok=True,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=AlphaTestSummaryRequest(campaign_id=campaign_id),
        source_report_paths={
            "alpha_shadow_report": "reports/latest_alpha_shadow_run.json",
            "paper_smoke_report": "reports/latest_paper_order_smoke.json",
            "alpha_paper_report": "reports/latest_alpha_paper_run.json",
            "paper_reconcile_report": "reports/latest_paper_reconcile.json",
        },
        source_report_campaign_ids={
            "alpha_shadow_report": campaign_id,
            "paper_smoke_report": campaign_id,
            "alpha_paper_report": campaign_id,
            "paper_reconcile_report": campaign_id,
        },
        source_report_statuses={
            "alpha_shadow_report": "completed",
            "paper_smoke_report": "completed",
            "alpha_paper_report": "completed",
            "paper_reconcile_report": "completed",
        },
        alpha_shadow_verified=True,
        paper_smoke_verified=True,
        alpha_paper_verified=True,
        paper_reconcile_verified=True,
        account_ids_masked=["DUQ2****23"],
        account_summary_verified=account_summary_verified,
        open_order_count=open_order_count,
        latest_order_ids=[31, 32],
        latest_perm_ids=[3100, 3200],
        paper_smoke_order_status="Cancelled",
        paper_smoke_fill_quantity=Decimal("0"),
        paper_smoke_canceled=True,
        alpha_paper_order_status="Cancelled",
        alpha_paper_fill_quantity=Decimal("0"),
        alpha_paper_canceled=True,
        next_eligible_for_alpha_window=next_eligible,
        next_eligibility_reason=["ready_for_next_read_only_shadow"]
        if next_eligible
        else ["open broker orders must be cleared before the next alpha window"],
        submitted_orders=True,
        final_status=AlphaTestSummaryStatus.COMPLETED_WITH_WARNINGS,
        timestamp=now(),
    )


def reconcile_report(
    *,
    campaign_id: str | None = CAMPAIGN_ID,
    commit_sha: str | None = COMMIT_SHA,
    open_order_count: int = 0,
    account_summary_verified: bool = True,
    positions_query_completed: bool = True,
    broker_state_fingerprint: str | None = "fingerprint-001",
) -> PaperReconcileReport:
    open_orders = (
        [
            BrokerOpenOrderSnapshot(
                order_id=33,
                perm_id=3300,
                symbol="SPY",
                action="BUY",
                status="Submitted",
            )
        ]
        if open_order_count
        else []
    )
    return PaperReconcileReport(
        ok=True,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=PaperReconcileRequest(campaign_id=campaign_id),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=11,
        broker_kind="ib_gateway",
        broker_connected=True,
        account_summary_verified=account_summary_verified,
        account_summary_source="broker_read_only_account_summary",
        account_ids_masked=["DUQ2****23"],
        account_snapshot={
            "DUQ2****23": {
                "NetLiquidation": {"value": "1000000", "currency": "USD"}
            }
        },
        positions_snapshot=[],
        positions_source="broker_read_only_positions",
        broker_positions_available=positions_query_completed,
        positions_query_completed=positions_query_completed,
        zero_positions_confirmed=positions_query_completed and not open_orders,
        open_orders=open_orders,
        open_order_count=len(open_orders),
        executions_snapshot=[],
        executions_available=False,
        execution_order_ids=[],
        latest_order_ids=[31, 32],
        latest_perm_ids=[3100, 3200],
        broker_state_fingerprint=broker_state_fingerprint,
        final_status=PaperReconcileStatus.COMPLETED
        if not open_orders
        else PaperReconcileStatus.COMPLETED_WITH_WARNINGS,
        timestamp=now(),
    )


def write_report(path: Path, report: object) -> None:
    path.write_text(report.model_dump_json())  # type: ignore[attr-defined]


def request(tmp_path: Path) -> PaperLedgerUpdateRequest:
    return PaperLedgerUpdateRequest(
        campaign_id=CAMPAIGN_ID,
        alpha_test_summary_report_path=(tmp_path / "summary.json").as_posix(),
        paper_reconcile_report_path=(tmp_path / "reconcile.json").as_posix(),
        ledger_path=(tmp_path / "state" / "paper_ledger.jsonl").as_posix(),
    )


def test_paper_ledger_update_writes_and_upserts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.paper_ledger._current_commit_sha", lambda: COMMIT_SHA)
    selected_request = request(tmp_path)
    write_report(Path(selected_request.alpha_test_summary_report_path), summary_report())
    write_report(Path(selected_request.paper_reconcile_report_path), reconcile_report())

    report = run_paper_ledger_update(selected_request)

    assert report.ok is True
    assert report.final_status == PaperLedgerUpdateStatus.COMPLETED_WITH_WARNINGS
    assert report.ledger_entry_written is True
    assert report.replaced_existing_entry is False
    ledger_path = Path(selected_request.ledger_path)
    ledger_rows = ledger_path.read_text().splitlines()
    assert len(ledger_rows) == 1
    assert '"campaign_id":"campaign-001"' in ledger_rows[0]
    assert report.submitted_orders is False
    assert report.broker_contacted is False
    assert report.order_api_invoked is False

    second_report = run_paper_ledger_update(selected_request)

    assert second_report.ok is True
    assert second_report.replaced_existing_entry is True
    assert second_report.ledger_record_count == 1
    assert len(ledger_path.read_text().splitlines()) == 1


def test_paper_ledger_update_fails_on_campaign_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.paper_ledger._current_commit_sha", lambda: COMMIT_SHA)
    selected_request = request(tmp_path).model_copy(update={"campaign_id": None})
    write_report(
        Path(selected_request.alpha_test_summary_report_path),
        summary_report(campaign_id="campaign-a"),
    )
    write_report(
        Path(selected_request.paper_reconcile_report_path),
        reconcile_report(campaign_id="campaign-b"),
    )

    report = run_paper_ledger_update(selected_request)

    assert report.ok is False
    assert report.final_status == PaperLedgerUpdateStatus.FAILED
    assert any("mismatched campaign_id" in error for error in report.errors)
    assert not Path(selected_request.ledger_path).exists()


def test_paper_ledger_update_blocks_open_orders(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.paper_ledger._current_commit_sha", lambda: COMMIT_SHA)
    selected_request = request(tmp_path)
    write_report(
        Path(selected_request.alpha_test_summary_report_path),
        summary_report(open_order_count=1, next_eligible=False),
    )
    write_report(
        Path(selected_request.paper_reconcile_report_path),
        reconcile_report(open_order_count=1),
    )

    report = run_paper_ledger_update(selected_request)

    assert report.ok is False
    assert report.final_status == PaperLedgerUpdateStatus.FAILED
    assert any("open broker orders" in error for error in report.errors)
    assert not Path(selected_request.ledger_path).exists()


def test_paper_ledger_update_blocks_missing_broker_truth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.paper_ledger._current_commit_sha", lambda: COMMIT_SHA)
    selected_request = request(tmp_path)
    write_report(
        Path(selected_request.alpha_test_summary_report_path),
        summary_report(account_summary_verified=False, next_eligible=False),
    )
    write_report(
        Path(selected_request.paper_reconcile_report_path),
        reconcile_report(
            account_summary_verified=False,
            positions_query_completed=False,
            broker_state_fingerprint=None,
        ),
    )

    report = run_paper_ledger_update(selected_request)

    assert report.ok is False
    joined_errors = " ".join(report.errors)
    assert "verified account summary" in joined_errors
    assert "positions query" in joined_errors
    assert "broker_state_fingerprint" in joined_errors
    assert not Path(selected_request.ledger_path).exists()


def test_paper_ledger_update_markdown_rendering(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.paper_ledger._current_commit_sha", lambda: COMMIT_SHA)
    selected_request = request(tmp_path)
    write_report(Path(selected_request.alpha_test_summary_report_path), summary_report())
    write_report(Path(selected_request.paper_reconcile_report_path), reconcile_report())

    report = run_paper_ledger_update(selected_request)
    markdown = markdown_summary(report.model_dump(mode="json"))

    assert "# IBKR Paper Ledger Update" in markdown
    assert "paper-ledger-update" in markdown
    assert "fingerprint-001" in markdown
    assert "Order API invoked: `False`" in markdown
