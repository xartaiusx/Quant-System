from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from trader.config import TraderConfig
from trader.models import (
    BrokerDiagnosticReport,
    HistoricalDatasetSummary,
    HistoricalLoaderReport,
    HistoricalLoadResult,
    HistoricalLoadStatus,
    HistoricalReadinessReport,
    HistoricalReadinessStatus,
    HistoricalReadinessSummary,
    HistoricalSnapshotLoadRequest,
    ManagedAccountInfo,
    PaperReadinessRunReport,
    PaperReadinessRunRequest,
    PaperReadinessRunStage,
    PaperReadinessRunStatus,
    PaperReadinessStageStatus,
)
from trader.paper_readiness import run_paper_readiness_run
from trader.reporting.reports import markdown_summary


def now() -> datetime:
    return datetime(2026, 5, 18, 21, 30, tzinfo=UTC)


def config(**overrides: object) -> TraderConfig:
    return TraderConfig(**overrides)


def request() -> PaperReadinessRunRequest:
    return PaperReadinessRunRequest(
        symbols=["SPY", "AAPL", "GLD", "USO", "DBA"],
        commodity_symbols=["GLD", "USO", "DBA"],
    )


def stage(
    name: str,
    *,
    ok: bool = True,
    status: PaperReadinessStageStatus = PaperReadinessStageStatus.COMPLETED,
) -> PaperReadinessRunStage:
    return PaperReadinessRunStage(
        name=name,
        command=name,
        ok=ok,
        final_status=status,
        started_at=now(),
        finished_at=now(),
        report_paths={f"{name}_json": f"reports/{name}.json"},
        errors=[] if ok else [f"{name} failed"],
    )


def broker_report(*, ok: bool = True, connected: bool = True) -> BrokerDiagnosticReport:
    return BrokerDiagnosticReport(
        ok=ok,
        mode="paper",
        host="127.0.0.1",
        port=7497,
        client_id=11,
        broker_kind="tws",
        connected=connected,
        ibapi_available=True,
        connection_attempted=True,
        managed_accounts_masked=[ManagedAccountInfo(account_id_masked="DUQ2****23")],
        final_status="connected" if ok and connected else "failed",
    )


def account_report(*, verified: bool = True) -> BrokerDiagnosticReport:
    report = broker_report(ok=True, connected=True)
    snapshot = (
        {
            "DUQ2****23": {
                "BuyingPower": {"value": "4014473.88", "currency": "USD"},
                "NetLiquidation": {"value": "1006292.18", "currency": "USD"},
            }
        }
        if verified
        else None
    )
    return report.model_copy(update={"account_snapshot": snapshot})


def readiness_report(
    statuses: dict[str, HistoricalReadinessStatus],
) -> HistoricalReadinessReport:
    summaries = [
        HistoricalReadinessSummary(
            symbol=symbol,
            requested_duration="1 D",
            requested_bar_size="5 mins",
            requested_what_to_show="TRADES",
            use_rth=1,
            bars_count=78,
            readiness_status=status,
        )
        for symbol, status in statuses.items()
    ]
    return HistoricalReadinessReport(
        ok=any(
            summary.readiness_status
            in {HistoricalReadinessStatus.READY, HistoricalReadinessStatus.PARTIAL}
            for summary in summaries
        ),
        mode="paper",
        host="127.0.0.1",
        port=7497,
        client_id=11,
        broker_kind="tws",
        symbols_requested=list(statuses),
        summaries=summaries,
        final_status=(
            "partial"
            if any(
                summary.readiness_status != HistoricalReadinessStatus.READY
                for summary in summaries
            )
            else "ready"
        ),
    )


def loader_report(statuses: dict[str, HistoricalLoadStatus]) -> HistoricalLoaderReport:
    load_request = HistoricalSnapshotLoadRequest(
        symbols=list(statuses),
        bar_size="5 mins",
        what_to_show="TRADES",
    )
    results = [
        HistoricalLoadResult(
            symbol=symbol,
            request=load_request,
            summary=HistoricalDatasetSummary(
                symbol=symbol,
                bar_size="5 mins",
                what_to_show="TRADES",
                bars_count=78,
                load_status=status,
            ),
            load_status=status,
        )
        for symbol, status in statuses.items()
    ]
    return HistoricalLoaderReport(
        command="history-load",
        ok=any(
            result.load_status in {HistoricalLoadStatus.LOADED, HistoricalLoadStatus.PARTIAL}
            for result in results
        ),
        request=load_request,
        base_data_path="data/historical",
        symbols_requested=list(statuses),
        results=results,
        summaries=[result.summary for result in results if result.summary is not None],
        final_status=(
            "partial"
            if any(result.load_status != HistoricalLoadStatus.LOADED for result in results)
            else "loaded"
        ),
    )


def patch_success_stages(monkeypatch, *, partial: bool = False) -> None:
    readiness_status = {
        "SPY": HistoricalReadinessStatus.READY,
        "AAPL": HistoricalReadinessStatus.READY,
        "GLD": HistoricalReadinessStatus.READY,
        "USO": HistoricalReadinessStatus.READY,
        "DBA": (
            HistoricalReadinessStatus.PARTIAL
            if partial
            else HistoricalReadinessStatus.READY
        ),
    }
    load_status = {
        symbol: (
            HistoricalLoadStatus.PARTIAL
            if partial and symbol == "DBA"
            else HistoricalLoadStatus.LOADED
        )
        for symbol in readiness_status
    }
    readiness = readiness_report(readiness_status)
    loader = loader_report(load_status)
    monkeypatch.setattr(
        "trader.paper_readiness._run_broker_probe_stage",
        lambda *args, **kwargs: (stage("broker_probe"), broker_report()),
    )
    monkeypatch.setattr(
        "trader.paper_readiness._run_account_summary_stage",
        lambda *args, **kwargs: (stage("account_summary"), account_report()),
    )
    monkeypatch.setattr(
        "trader.paper_readiness._run_history_snapshot_stage",
        lambda *args, **kwargs: (
            stage(
                "history_snapshot",
                status=(
                    PaperReadinessStageStatus.COMPLETED_WITH_WARNINGS
                    if partial
                    else PaperReadinessStageStatus.COMPLETED
                ),
            ),
            SimpleNamespace(ok=True, snapshot_paths=["data/historical/SPY/bars.jsonl"]),
            readiness,
        ),
    )
    monkeypatch.setattr(
        "trader.paper_readiness._run_history_load_stage",
        lambda *args, **kwargs: (
            stage(
                "history_load",
                status=(
                    PaperReadinessStageStatus.COMPLETED_WITH_WARNINGS
                    if partial
                    else PaperReadinessStageStatus.COMPLETED
                ),
            ),
            loader,
        ),
    )
    monkeypatch.setattr(
        "trader.paper_readiness._run_commodity_universe_stage",
        lambda *args, **kwargs: (
            stage("commodity_universe"),
            SimpleNamespace(ok=True),
        ),
    )
    monkeypatch.setattr(
        "trader.paper_readiness._run_signal_evaluation_stage",
        lambda *args, **kwargs: (
            stage("signal_evaluation"),
            SimpleNamespace(ok=True),
        ),
    )


def test_paper_readiness_run_completed(monkeypatch) -> None:
    patch_success_stages(monkeypatch)

    report = run_paper_readiness_run(config(), request())

    assert report.ok is True
    assert report.final_status == PaperReadinessRunStatus.COMPLETED
    assert report.broker_connected is True
    assert report.account_summary_verified is True
    assert report.history_snapshot_written is True
    assert report.signal_evaluation_completed is True
    assert report.submitted_orders is False
    assert report.paper_orders_enabled is False
    assert report.order_routing_enabled is False
    assert report.partial_symbols == []


def test_paper_readiness_run_completed_with_partial_symbol_warnings(monkeypatch) -> None:
    patch_success_stages(monkeypatch, partial=True)

    report = run_paper_readiness_run(config(), request())

    assert report.ok is True
    assert report.final_status == PaperReadinessRunStatus.COMPLETED_WITH_WARNINGS
    assert report.partial_symbols == ["DBA"]
    assert report.readiness_status_by_symbol["DBA"] == "partial"
    assert report.load_status_by_symbol["DBA"] == "partial"


def test_paper_readiness_run_fails_when_broker_probe_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "trader.paper_readiness._run_broker_probe_stage",
        lambda *args, **kwargs: (
            calls.append("broker")
            or stage("broker_probe", ok=False, status=PaperReadinessStageStatus.FAILED),
            broker_report(ok=False, connected=False),
        ),
    )
    monkeypatch.setattr(
        "trader.paper_readiness._run_account_summary_stage",
        lambda *args, **kwargs: calls.append("account"),
    )

    report = run_paper_readiness_run(config(), request())

    assert report.final_status == PaperReadinessRunStatus.FAILED
    assert report.broker_connected is False
    assert calls == ["broker"]


def test_paper_readiness_run_rejects_account_mock_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "trader.paper_readiness._run_broker_probe_stage",
        lambda *args, **kwargs: (stage("broker_probe"), broker_report()),
    )
    monkeypatch.setattr(
        "trader.paper_readiness._run_account_summary_stage",
        lambda *args, **kwargs: (
            stage("account_summary", ok=False, status=PaperReadinessStageStatus.FAILED),
            account_report(verified=False),
        ),
    )

    report = run_paper_readiness_run(config(), request())

    assert report.final_status == PaperReadinessRunStatus.FAILED
    assert report.account_summary_verified is False
    assert "broker account summary is unavailable or lacks funding tags" in report.errors


def test_paper_readiness_run_fails_when_signal_evaluation_fails(monkeypatch) -> None:
    patch_success_stages(monkeypatch)
    monkeypatch.setattr(
        "trader.paper_readiness._run_signal_evaluation_stage",
        lambda *args, **kwargs: (
            stage("signal_evaluation", ok=False, status=PaperReadinessStageStatus.FAILED),
            SimpleNamespace(ok=False),
        ),
    )

    report = run_paper_readiness_run(config(), request())

    assert report.final_status == PaperReadinessRunStatus.FAILED
    assert report.signal_evaluation_completed is False
    assert "signal evaluation failed" in report.errors


def test_paper_readiness_run_rejects_enabled_paper_orders_before_broker(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "trader.paper_readiness._run_broker_probe_stage",
        lambda *args, **kwargs: calls.append("broker"),
    )

    report = run_paper_readiness_run(config(allow_paper_orders=True), request())

    assert report.final_status == PaperReadinessRunStatus.FAILED
    assert report.configured_allow_paper_orders is True
    assert report.paper_orders_enabled is False
    assert calls == []


def test_paper_readiness_report_serializes_and_renders_markdown(monkeypatch) -> None:
    patch_success_stages(monkeypatch, partial=True)
    report = run_paper_readiness_run(config(), request())

    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert PaperReadinessRunReport.model_validate(payload).ok is True
    assert payload["submitted_orders"] is False
    assert payload["paper_orders_enabled"] is False
    assert "# Read-only IBKR Paper Readiness Run" in markdown
    assert "Submitted orders" in markdown
    assert "`DBA`" in markdown
