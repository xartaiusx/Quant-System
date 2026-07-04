from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from trader.alpha_shadow import run_alpha_shadow_run
from trader.backtest.data_adapter import build_backtest_feed
from trader.config import TraderConfig
from trader.models import (
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaShadowRunStatus,
    AnalyticalSignalEvaluationRequest,
    BacktestAlignmentMode,
    BrokerDiagnosticReport,
    DataQualityGateReport,
    DataQualityGateRequest,
    DataQualityGateStatus,
    DataQualityGateSymbolResult,
    HistoricalDatasetSummary,
    HistoricalLoadedBar,
    HistoricalLoadedDataset,
    HistoricalLoaderReport,
    HistoricalLoadResult,
    HistoricalLoadStatus,
    HistoricalSnapshotLoadRequest,
    ManagedAccountInfo,
    PaperReadinessRunStage,
    PaperReadinessStageStatus,
)
from trader.reporting.reports import markdown_summary
from trader.strategy.signal_evaluation import build_analytical_signal_evaluation_report


def now() -> datetime:
    return datetime(2026, 5, 18, 21, 30, tzinfo=UTC)


def config(**overrides: object) -> TraderConfig:
    return TraderConfig(**overrides)


def request() -> AlphaShadowRunRequest:
    return AlphaShadowRunRequest(broker_stage_pause_seconds=0)


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
        warnings=[],
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
                "TotalCashValue": {"value": "1006292.18", "currency": "USD"},
            }
        }
        if verified
        else None
    )
    return report.model_copy(update={"account_snapshot": snapshot})


def bars(*, rising: bool = True) -> list[HistoricalLoadedBar]:
    start = datetime(2026, 5, 18, 13, tzinfo=UTC)
    loaded: list[HistoricalLoadedBar] = []
    for index in range(25):
        price = Decimal("500") + Decimal(index if rising else 25 - index)
        timestamp = start + timedelta(minutes=5 * index)
        loaded.append(
            HistoricalLoadedBar(
                symbol="SPY",
                timestamp=timestamp,
                raw_timestamp=timestamp.isoformat(),
                open=price - Decimal("0.50"),
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("100000"),
                typical_price=price,
                dollar_volume=price * Decimal("100000"),
                interval_seconds=300,
                duration="1 D",
                bar_size="5 mins",
                what_to_show="TRADES",
                use_rth=1,
            )
        )
    return loaded


def loader_report(*, rising: bool = True) -> HistoricalLoaderReport:
    loaded_bars = bars(rising=rising)
    load_request = HistoricalSnapshotLoadRequest(
        symbols=["SPY"],
        bar_size="5 mins",
        what_to_show="TRADES",
    )
    summary = HistoricalDatasetSummary(
        symbol="SPY",
        bar_size="5 mins",
        what_to_show="TRADES",
        snapshot_timestamp="20260518T213000Z",
        bars_path="data/historical/SPY/5_mins/TRADES/spy_bars.jsonl",
        manifest_path="data/historical/SPY/5_mins/TRADES/spy_manifest.json",
        bars_count=len(loaded_bars),
        first_timestamp=loaded_bars[0].timestamp,
        last_timestamp=loaded_bars[-1].timestamp,
        volume_count=len(loaded_bars),
        total_volume=Decimal("2500000"),
        average_volume=Decimal("100000"),
        dollar_volume_count=len(loaded_bars),
        total_dollar_volume=Decimal("1250000000"),
        average_dollar_volume=Decimal("50000000"),
        manifest_bar_count=len(loaded_bars),
        manifest_matches_bars=True,
        load_status=HistoricalLoadStatus.LOADED,
    )
    dataset = HistoricalLoadedDataset(
        symbol="SPY",
        bar_size="5 mins",
        what_to_show="TRADES",
        snapshot_timestamp="20260518T213000Z",
        bars_path=summary.bars_path or "",
        manifest_path=summary.manifest_path or "",
        bars=loaded_bars,
        summary=summary,
    )
    result = HistoricalLoadResult(
        symbol="SPY",
        request=load_request,
        dataset=dataset,
        summary=summary,
        load_status=HistoricalLoadStatus.LOADED,
    )
    return HistoricalLoaderReport(
        command="history-load",
        ok=True,
        request=load_request,
        base_data_path="data/historical",
        symbols_requested=["SPY"],
        results=[result],
        summaries=[summary],
        warnings=["No broker contacted; offline snapshot load only"],
        final_status="loaded",
    )


def signal_report(source_loader: HistoricalLoaderReport):
    datasets = [
        result.dataset
        for result in source_loader.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=BacktestAlignmentMode.UNION)
    return build_analytical_signal_evaluation_report(
        feed,
        AnalyticalSignalEvaluationRequest(
            symbols=["SPY"],
            alignment_mode=BacktestAlignmentMode.UNION,
            requested_bar_size="5 mins",
            requested_what_to_show="TRADES",
            short_window=5,
            long_window=20,
        ),
    )


def data_quality_report(*, ok: bool = True) -> DataQualityGateReport:
    status = DataQualityGateStatus.PASSED if ok else DataQualityGateStatus.FAILED
    result = DataQualityGateSymbolResult(
        symbol="SPY",
        status=status,
        bars_count=78,
        zero_volume_bars=0,
        average_volume=Decimal("100000"),
        average_dollar_volume=Decimal("50000000"),
        load_status="loaded",
        readiness_status="ready",
        errors=[] if ok else ["average volume observed 0; expected at least 100"],
    )
    return DataQualityGateReport(
        ok=ok,
        request=DataQualityGateRequest(
            symbols=["SPY"],
            bar_size="5 mins",
            what_to_show="TRADES",
            min_average_volume=Decimal("100"),
            min_average_dollar_volume=Decimal("5000"),
        ),
        symbols_requested=["SPY"],
        results=[result],
        readiness_final_status="ready",
        loader_final_status="loaded",
        errors=result.errors,
        final_status=status,
    )


def patch_success_stages(monkeypatch, *, rising: bool = True) -> HistoricalLoaderReport:
    source_loader = loader_report(rising=rising)
    monkeypatch.setattr(
        "trader.alpha_shadow._run_broker_probe_stage",
        lambda *args, **kwargs: (stage("broker_probe"), broker_report()),
    )
    monkeypatch.setattr(
        "trader.alpha_shadow._run_account_summary_stage",
        lambda *args, **kwargs: (stage("account_summary"), account_report()),
    )
    monkeypatch.setattr(
        "trader.alpha_shadow._run_history_snapshot_stage",
        lambda *args, **kwargs: (
            stage("history_snapshot"),
            SimpleNamespace(ok=True, snapshot_paths=["data/historical/SPY/bars.jsonl"]),
            SimpleNamespace(ok=True),
        ),
    )
    monkeypatch.setattr(
        "trader.alpha_shadow._run_history_load_stage",
        lambda *args, **kwargs: (stage("history_load"), source_loader),
    )
    monkeypatch.setattr(
        "trader.alpha_shadow._run_data_quality_stage",
        lambda *args, **kwargs: (stage("data_quality_gate"), data_quality_report()),
    )
    monkeypatch.setattr(
        "trader.alpha_shadow._run_signal_evaluation_stage",
        lambda *args, **kwargs: (stage("signal_evaluation"), signal_report(source_loader)),
    )
    return source_loader


def test_alpha_shadow_run_completed_with_simulated_fill(monkeypatch) -> None:
    patch_success_stages(monkeypatch, rising=True)

    report = run_alpha_shadow_run(config(), request())

    assert report.ok is True
    assert report.final_status == AlphaShadowRunStatus.COMPLETED
    assert report.broker_connected is True
    assert report.account_summary_verified is True
    assert report.data_quality_completed is True
    assert report.signal_evaluation_completed is True
    assert report.shadow_signal_count == 1
    assert report.trade_plan_count == 1
    assert report.risk_approved_count == 1
    assert report.simulated_fill_count == 1
    assert report.submitted_orders is False
    assert report.paper_orders_enabled is False
    assert report.order_routing_enabled is False


def test_alpha_shadow_run_completed_with_warning_for_hold_signal(monkeypatch) -> None:
    patch_success_stages(monkeypatch, rising=False)

    report = run_alpha_shadow_run(config(), request())

    assert report.ok is True
    assert report.final_status == AlphaShadowRunStatus.COMPLETED_WITH_WARNINGS
    assert report.shadow_signal_count == 1
    assert report.trade_plan_count == 0
    assert report.simulation_result_count == 0
    assert "shadow signal did not produce a trade plan" in report.warnings


def test_alpha_shadow_run_rejects_enabled_paper_orders_before_broker(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "trader.alpha_shadow._run_broker_probe_stage",
        lambda *args, **kwargs: calls.append("broker"),
    )

    report = run_alpha_shadow_run(config(allow_paper_orders=True), request())

    assert report.final_status == AlphaShadowRunStatus.FAILED
    assert report.configured_allow_paper_orders is True
    assert report.paper_orders_enabled is False
    assert calls == []


def test_alpha_shadow_run_rejects_non_tws_paper_port() -> None:
    report = run_alpha_shadow_run(config(ibkr_port=4002), request())

    assert report.final_status == AlphaShadowRunStatus.FAILED
    assert "IBKR_PORT must be 7497 for TWS paper alpha-shadow-run" in report.errors


def test_alpha_shadow_run_fails_when_broker_probe_fails(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "trader.alpha_shadow._run_broker_probe_stage",
        lambda *args, **kwargs: (
            calls.append("broker")
            or stage("broker_probe", ok=False, status=PaperReadinessStageStatus.FAILED),
            broker_report(ok=False, connected=False),
        ),
    )
    monkeypatch.setattr(
        "trader.alpha_shadow._run_account_summary_stage",
        lambda *args, **kwargs: calls.append("account"),
    )

    report = run_alpha_shadow_run(config(), request())

    assert report.final_status == AlphaShadowRunStatus.FAILED
    assert report.broker_connected is False
    assert calls == ["broker"]


def test_alpha_shadow_run_rejects_account_mock_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "trader.alpha_shadow._run_broker_probe_stage",
        lambda *args, **kwargs: (stage("broker_probe"), broker_report()),
    )
    monkeypatch.setattr(
        "trader.alpha_shadow._run_account_summary_stage",
        lambda *args, **kwargs: (
            stage("account_summary", ok=False, status=PaperReadinessStageStatus.FAILED),
            account_report(verified=False),
        ),
    )

    report = run_alpha_shadow_run(config(), request())

    assert report.final_status == AlphaShadowRunStatus.FAILED
    assert report.account_summary_verified is False
    assert "broker account summary is unavailable or lacks funding tags" in report.errors


def test_alpha_shadow_run_fails_when_data_quality_fails(monkeypatch) -> None:
    source_loader = loader_report(rising=True)
    patch_success_stages(monkeypatch, rising=True)
    monkeypatch.setattr(
        "trader.alpha_shadow._run_data_quality_stage",
        lambda *args, **kwargs: (
            stage("data_quality_gate", ok=False, status=PaperReadinessStageStatus.FAILED),
            data_quality_report(ok=False),
        ),
    )
    signal_calls: list[str] = []
    monkeypatch.setattr(
        "trader.alpha_shadow._run_signal_evaluation_stage",
        lambda *args, **kwargs: signal_calls.append("signal") or signal_report(source_loader),
    )

    report = run_alpha_shadow_run(config(), request())

    assert report.final_status == AlphaShadowRunStatus.FAILED
    assert report.data_quality_completed is False
    assert signal_calls == []


def test_alpha_shadow_run_fails_when_signal_evaluation_fails(monkeypatch) -> None:
    patch_success_stages(monkeypatch, rising=True)
    monkeypatch.setattr(
        "trader.alpha_shadow._run_signal_evaluation_stage",
        lambda *args, **kwargs: (
            stage("signal_evaluation", ok=False, status=PaperReadinessStageStatus.FAILED),
            SimpleNamespace(ok=False),
        ),
    )

    report = run_alpha_shadow_run(config(), request())

    assert report.final_status == AlphaShadowRunStatus.FAILED
    assert report.signal_evaluation_completed is False
    assert "SPY signal evaluation failed" in report.errors


def test_alpha_shadow_report_serializes_and_renders_markdown(monkeypatch) -> None:
    patch_success_stages(monkeypatch, rising=True)
    report = run_alpha_shadow_run(config(), request())

    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert AlphaShadowRunReport.model_validate(payload).ok is True
    assert payload["submitted_orders"] is False
    assert payload["paper_orders_enabled"] is False
    assert "# Read-only IBKR Alpha Shadow Run" in markdown
    assert "Submitted orders" in markdown
    assert "`SPY`" in markdown
