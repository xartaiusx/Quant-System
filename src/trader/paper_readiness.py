"""Read-only IBKR paper-client readiness orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from trader.backtest.data_adapter import build_backtest_feed
from trader.config import TraderConfig
from trader.data.commodity_universe import build_commodity_research_universe_report
from trader.data.historical import (
    attach_snapshot_paths,
    build_readiness_report,
    write_historical_snapshot_result,
)
from trader.data.historical_loader import load_historical_snapshots
from trader.models import (
    AnalyticalSignalEvaluationReport,
    AnalyticalSignalEvaluationRequest,
    BacktestAlignmentMode,
    BrokerDiagnosticReport,
    BrokerErrorEvent,
    CommodityResearchUniverseReport,
    CommodityResearchUniverseRequest,
    HistoricalLoaderReport,
    HistoricalLoadStatus,
    HistoricalReadinessReport,
    HistoricalReadinessStatus,
    HistoricalSnapshotLoadRequest,
    HistoricalSnapshotReport,
    PaperReadinessRunReport,
    PaperReadinessRunRequest,
    PaperReadinessRunStage,
    PaperReadinessRunStatus,
    PaperReadinessStageStatus,
    SerializableModel,
    utc_now,
)
from trader.reporting.journal import Journal
from trader.strategy.signal_evaluation import build_analytical_signal_evaluation_report

DEFAULT_PAPER_READINESS_SYMBOLS = ["SPY", "AAPL", "GLD", "USO", "DBA"]
DEFAULT_COMMODITY_PROXY_SYMBOLS = ["GLD", "USO", "DBA"]
_FUNDING_TAGS = {
    "AvailableFunds",
    "BuyingPower",
    "CashBalance",
    "NetLiquidation",
    "TotalCashValue",
}


class PaperReadinessBrokerClient(Protocol):
    """Broker surface required by the read-only readiness orchestration."""

    def diagnostic_report(
        self,
        *,
        timeout: float | None = None,
        include_managed_accounts: bool = True,
        include_account: bool = False,
        include_positions: bool = False,
    ) -> BrokerDiagnosticReport:
        """Return a read-only broker diagnostic report."""

    def request_historical_snapshots(
        self,
        symbols: list[str],
        *,
        duration: str,
        bar_size: str,
        what_to_show: str,
        use_rth: int,
        timeout: float | None = None,
    ) -> HistoricalSnapshotReport:
        """Request read-only historical data snapshots."""


BrokerClientFactory = Callable[[TraderConfig], PaperReadinessBrokerClient]
BrokerProbeStageResult = tuple[PaperReadinessRunStage, BrokerDiagnosticReport | None]
HistorySnapshotStageResult = tuple[
    PaperReadinessRunStage,
    HistoricalSnapshotReport | None,
    HistoricalReadinessReport | None,
]
HistoryLoadStageResult = tuple[PaperReadinessRunStage, HistoricalLoaderReport | None]
CommodityUniverseStageResult = tuple[
    PaperReadinessRunStage,
    CommodityResearchUniverseReport | None,
]
SignalEvaluationStageResult = tuple[
    PaperReadinessRunStage,
    AnalyticalSignalEvaluationReport | None,
]


def default_broker_client_factory(config: TraderConfig) -> PaperReadinessBrokerClient:
    """Create the IBKR client lazily so importing this module stays broker-light."""

    from trader.broker.ibkr_client import IBKRClient

    return cast(PaperReadinessBrokerClient, IBKRClient(config))


def run_paper_readiness_run(
    config: TraderConfig,
    request: PaperReadinessRunRequest | None = None,
    *,
    journal: Journal | None = None,
    broker_client_factory: BrokerClientFactory = default_broker_client_factory,
) -> PaperReadinessRunReport:
    """Run the first paper-client readiness workflow with no order routing."""

    readiness_request = request or PaperReadinessRunRequest()
    selected_journal = journal or Journal()
    stages: list[PaperReadinessRunStage] = []
    run_warnings = [
        "TWS Read-Only API is expected to remain enabled; the API setting is operator-verified.",
        "No order APIs invoked; order routing remains disabled.",
    ]
    run_errors: list[str] = []

    if config.allow_paper_orders:
        run_errors.append("ALLOW_PAPER_ORDERS=true is not accepted for paper-readiness-run")
    if config.allow_live_orders:
        run_errors.append("ALLOW_LIVE_ORDERS=true is not accepted")
    if config.trading_mode.value != "paper":
        run_errors.append("TRADING_MODE must be paper for the first paper-client run")

    if run_errors:
        return _build_run_report(
            config,
            readiness_request,
            stages,
            final_status=PaperReadinessRunStatus.FAILED,
            warnings=run_warnings,
            errors=run_errors,
        )

    broker_stage, broker_report = _run_broker_probe_stage(
        config,
        readiness_request,
        journal=selected_journal,
        broker_client_factory=broker_client_factory,
    )
    stages.append(broker_stage)
    if not _broker_stage_passed(broker_report):
        return _build_run_report(
            config,
            readiness_request,
            stages,
            final_status=PaperReadinessRunStatus.FAILED,
            warnings=run_warnings,
            errors=["broker probe failed"],
        )

    account_stage, account_report = _run_account_summary_stage(
        config,
        readiness_request,
        journal=selected_journal,
        broker_client_factory=broker_client_factory,
    )
    stages.append(account_stage)
    if not _account_stage_passed(account_report):
        return _build_run_report(
            config,
            readiness_request,
            stages,
            final_status=PaperReadinessRunStatus.FAILED,
            warnings=run_warnings,
            errors=["broker account summary is unavailable or lacks funding tags"],
        )

    snapshot_stage, snapshot_report, readiness_report = _run_history_snapshot_stage(
        config,
        readiness_request,
        journal=selected_journal,
        broker_client_factory=broker_client_factory,
    )
    stages.append(snapshot_stage)
    if not _history_snapshot_stage_passed(snapshot_report, readiness_report):
        return _build_run_report(
            config,
            readiness_request,
            stages,
            final_status=PaperReadinessRunStatus.FAILED,
            warnings=run_warnings,
            errors=["no usable historical snapshots were written"],
            broker_report=broker_report,
            account_report=account_report,
            snapshot_report=snapshot_report,
            readiness_report=readiness_report,
        )

    load_stage, loader_report = _run_history_load_stage(
        readiness_request,
        journal=selected_journal,
    )
    stages.append(load_stage)
    if not _history_load_stage_passed(loader_report):
        return _build_run_report(
            config,
            readiness_request,
            stages,
            final_status=PaperReadinessRunStatus.FAILED,
            warnings=run_warnings,
            errors=["no usable historical snapshots loaded"],
            broker_report=broker_report,
            account_report=account_report,
            snapshot_report=snapshot_report,
            readiness_report=readiness_report,
            loader_report=loader_report,
        )
    assert loader_report is not None

    commodity_stage, commodity_report = _run_commodity_universe_stage(
        readiness_request,
        journal=selected_journal,
    )
    stages.append(commodity_stage)

    signal_stage, signal_report = _run_signal_evaluation_stage(
        readiness_request,
        loader_report,
        journal=selected_journal,
    )
    stages.append(signal_stage)
    if signal_report is None or not signal_report.ok:
        return _build_run_report(
            config,
            readiness_request,
            stages,
            final_status=PaperReadinessRunStatus.FAILED,
            warnings=run_warnings,
            errors=["signal evaluation failed"],
            broker_report=broker_report,
            account_report=account_report,
            snapshot_report=snapshot_report,
            readiness_report=readiness_report,
            loader_report=loader_report,
            commodity_report=commodity_report,
            signal_report=signal_report,
        )

    partial_symbols = _partial_symbols(readiness_report, loader_report)
    final_status = (
        PaperReadinessRunStatus.COMPLETED_WITH_WARNINGS
        if partial_symbols
        else PaperReadinessRunStatus.COMPLETED
    )
    return _build_run_report(
        config,
        readiness_request,
        stages,
        final_status=final_status,
        warnings=run_warnings,
        errors=[],
        broker_report=broker_report,
        account_report=account_report,
        snapshot_report=snapshot_report,
        readiness_report=readiness_report,
        loader_report=loader_report,
        commodity_report=commodity_report,
        signal_report=signal_report,
    )


def _run_broker_probe_stage(
    config: TraderConfig,
    request: PaperReadinessRunRequest,
    *,
    journal: Journal,
    broker_client_factory: BrokerClientFactory,
) -> BrokerProbeStageResult:
    started_at = utc_now()
    try:
        report = broker_client_factory(config).diagnostic_report(
            timeout=request.broker_timeout_seconds,
            include_managed_accounts=True,
        )
        paths = _write_model_report(journal, "broker_probe", report)
        errors = _broker_error_messages(report.errors)
        ok = _broker_stage_passed(report)
        return (
            _stage(
                "broker_probe",
                f"broker-probe --timeout {request.broker_timeout_seconds:g}",
                ok=ok,
                status=_completed_or_failed(ok),
                started_at=started_at,
                report_paths=paths,
                warnings=report.warnings,
                errors=errors if errors else [] if ok else ["broker probe failed"],
            ),
            report,
        )
    except Exception as exc:
        return _exception_stage(
            "broker_probe",
            f"broker-probe --timeout {request.broker_timeout_seconds:g}",
            started_at,
            exc,
        ), None


def _run_account_summary_stage(
    config: TraderConfig,
    request: PaperReadinessRunRequest,
    *,
    journal: Journal,
    broker_client_factory: BrokerClientFactory,
) -> BrokerProbeStageResult:
    started_at = utc_now()
    command = f"account --connect --timeout {request.broker_timeout_seconds:g}"
    try:
        report = broker_client_factory(config).diagnostic_report(
            timeout=request.broker_timeout_seconds,
            include_managed_accounts=True,
            include_account=True,
        )
        verified = _account_stage_passed(report)
        warnings = list(report.warnings)
        errors = _broker_error_messages(report.errors)
        if report.account_snapshot is None:
            errors.append("broker account summary unavailable; mock fallback is not accepted")
        elif not _account_summary_has_funding_tags(report.account_snapshot):
            errors.append("broker account summary did not include funding verification tags")
        payload = _account_summary_payload(report, account_summary_verified=verified)
        paths = _write_mapping_report(journal, "account_summary", payload)
        return (
            _stage(
                "account_summary",
                command,
                ok=verified,
                status=_completed_or_failed(verified),
                started_at=started_at,
                report_paths=paths,
                warnings=warnings,
                errors=list(dict.fromkeys(errors)),
            ),
            report,
        )
    except Exception as exc:
        return _exception_stage("account_summary", command, started_at, exc), None


def _run_history_snapshot_stage(
    config: TraderConfig,
    request: PaperReadinessRunRequest,
    *,
    journal: Journal,
    broker_client_factory: BrokerClientFactory,
) -> HistorySnapshotStageResult:
    started_at = utc_now()
    command = (
        f'history-snapshot --symbols {",".join(request.symbols)} '
        f'--duration "{request.duration}" --bar-size "{request.bar_size}" '
        f"--what-to-show {request.what_to_show} --use-rth {request.use_rth} "
        f"--timeout {request.history_timeout_seconds:g}"
    )
    try:
        snapshot_report = _fetch_historical_snapshot_report(
            config,
            request,
            broker_client_factory=broker_client_factory,
        )
        snapshot_paths = _write_model_report(journal, "history_snapshot", snapshot_report)
        readiness_report = build_readiness_report(
            config,
            manifest_paths=snapshot_report.manifest_paths,
            base_dir=request.base_data_path,
        )
        readiness_paths = _write_model_report(journal, "history_readiness", readiness_report)
        ok = _history_snapshot_stage_passed(snapshot_report, readiness_report)
        partial = _readiness_has_partial_symbols(readiness_report) or not all(
            result.ok for result in snapshot_report.results
        )
        status = _completed_partial_or_failed(ok, partial)
        errors = [
            *_broker_error_messages(snapshot_report.errors),
            *readiness_report.errors,
        ]
        if not snapshot_report.snapshot_paths:
            errors.append("no historical snapshot files were written")
        return (
            _stage(
                "history_snapshot",
                command,
                ok=ok,
                status=status,
                started_at=started_at,
                report_paths={
                    "history_snapshot_json": snapshot_paths["json"],
                    "history_snapshot_markdown": snapshot_paths["markdown"],
                    "history_readiness_json": readiness_paths["json"],
                    "history_readiness_markdown": readiness_paths["markdown"],
                },
                warnings=[*snapshot_report.warnings, *readiness_report.warnings],
                errors=list(dict.fromkeys(errors)),
            ),
            snapshot_report,
            readiness_report,
        )
    except Exception as exc:
        return _exception_stage("history_snapshot", command, started_at, exc), None, None


def _run_history_load_stage(
    request: PaperReadinessRunRequest,
    *,
    journal: Journal,
) -> HistoryLoadStageResult:
    started_at = utc_now()
    command = (
        f"history-load --symbols {','.join(request.symbols)} "
        f'--bar-size "{request.bar_size}" --what-to-show {request.what_to_show}'
    )
    try:
        loader_request = HistoricalSnapshotLoadRequest(
            symbols=request.symbols,
            bar_size=request.bar_size,
            what_to_show=request.what_to_show,
            latest=request.latest,
            strict=request.strict,
            base_data_path=request.base_data_path,
        )
        report = load_historical_snapshots(loader_request)
        paths = _write_model_report(journal, "history_load", report)
        ok = _history_load_stage_passed(report)
        partial = any(
            result.load_status != HistoricalLoadStatus.LOADED for result in report.results
        )
        return (
            _stage(
                "history_load",
                command,
                ok=ok,
                status=_completed_partial_or_failed(ok, partial),
                started_at=started_at,
                report_paths={
                    "history_load_json": paths["json"],
                    "history_load_markdown": paths["markdown"],
                },
                warnings=report.warnings,
                errors=report.errors,
            ),
            report,
        )
    except Exception as exc:
        return _exception_stage("history_load", command, started_at, exc), None


def _run_commodity_universe_stage(
    request: PaperReadinessRunRequest,
    *,
    journal: Journal,
) -> CommodityUniverseStageResult:
    started_at = utc_now()
    command = f"commodity-universe --symbols {','.join(request.commodity_symbols)}"
    try:
        report = build_commodity_research_universe_report(
            CommodityResearchUniverseRequest(symbols=request.commodity_symbols)
        )
        paths = _write_model_report(journal, "commodity_universe", report)
        return (
            _stage(
                "commodity_universe",
                command,
                ok=report.ok,
                status=_completed_partial_or_failed(report.ok, bool(report.warnings)),
                started_at=started_at,
                report_paths={
                    "commodity_universe_json": paths["json"],
                    "commodity_universe_markdown": paths["markdown"],
                },
                warnings=report.warnings,
                errors=report.errors,
            ),
            report,
        )
    except Exception as exc:
        return _exception_stage("commodity_universe", command, started_at, exc), None


def _run_signal_evaluation_stage(
    request: PaperReadinessRunRequest,
    loader_report: HistoricalLoaderReport,
    *,
    journal: Journal,
) -> SignalEvaluationStageResult:
    started_at = utc_now()
    command = (
        f"signal-evaluate --symbols {','.join(request.symbols)} "
        f'--bar-size "{request.bar_size}" --what-to-show {request.what_to_show} '
        f"--short-window {request.short_window} --long-window {request.long_window}"
    )
    try:
        evaluation_request = AnalyticalSignalEvaluationRequest(
            symbols=request.symbols,
            alignment_mode=BacktestAlignmentMode.UNION,
            requested_bar_size=request.bar_size,
            requested_what_to_show=request.what_to_show,
            latest=request.latest,
            strict=request.strict,
            base_data_path=request.base_data_path,
            short_window=request.short_window,
            long_window=request.long_window,
        )
        datasets = [
            result.dataset
            for result in loader_report.results
            if result.dataset is not None
        ]
        feed = build_backtest_feed(datasets, alignment_mode=evaluation_request.alignment_mode)
        feed = feed.model_copy(
            update={
                "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
                "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
            }
        )
        report = build_analytical_signal_evaluation_report(feed, evaluation_request)
        paths = _write_model_report(journal, "signal_evaluation", report)
        partial = report.final_status != "completed"
        return (
            _stage(
                "signal_evaluation",
                command,
                ok=report.ok,
                status=_completed_partial_or_failed(report.ok, partial),
                started_at=started_at,
                report_paths={
                    "signal_evaluation_json": paths["json"],
                    "signal_evaluation_markdown": paths["markdown"],
                },
                warnings=report.warnings,
                errors=report.errors,
            ),
            report,
        )
    except Exception as exc:
        return _exception_stage("signal_evaluation", command, started_at, exc), None


def _fetch_historical_snapshot_report(
    config: TraderConfig,
    request: PaperReadinessRunRequest,
    *,
    broker_client_factory: BrokerClientFactory,
) -> HistoricalSnapshotReport:
    report = broker_client_factory(config).request_historical_snapshots(
        request.symbols,
        duration=request.duration,
        bar_size=request.bar_size,
        what_to_show=request.what_to_show,
        use_rth=request.use_rth,
        timeout=request.history_timeout_seconds,
    )
    timestamp_slug = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stored_results = [
        write_historical_snapshot_result(
            result,
            base_dir=Path(request.base_data_path),
            timestamp_slug=timestamp_slug,
        )
        for result in report.results
    ]
    return attach_snapshot_paths(report.model_copy(update={"results": stored_results}))


def _build_run_report(
    config: TraderConfig,
    request: PaperReadinessRunRequest,
    stages: list[PaperReadinessRunStage],
    *,
    final_status: PaperReadinessRunStatus,
    warnings: list[str],
    errors: list[str],
    broker_report: BrokerDiagnosticReport | None = None,
    account_report: BrokerDiagnosticReport | None = None,
    snapshot_report: HistoricalSnapshotReport | None = None,
    readiness_report: HistoricalReadinessReport | None = None,
    loader_report: HistoricalLoaderReport | None = None,
    commodity_report: CommodityResearchUniverseReport | None = None,
    signal_report: AnalyticalSignalEvaluationReport | None = None,
) -> PaperReadinessRunReport:
    broker_connected = _broker_stage_passed(broker_report)
    account_summary_verified = _account_stage_passed(account_report)
    history_snapshot_written = bool(snapshot_report and snapshot_report.snapshot_paths)
    history_load_completed = _history_load_stage_passed(loader_report)
    commodity_universe_verified = bool(commodity_report and commodity_report.ok)
    signal_evaluation_completed = bool(signal_report and signal_report.ok)
    account_ids, account_keys = _account_summary_metadata(
        account_report.account_snapshot if account_report else None
    )
    partial_symbols = _partial_symbols(readiness_report, loader_report)
    combined_errors = _unique([*errors, *[error for stage in stages for error in stage.errors]])
    combined_warnings = _unique(
        [*warnings, *[warning for stage in stages for warning in stage.warnings]]
    )

    return PaperReadinessRunReport(
        ok=final_status != PaperReadinessRunStatus.FAILED,
        request=request,
        selected_universe=request.symbols,
        commodity_symbols=request.commodity_symbols,
        stages=stages,
        stage_statuses={
            stage.name: _status_text(stage.final_status) for stage in stages
        },
        report_paths=_flatten_report_paths(stages),
        broker_connected=broker_connected,
        account_summary_verified=account_summary_verified,
        account_summary_source=(
            "broker_read_only_account_summary"
            if account_summary_verified
            else "unavailable_or_mock_fallback_rejected"
        ),
        account_ids_masked=account_ids,
        account_summary_fields_by_account=account_keys,
        history_snapshot_written=history_snapshot_written,
        history_load_completed=history_load_completed,
        commodity_universe_verified=commodity_universe_verified,
        signal_evaluation_completed=signal_evaluation_completed,
        readiness_status_by_symbol=_readiness_status_by_symbol(readiness_report),
        load_status_by_symbol=_load_status_by_symbol(loader_report),
        partial_symbols=partial_symbols,
        warnings=combined_warnings,
        errors=combined_errors,
        configured_allow_paper_orders=config.allow_paper_orders,
        broker_contacted=any(
            stage.name in {"broker_probe", "account_summary", "history_snapshot"}
            for stage in stages
        ),
        final_status=final_status,
    )


def _stage(
    name: str,
    command: str,
    *,
    ok: bool,
    status: PaperReadinessStageStatus,
    started_at: datetime,
    report_paths: dict[str, str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> PaperReadinessRunStage:
    return PaperReadinessRunStage(
        name=name,
        command=command,
        ok=ok,
        final_status=status,
        started_at=started_at,
        finished_at=utc_now(),
        report_paths=report_paths or {},
        warnings=_unique(warnings or []),
        errors=_unique(errors or []),
    )


def _exception_stage(
    name: str,
    command: str,
    started_at: datetime,
    exc: Exception,
) -> PaperReadinessRunStage:
    return _stage(
        name,
        command,
        ok=False,
        status=PaperReadinessStageStatus.FAILED,
        started_at=started_at,
        errors=[f"{name} raised {type(exc).__name__}: {exc}"],
    )


def _completed_or_failed(ok: bool) -> PaperReadinessStageStatus:
    return (
        PaperReadinessStageStatus.COMPLETED
        if ok
        else PaperReadinessStageStatus.FAILED
    )


def _completed_partial_or_failed(
    ok: bool,
    partial: bool,
) -> PaperReadinessStageStatus:
    if not ok:
        return PaperReadinessStageStatus.FAILED
    if partial:
        return PaperReadinessStageStatus.COMPLETED_WITH_WARNINGS
    return PaperReadinessStageStatus.COMPLETED


def _write_model_report(
    journal: Journal,
    name: str,
    report: SerializableModel,
) -> dict[str, str]:
    json_path, markdown_path = journal.write_cycle(name, report.model_dump(mode="json"))
    return {"json": json_path.as_posix(), "markdown": markdown_path.as_posix()}


def _write_mapping_report(
    journal: Journal,
    name: str,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    json_path, markdown_path = journal.write_cycle(name, payload)
    return {"json": json_path.as_posix(), "markdown": markdown_path.as_posix()}


def _account_summary_payload(
    report: BrokerDiagnosticReport,
    *,
    account_summary_verified: bool,
) -> dict[str, Any]:
    account_ids, account_keys = _account_summary_metadata(report.account_snapshot)
    return {
        "title": "Read-only Broker Account Summary",
        "report_type": "account_summary",
        "command": "account --connect",
        "ok": account_summary_verified,
        "final_status": "verified" if account_summary_verified else "failed",
        "account_summary_verified": account_summary_verified,
        "account_summary_source": (
            "broker_read_only_account_summary"
            if account_summary_verified
            else "unavailable_or_mock_fallback_rejected"
        ),
        "account_ids_masked": account_ids,
        "account_summary_fields_by_account": account_keys,
        "account_snapshot": report.account_snapshot or {},
        "broker_connected": report.connected,
        "order_routing_enabled": False,
        "submitted_orders": False,
        "paper_orders_enabled": False,
        "read_only_api_expected": True,
        "no_order_guarantee": True,
        "warnings": report.warnings,
        "errors": _broker_error_messages(report.errors),
    }


def _broker_stage_passed(report: BrokerDiagnosticReport | None) -> bool:
    return bool(report and report.ok and report.connected)


def _account_stage_passed(report: BrokerDiagnosticReport | None) -> bool:
    return bool(
        report
        and report.ok
        and report.connected
        and report.account_snapshot
        and _account_summary_has_funding_tags(report.account_snapshot)
    )


def _history_snapshot_stage_passed(
    snapshot_report: HistoricalSnapshotReport | None,
    readiness_report: HistoricalReadinessReport | None,
) -> bool:
    return bool(
        snapshot_report
        and snapshot_report.ok
        and snapshot_report.snapshot_paths
        and readiness_report
        and readiness_report.ok
    )


def _history_load_stage_passed(report: HistoricalLoaderReport | None) -> bool:
    return bool(report and report.ok and report.summaries)


def _account_summary_has_funding_tags(snapshot: Mapping[str, Any]) -> bool:
    for raw_tags in snapshot.values():
        if not isinstance(raw_tags, Mapping):
            continue
        tags = cast(Mapping[str, Any], raw_tags)
        for tag in _FUNDING_TAGS:
            raw_value = tags.get(tag)
            if _summary_tag_has_value(raw_value):
                return True
    return False


def _summary_tag_has_value(raw_value: Any) -> bool:
    if raw_value is None:
        return False
    value = raw_value.get("value") if isinstance(raw_value, Mapping) else raw_value
    return str(value).strip() not in {"", "None", "nan"}


def _account_summary_metadata(
    snapshot: Mapping[str, Any] | None,
) -> tuple[list[str], dict[str, list[str]]]:
    if not snapshot:
        return [], {}
    keys_by_account: dict[str, list[str]] = {}
    for account_id, raw_tags in snapshot.items():
        if isinstance(raw_tags, Mapping):
            tags = cast(Mapping[str, Any], raw_tags)
            keys_by_account[str(account_id)] = sorted(str(tag) for tag in tags)
        else:
            keys_by_account[str(account_id)] = []
    return sorted(str(account_id) for account_id in snapshot), keys_by_account


def _readiness_has_partial_symbols(report: HistoricalReadinessReport | None) -> bool:
    return bool(
        report
        and any(
            summary.readiness_status != HistoricalReadinessStatus.READY
            for summary in report.summaries
        )
    )


def _partial_symbols(
    readiness_report: HistoricalReadinessReport | None,
    loader_report: HistoricalLoaderReport | None,
) -> list[str]:
    symbols: set[str] = set()
    if readiness_report is not None:
        for summary in readiness_report.summaries:
            if summary.readiness_status != HistoricalReadinessStatus.READY:
                symbols.add(summary.symbol)
    if loader_report is not None:
        for result in loader_report.results:
            if result.load_status != HistoricalLoadStatus.LOADED:
                symbols.add(result.symbol)
    return sorted(symbols)


def _readiness_status_by_symbol(
    report: HistoricalReadinessReport | None,
) -> dict[str, str]:
    if report is None:
        return {}
    return {
        summary.symbol: _status_text(summary.readiness_status)
        for summary in report.summaries
    }


def _load_status_by_symbol(report: HistoricalLoaderReport | None) -> dict[str, str]:
    if report is None:
        return {}
    return {
        result.symbol: _status_text(result.load_status)
        for result in report.results
    }


def _flatten_report_paths(stages: list[PaperReadinessRunStage]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for stage in stages:
        for label, path in stage.report_paths.items():
            paths[f"{stage.name}.{label}"] = path
    return paths


def _broker_error_messages(errors: list[BrokerErrorEvent]) -> list[str]:
    messages: list[str] = []
    for error in errors:
        prefix = f"IBKR {error.code}: " if error.code is not None else ""
        messages.append(prefix + error.message)
    return messages


def _status_text(value: object) -> str:
    return str(getattr(value, "value", value))


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
