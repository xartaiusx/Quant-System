"""Read-only IBKR alpha shadow orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from trader.config import PAPER_PORTS, TraderConfig, TradingMode
from trader.data.quality_gate import build_data_quality_gate_report
from trader.execution.router import ExecutionRouter
from trader.models import (
    AccountSnapshot,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaShadowRunStatus,
    AnalyticalSignalConditionState,
    AnalyticalSignalEvaluationReport,
    BrokerDiagnosticReport,
    DataQualityGateReport,
    DataQualityGateRequest,
    ExecutionResult,
    HistoricalLoadedBar,
    HistoricalLoaderReport,
    MarketQuote,
    PaperReadinessRunRequest,
    PaperReadinessRunStage,
    PaperReadinessStageStatus,
    RiskDecision,
    Signal,
    SignalDirection,
    new_campaign_id,
    utc_now,
)
from trader.paper_readiness import (
    _account_stage_passed,
    _broker_stage_config,
    _broker_stage_passed,
    _completed_partial_or_failed,
    _flatten_report_paths,
    _history_load_stage_passed,
    _history_snapshot_stage_passed,
    _pause_between_broker_stages,
    _run_account_summary_stage,
    _run_broker_probe_stage,
    _run_history_load_stage,
    _run_history_snapshot_stage,
    _run_signal_evaluation_stage,
    _stage,
    _unique,
    _write_model_report,
    default_broker_client_factory,
)
from trader.portfolio.construction import build_trade_plans
from trader.reporting.journal import Journal
from trader.risk.rules import evaluate_trade_plans

DEFAULT_ALPHA_SHADOW_SYMBOLS = ["SPY"]
_EQUITY_TAGS = ("NetLiquidation", "EquityWithLoanValue")
_CASH_TAGS = ("TotalCashValue", "CashBalance", "AvailableFunds")
_BUYING_POWER_TAGS = ("BuyingPower", "AvailableFunds", "ExcessLiquidity")


class AlphaShadowBrokerClient(Protocol):
    """Broker surface required by the alpha shadow orchestration."""

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
    ) -> Any:
        """Request read-only historical snapshots."""


BrokerClientFactory = Callable[[TraderConfig], AlphaShadowBrokerClient]


def run_alpha_shadow_run(
    config: TraderConfig,
    request: AlphaShadowRunRequest | None = None,
    *,
    journal: Journal | None = None,
    broker_client_factory: BrokerClientFactory = default_broker_client_factory,
) -> AlphaShadowRunReport:
    """Run a read-only broker-connected alpha shadow workflow."""

    alpha_request = _request_with_campaign_id(request or AlphaShadowRunRequest())
    readiness_request = _readiness_request(alpha_request)
    selected_journal = journal or Journal()
    stages: list[PaperReadinessRunStage] = []
    run_warnings = [
        "IBKR Read-Only API is expected to remain enabled for alpha-shadow-run.",
        "ALLOW_PAPER_ORDERS=false is required; paper order routing remains disabled.",
        "Shadow trade plans are routed to the simulator only.",
    ]
    run_errors = _config_errors(config)
    if run_errors:
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=run_errors,
        )

    broker_stage, broker_report = _run_broker_probe_stage(
        _broker_stage_config(config, stage_offset=0),
        readiness_request,
        journal=selected_journal,
        broker_client_factory=broker_client_factory,
    )
    stages.append(broker_stage)
    if not _broker_stage_passed(broker_report):
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=["broker probe failed"],
            broker_report=broker_report,
        )
    _pause_between_broker_stages(readiness_request)

    account_stage, account_report = _run_account_summary_stage(
        _broker_stage_config(config, stage_offset=1),
        readiness_request,
        journal=selected_journal,
        broker_client_factory=broker_client_factory,
    )
    stages.append(account_stage)
    if not _account_stage_passed(account_report):
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=["broker account summary is unavailable or lacks funding tags"],
            broker_report=broker_report,
            account_report=account_report,
        )
    _pause_between_broker_stages(readiness_request)

    snapshot_stage, snapshot_report, readiness_report = _run_history_snapshot_stage(
        _broker_stage_config(config, stage_offset=2),
        readiness_request,
        journal=selected_journal,
        broker_client_factory=broker_client_factory,
    )
    stages.append(snapshot_stage)
    if not _history_snapshot_stage_passed(snapshot_report, readiness_report):
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=["no usable SPY historical snapshot was written"],
            broker_report=broker_report,
            account_report=account_report,
        )

    load_stage, loader_report = _run_history_load_stage(
        readiness_request,
        journal=selected_journal,
    )
    stages.append(load_stage)
    if not _history_load_stage_passed(loader_report):
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=["no usable SPY historical snapshot loaded"],
            broker_report=broker_report,
            account_report=account_report,
            loader_report=loader_report,
        )
    assert loader_report is not None

    data_quality_stage, data_quality_report = _run_data_quality_stage(
        config,
        alpha_request,
        journal=selected_journal,
    )
    stages.append(data_quality_stage)
    if data_quality_report is None or not data_quality_report.ok:
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=["SPY data-quality gate failed"],
            broker_report=broker_report,
            account_report=account_report,
            loader_report=loader_report,
            data_quality_report=data_quality_report,
        )

    signal_stage, signal_report = _run_signal_evaluation_stage(
        readiness_request,
        loader_report,
        journal=selected_journal,
    )
    stages.append(signal_stage)
    if signal_report is None or not signal_report.ok:
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=["SPY signal evaluation failed"],
            broker_report=broker_report,
            account_report=account_report,
            loader_report=loader_report,
            data_quality_report=data_quality_report,
            signal_report=signal_report,
        )

    assert account_report is not None
    shadow_stage, shadow_payload = _run_shadow_simulation_stage(
        config,
        alpha_request,
        account_report,
        loader_report,
        signal_report,
    )
    stages.append(shadow_stage)
    if not shadow_stage.ok:
        return _build_alpha_report(
            config,
            alpha_request,
            stages,
            final_status=AlphaShadowRunStatus.FAILED,
            warnings=run_warnings,
            errors=["shadow risk or simulation stage failed"],
            broker_report=broker_report,
            account_report=account_report,
            loader_report=loader_report,
            data_quality_report=data_quality_report,
            signal_report=signal_report,
            shadow_payload=shadow_payload,
        )

    final_status = (
        AlphaShadowRunStatus.COMPLETED_WITH_WARNINGS
        if shadow_stage.final_status == PaperReadinessStageStatus.COMPLETED_WITH_WARNINGS
        else AlphaShadowRunStatus.COMPLETED
    )
    return _build_alpha_report(
        config,
        alpha_request,
        stages,
        final_status=final_status,
        warnings=run_warnings,
        errors=[],
        broker_report=broker_report,
        account_report=account_report,
        loader_report=loader_report,
        data_quality_report=data_quality_report,
        signal_report=signal_report,
        shadow_payload=shadow_payload,
    )


def _config_errors(config: TraderConfig) -> list[str]:
    errors: list[str] = []
    if config.ibkr_host != "127.0.0.1":
        errors.append("IBKR_HOST must be 127.0.0.1 for alpha-shadow-run")
    if config.ibkr_port not in PAPER_PORTS:
        errors.append(
            "IBKR_PORT must be 7497 (TWS paper) or 4002 (IB Gateway paper) "
            "for alpha-shadow-run"
        )
    if config.allow_paper_orders:
        errors.append("ALLOW_PAPER_ORDERS=true is not accepted for alpha-shadow-run")
    if config.allow_live_orders:
        errors.append("ALLOW_LIVE_ORDERS=true is not accepted")
    if config.trading_mode != TradingMode.PAPER:
        errors.append("TRADING_MODE must be paper for alpha-shadow-run")
    return errors


def _request_with_campaign_id(request: AlphaShadowRunRequest) -> AlphaShadowRunRequest:
    if request.campaign_id:
        return request
    return request.model_copy(update={"campaign_id": new_campaign_id()})


def _readiness_request(request: AlphaShadowRunRequest) -> PaperReadinessRunRequest:
    return PaperReadinessRunRequest(
        symbols=request.symbols,
        commodity_symbols=["GLD"],
        duration=request.duration,
        bar_size=request.bar_size,
        what_to_show=request.what_to_show,
        use_rth=request.use_rth,
        broker_timeout_seconds=request.broker_timeout_seconds,
        history_timeout_seconds=request.history_timeout_seconds,
        broker_stage_pause_seconds=request.broker_stage_pause_seconds,
        latest=request.latest,
        strict=request.strict,
        base_data_path=request.base_data_path,
        short_window=request.short_window,
        long_window=request.long_window,
    )


def _run_data_quality_stage(
    config: TraderConfig,
    request: AlphaShadowRunRequest,
    *,
    journal: Journal,
) -> tuple[PaperReadinessRunStage, DataQualityGateReport | None]:
    started_at = utc_now()
    command = (
        f"data-quality-gate --symbols {','.join(request.symbols)} "
        f'--bar-size "{request.bar_size}" --what-to-show {request.what_to_show} '
        f"--min-bars {request.min_bars} "
        f"--max-zero-volume-bars {request.max_zero_volume_bars} "
        f"--min-average-volume {request.min_average_volume} "
        f"--min-average-dollar-volume {request.min_average_dollar_volume}"
    )
    try:
        quality_request = DataQualityGateRequest(
            symbols=request.symbols,
            bar_size=request.bar_size,
            what_to_show=request.what_to_show,
            latest=request.latest,
            strict=request.strict,
            base_data_path=request.base_data_path,
            min_bars=request.min_bars,
            max_zero_volume_bars=request.max_zero_volume_bars,
            min_average_volume=request.min_average_volume,
            min_average_dollar_volume=request.min_average_dollar_volume,
        )
        report = build_data_quality_gate_report(config, quality_request)
        paths = _write_model_report(journal, "data_quality_gate", report)
        partial = report.final_status != "passed"
        return (
            _stage(
                "data_quality_gate",
                command,
                ok=report.ok,
                status=_completed_partial_or_failed(report.ok, partial),
                started_at=started_at,
                report_paths={
                    "data_quality_gate_json": paths["json"],
                    "data_quality_gate_markdown": paths["markdown"],
                },
                warnings=report.warnings,
                errors=report.errors,
            ),
            report,
        )
    except Exception as exc:
        return (
            _stage(
                "data_quality_gate",
                command,
                ok=False,
                status=PaperReadinessStageStatus.FAILED,
                started_at=started_at,
                errors=[f"data_quality_gate raised {type(exc).__name__}: {exc}"],
            ),
            None,
        )


def _run_shadow_simulation_stage(
    config: TraderConfig,
    request: AlphaShadowRunRequest,
    account_report: BrokerDiagnosticReport,
    loader_report: HistoricalLoaderReport,
    signal_report: AnalyticalSignalEvaluationReport,
) -> tuple[PaperReadinessRunStage, dict[str, Any]]:
    started_at = utc_now()
    command = "shadow-trade-plan-risk-simulate --symbols SPY --destination simulator"
    warnings: list[str] = []
    errors: list[str] = []
    signals = _shadow_signals(signal_report)
    if not signals:
        warnings.append("no shadow signal could be derived from the latest SPY observation")

    quotes, source_timestamps = _shadow_quotes(loader_report)
    account_snapshot = _account_snapshot_from_account_report(account_report)
    shadow_config = config.model_copy(
        update={
            "trading_mode": TradingMode.DRY_RUN,
            "max_trade_notional": request.max_trade_notional,
            "max_open_positions": request.max_open_positions,
            "allow_paper_orders": False,
            "allow_live_orders": False,
        }
    )
    plans = build_trade_plans(
        signals,
        quotes,
        shadow_config,
        fixed_notional=request.max_trade_notional,
    )
    decisions: list[RiskDecision] = []
    results: list[ExecutionResult] = []
    if account_snapshot is None:
        errors.append("broker account summary could not be converted into risk account view")
    if signals and not plans:
        warnings.append("shadow signal did not produce a trade plan")
    if plans and account_snapshot is not None:
        decisions = evaluate_trade_plans(plans, quotes, account_snapshot, [], shadow_config)
        approved = [decision for decision in decisions if decision.approved]
        if not approved:
            errors.append("no shadow trade plans passed risk checks")
        results = ExecutionRouter(shadow_config).route(decisions, quotes, destination="simulator")
        if approved and not any(result.fills for result in results):
            errors.append("shadow simulator did not produce a fill for approved risk decision")

    payload = {
        "shadow_signals": signals,
        "trade_plans": plans,
        "risk_decisions": decisions,
        "execution_results": results,
        "source_bar_timestamp_by_symbol": source_timestamps,
    }
    ok = not errors
    partial = bool(warnings) and ok
    return (
        _stage(
            "shadow_simulation",
            command,
            ok=ok,
            status=_completed_partial_or_failed(ok, partial),
            started_at=started_at,
            warnings=warnings,
            errors=errors,
        ),
        payload,
    )


def _shadow_signals(report: AnalyticalSignalEvaluationReport) -> list[Signal]:
    observation = _latest_spy_observation(report)
    if observation is None:
        return []
    if observation.condition_state == AnalyticalSignalConditionState.CONDITION_MET:
        direction = SignalDirection.BUY
    elif observation.condition_state == AnalyticalSignalConditionState.CONDITION_NOT_MET:
        direction = SignalDirection.HOLD
    else:
        return []
    return [
        Signal(
            symbol="SPY",
            direction=direction,
            strength=Decimal("0.50"),
            confidence=Decimal("0.50"),
            strategy="alpha_shadow_moving_average",
            reason=(
                "shadow observation "
                f"{observation.condition_name}:{observation.condition_state}"
            ),
            generated_at=observation.timestamp,
            horizon_minutes=60,
        )
    ]


def _latest_spy_observation(report: AnalyticalSignalEvaluationReport) -> Any | None:
    observations = [
        observation
        for observation in report.observations
        if observation.symbol == "SPY" and observation.data_valid
    ]
    if not observations:
        return None
    return sorted(observations, key=lambda item: (item.timestamp, item.frame_index))[-1]


def _shadow_quotes(
    loader_report: HistoricalLoaderReport,
) -> tuple[dict[str, MarketQuote], dict[str, str]]:
    quotes: dict[str, MarketQuote] = {}
    source_timestamps: dict[str, str] = {}
    for result in loader_report.results:
        if result.symbol != "SPY" or result.dataset is None or not result.dataset.bars:
            continue
        bar = result.dataset.bars[-1]
        quote = _quote_from_bar(bar)
        quotes[quote.symbol] = quote
        source_timestamps[quote.symbol] = bar.raw_timestamp or bar.timestamp.isoformat()
    return quotes, source_timestamps


def _quote_from_bar(bar: HistoricalLoadedBar) -> MarketQuote:
    spread = max(bar.close * Decimal("0.0002"), Decimal("0.01"))
    return MarketQuote(
        symbol=bar.symbol,
        bid=bar.close - spread / Decimal("2"),
        ask=bar.close + spread / Decimal("2"),
        last=bar.close,
        timestamp=utc_now(),
        source="historical_snapshot_shadow_quote",
        is_mock=True,
    )


def _account_snapshot_from_account_report(
    report: BrokerDiagnosticReport,
) -> AccountSnapshot | None:
    if not report.account_snapshot:
        return None
    for account_id, raw_tags in report.account_snapshot.items():
        if not isinstance(raw_tags, Mapping):
            continue
        tags = cast(Mapping[str, Any], raw_tags)
        equity = _first_decimal_tag(tags, _EQUITY_TAGS)
        buying_power = _first_decimal_tag(tags, _BUYING_POWER_TAGS)
        cash = _first_decimal_tag(tags, _CASH_TAGS)
        if equity is None and buying_power is not None:
            equity = buying_power
        if cash is None:
            cash = equity or buying_power
        if buying_power is None:
            buying_power = cash or equity
        if equity is None or cash is None or buying_power is None:
            continue
        return AccountSnapshot(
            account_id=str(account_id),
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            daily_pnl=Decimal("0"),
            is_mock=False,
        )
    return None


def _first_decimal_tag(tags: Mapping[str, Any], names: tuple[str, ...]) -> Decimal | None:
    for name in names:
        raw_value = tags.get(name)
        value = raw_value.get("value") if isinstance(raw_value, Mapping) else raw_value
        if value is None:
            continue
        try:
            return Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError):
            continue
    return None


def _build_alpha_report(
    config: TraderConfig,
    request: AlphaShadowRunRequest,
    stages: list[PaperReadinessRunStage],
    *,
    final_status: AlphaShadowRunStatus,
    warnings: list[str],
    errors: list[str],
    broker_report: BrokerDiagnosticReport | None = None,
    account_report: BrokerDiagnosticReport | None = None,
    loader_report: HistoricalLoaderReport | None = None,
    data_quality_report: DataQualityGateReport | None = None,
    signal_report: AnalyticalSignalEvaluationReport | None = None,
    shadow_payload: dict[str, Any] | None = None,
) -> AlphaShadowRunReport:
    shadow_payload = shadow_payload or {}
    shadow_signals = list(shadow_payload.get("shadow_signals", []))
    trade_plans = list(shadow_payload.get("trade_plans", []))
    risk_decisions = list(shadow_payload.get("risk_decisions", []))
    execution_results = list(shadow_payload.get("execution_results", []))
    combined_errors = _unique([*errors, *[error for stage in stages for error in stage.errors]])
    combined_warnings = _unique(
        [*warnings, *[warning for stage in stages for warning in stage.warnings]]
    )
    if combined_errors:
        final_status = AlphaShadowRunStatus.FAILED
    account_ids = sorted(account_report.account_snapshot or {}) if account_report else []
    return AlphaShadowRunReport(
        ok=final_status != AlphaShadowRunStatus.FAILED,
        request=request,
        campaign_id=request.campaign_id,
        selected_universe=request.symbols,
        stages=stages,
        stage_statuses={stage.name: _status_text(stage.final_status) for stage in stages},
        report_paths=_flatten_report_paths(stages),
        broker_connected=_broker_stage_passed(broker_report),
        account_summary_verified=_account_stage_passed(account_report),
        account_summary_source=(
            "broker_read_only_account_summary"
            if _account_stage_passed(account_report)
            else "unavailable_or_mock_fallback_rejected"
        ),
        account_ids_masked=account_ids,
        history_snapshot_written=any(
            stage.name == "history_snapshot" and stage.ok for stage in stages
        ),
        history_load_completed=_history_load_stage_passed(loader_report),
        data_quality_completed=bool(data_quality_report and data_quality_report.ok),
        signal_evaluation_completed=bool(signal_report and signal_report.ok),
        trade_plan_completed=bool(trade_plans) or bool(shadow_signals),
        risk_completed=bool(risk_decisions) or not trade_plans,
        simulation_completed=bool(execution_results) or not trade_plans,
        source_bar_timestamp_by_symbol=dict(
            shadow_payload.get("source_bar_timestamp_by_symbol", {})
        ),
        data_quality_status_by_symbol=_data_quality_status_by_symbol(data_quality_report),
        shadow_signals=shadow_signals,
        trade_plans=trade_plans,
        risk_decisions=risk_decisions,
        execution_results=execution_results,
        shadow_signal_count=len(shadow_signals),
        trade_plan_count=len(trade_plans),
        risk_decision_count=len(risk_decisions),
        risk_approved_count=sum(1 for decision in risk_decisions if decision.approved),
        simulation_result_count=len(execution_results),
        simulated_fill_count=sum(len(result.fills) for result in execution_results),
        warnings=combined_warnings,
        errors=combined_errors,
        configured_allow_paper_orders=config.allow_paper_orders,
        live_orders_enabled=config.allow_live_orders,
        broker_contacted=any(
            stage.name in {"broker_probe", "account_summary", "history_snapshot"}
            for stage in stages
        ),
        simulator_routed=bool(execution_results),
        generated_signals=bool(shadow_signals),
        generated_trade_plans=bool(trade_plans),
        orders_simulated=bool(execution_results),
        fills_simulated=any(result.fills for result in execution_results),
        final_status=final_status,
    )


def _data_quality_status_by_symbol(
    report: DataQualityGateReport | None,
) -> dict[str, str]:
    if report is None:
        return {}
    return {result.symbol: _status_text(result.status) for result in report.results}


def _status_text(value: object) -> str:
    return str(getattr(value, "value", value))
