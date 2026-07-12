"""Command-line interface for safe dry-run trading workflows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from trader.alpha_campaign import READ_ONLY_OFF_CONFIRMATION, run_alpha_campaign_run
from trader.alpha_paper import ALPHA_PAPER_CONFIRMATION, run_alpha_paper_run
from trader.alpha_shadow import run_alpha_shadow_run
from trader.alpha_shadow_daemon import (
    run_alpha_shadow_daemon,
    run_delayed_alpha_shadow_daemon,
)
from trader.alpha_shadow_daemon_summary import run_alpha_shadow_daemon_summary
from trader.alpha_summary import run_alpha_test_summary
from trader.backtest.data_adapter import build_backtest_feed, build_backtest_feed_report
from trader.backtest.engine import build_backtest_run_report
from trader.backtest.research import build_research_backtest_report
from trader.backtest.walk_forward import (
    build_research_walk_forward_report,
    parse_research_candidates,
)
from trader.config import ConfigError, TraderConfig, load_config
from trader.data.commodity_universe import build_commodity_research_universe_report
from trader.data.historical import (
    attach_snapshot_paths,
    build_readiness_report,
    write_historical_snapshot_result,
)
from trader.data.historical_loader import (
    build_history_index_report,
    load_historical_snapshots,
)
from trader.data.ibkr_data_diagnostics import build_ibkr_data_diagnostics_report
from trader.data.quality_gate import build_data_quality_gate_report
from trader.data.snapshots import deterministic_history, deterministic_quotes, mock_positions
from trader.data.universe import parse_symbols
from trader.execution.paper_order_smoke import run_paper_order_smoke
from trader.execution.router import ExecutionRouter
from trader.models import (
    AlphaCampaignRunMode,
    AlphaCampaignRunReport,
    AlphaCampaignRunRequest,
    AlphaPaperRunReport,
    AlphaPaperRunRequest,
    AlphaShadowDaemonReport,
    AlphaShadowDaemonReportEvidence,
    AlphaShadowDaemonRequest,
    AlphaShadowDaemonSummaryReport,
    AlphaShadowDaemonSummaryRequest,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaTestSummaryReport,
    AlphaTestSummaryRequest,
    AnalyticalSignalEvaluationReport,
    AnalyticalSignalEvaluationRequest,
    BacktestAlignmentMode,
    BacktestDataAdapterReport,
    BacktestDataAdapterRequest,
    BacktestRunReport,
    BacktestRunRequest,
    BrokerDiagnosticReport,
    CommodityResearchUniverseReport,
    CommodityResearchUniverseRequest,
    DataQualityGateReport,
    DataQualityGateRequest,
    DisabledSignalRunnerReport,
    DisabledSignalRunnerRequest,
    EvaluatorComparisonReport,
    EvaluatorComparisonRequest,
    HistoricalLoaderReport,
    HistoricalReadinessReport,
    HistoricalSnapshotLoadRequest,
    HistoricalSnapshotReport,
    IBKRDataDiagnosticsReport,
    IBKRDataDiagnosticsRequest,
    InertStrategyRunnerReport,
    InertStrategyRunnerRequest,
    MarketDataDiagnosticReport,
    MarketDataRequestType,
    MarketQuote,
    PaperLedgerUpdateReport,
    PaperLedgerUpdateRequest,
    PaperOrderSmokeReport,
    PaperOrderSmokeRequest,
    PaperReadinessRunReport,
    PaperReadinessRunRequest,
    PaperReconcileReport,
    PaperReconcileRequest,
    ResearchBacktestReport,
    ResearchBacktestRequest,
    ResearchDataAuditReport,
    ResearchDataAuditRequest,
    ResearchDataIngestReport,
    ResearchDataIngestRequest,
    ResearchWalkForwardReport,
    ResearchWalkForwardRequest,
    RiskDecision,
    ShadowDataPolicy,
    SignalContractReport,
    SignalContractValidationRequest,
    StrategyContractReport,
    StrategyContractValidationRequest,
)
from trader.paper_ledger import run_paper_ledger_update
from trader.paper_readiness import run_paper_readiness_run
from trader.paper_reconcile import run_paper_reconcile
from trader.portfolio.construction import build_trade_plans
from trader.reporting.journal import Journal
from trader.risk.rules import evaluate_trade_plans
from trader.strategy import get_strategy
from trader.strategy.evaluator_comparison import (
    build_evaluator_comparison_report,
    parse_window_candidates,
)
from trader.strategy.interface import build_strategy_contract_report
from trader.strategy.runner import build_inert_strategy_runner_report
from trader.strategy.signal_evaluation import build_analytical_signal_evaluation_report
from trader.strategy.signal_runner import build_disabled_signal_runner_report
from trader.strategy.signals import build_signal_contract_report

app = typer.Typer(
    help=(
        "Safety-first IBKR quantitative trading foundation. Live orders are refused; "
        "paper orders require explicit gated commands."
    ),
    no_args_is_help=True,
)
console = Console()

AccountClient: Any = None
IBKRClient: Any = None


def _ibkr_client(config: TraderConfig) -> Any:
    """Create the IBKR client lazily so offline commands do not import broker code."""

    global IBKRClient
    if IBKRClient is None:
        from trader.broker.ibkr_client import IBKRClient as ImportedIBKRClient

        IBKRClient = ImportedIBKRClient
    return IBKRClient(config)


def _account_client(config: TraderConfig) -> Any:
    """Create the account client lazily so offline commands stay broker-free."""

    global AccountClient
    if AccountClient is None:
        from trader.broker.account import AccountClient as ImportedAccountClient

        AccountClient = ImportedAccountClient
    return AccountClient(config)


@app.command()
def preflight(
    connect: Annotated[
        bool,
        typer.Option(
            "--connect/--no-connect",
            help="Attempt a harmless read-only current-time broker probe.",
        ),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Override IBKR connect/request timeout seconds."),
    ] = None,
) -> None:
    """Show fail-closed config and optional read-only broker diagnostics."""

    config = _load_config_or_exit()
    timeout = _validate_timeout_option(timeout)
    result = _ibkr_client(config).preflight(attempt_connection=connect, timeout=timeout)
    console.print("[bold]Broker preflight[/bold]")
    console.print("Config: passed.")
    console.print(f"Connection probe: {'attempted' if connect else 'skipped'}.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print_json(data={"config": config.safe_summary(), "broker": _report_dict(result)})
    if connect and not result.ok:
        raise typer.Exit(code=1)


@app.command()
def broker_probe(
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Override IBKR connect/request timeout seconds."),
    ] = None,
) -> None:
    """Run a read-only TWS / IB Gateway current-time and account discovery probe."""

    config = _load_config_or_exit()
    timeout = _validate_timeout_option(timeout)
    report = _ibkr_client(config).diagnostic_report(timeout=timeout)
    json_path, md_path = Journal().write_cycle("broker_probe", _report_dict(report))

    console.print("[bold]Read-only broker probe[/bold]")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_broker_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("market-probe")
def market_probe(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to probe through IBKR read-only data APIs."),
    ] = "SPY,AAPL",
    data_type: Annotated[
        MarketDataRequestType,
        typer.Option("--data-type", help="IBKR market data type to request."),
    ] = MarketDataRequestType.DELAYED,
    historical: Annotated[
        bool,
        typer.Option(
            "--historical/--no-historical",
            help="Request a small read-only historical bar sample after quote diagnostics.",
        ),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Override IBKR connect/request timeout seconds."),
    ] = None,
) -> None:
    """Run read-only IBKR market-data diagnostics."""

    config = _load_config_or_exit()
    timeout = _validate_timeout_option(timeout)
    selected_symbols = parse_symbols(symbols)
    report = _ibkr_client(config).market_data_diagnostic(
        selected_symbols,
        market_data_type=data_type,
        include_historical=historical,
        timeout=timeout,
    )
    json_path, md_path = Journal().write_cycle("market_probe", _report_dict(report))

    console.print("[bold]Read-only market-data probe[/bold]")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_market_data_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("history-fetch")
def history_fetch(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to fetch bounded historical bars for."),
    ] = "SPY,AAPL",
    duration: Annotated[
        str,
        typer.Option("--duration", help="IBKR historical duration string."),
    ] = "1 D",
    bar_size: Annotated[
        str,
        typer.Option("--bar-size", help="IBKR historical bar size."),
    ] = "5 mins",
    what_to_show: Annotated[
        str,
        typer.Option("--what-to-show", help="IBKR historical data type."),
    ] = "TRADES",
    use_rth: Annotated[
        int,
        typer.Option("--use-rth", help="Use regular trading hours: 1 or 0."),
    ] = 1,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Override IBKR connect/request timeout seconds."),
    ] = 30,
) -> None:
    """Fetch and store read-only IBKR historical snapshots."""

    config = _load_config_or_exit()
    validated_timeout = _validate_timeout_option(timeout)
    request_timeout = validated_timeout if validated_timeout is not None else 30
    use_rth = _validate_use_rth_option(use_rth)
    selected_symbols = parse_symbols(symbols)
    report = _fetch_historical_snapshot_report(
        config,
        selected_symbols,
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=use_rth,
        timeout=request_timeout,
    )
    json_path, md_path = Journal().write_cycle("history_snapshot", _report_dict(report))

    console.print("[bold]Read-only historical snapshot fetch[/bold]")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_history_snapshot_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("history-readiness")
def history_readiness(
    latest: Annotated[
        bool,
        typer.Option("--latest/--no-latest", help="Validate the latest stored snapshots."),
    ] = True,
) -> None:
    """Validate local historical snapshots without opening a broker socket."""

    config = _load_config_or_exit()
    if not latest:
        console.print("[red]Only --latest readiness is implemented for this milestone.[/red]")
        raise typer.Exit(code=2)
    report = build_readiness_report(config, latest=True)
    json_path, md_path = Journal().write_cycle("history_readiness", _report_dict(report))

    console.print("[bold]Historical snapshot readiness[/bold]")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_history_readiness_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("ibkr-data-diagnostics")
def ibkr_data_diagnostics(
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Symbol to diagnose. Only SPY is allowed."),
    ] = "SPY",
    broker_probe_report: Annotated[
        Path,
        typer.Option("--broker-probe-report", help="Ignored local broker-probe JSON path."),
    ] = Path("reports/latest_broker_probe.json"),
    history_snapshot_report: Annotated[
        Path,
        typer.Option(
            "--history-snapshot-report",
            help="Ignored local history-snapshot JSON path.",
        ),
    ] = Path("reports/latest_history_snapshot.json"),
    history_readiness_report: Annotated[
        Path,
        typer.Option(
            "--history-readiness-report",
            help="Ignored local history-readiness JSON path.",
        ),
    ] = Path("reports/latest_history_readiness.json"),
    market_probe_report: Annotated[
        Path | None,
        typer.Option(
            "--market-probe-report",
            help="Optional ignored local market-probe JSON path.",
        ),
    ] = Path("reports/latest_market_probe.json"),
    min_bars: Annotated[
        int,
        typer.Option("--min-bars", help="Minimum bars required for strict shadow."),
    ] = 50,
    stale_after_minutes: Annotated[
        int,
        typer.Option(
            "--stale-after-minutes",
            help="Maximum latest-bar age for strict shadow.",
        ),
    ] = 15,
) -> None:
    """Diagnose strict SPY data freshness from ignored local reports only."""

    request = IBKRDataDiagnosticsRequest(
        symbol=symbol,
        broker_probe_report_path=broker_probe_report.as_posix(),
        history_snapshot_report_path=history_snapshot_report.as_posix(),
        history_readiness_report_path=history_readiness_report.as_posix(),
        market_probe_report_path=(
            market_probe_report.as_posix() if market_probe_report is not None else None
        ),
        min_bars=min_bars,
        stale_after_minutes=stale_after_minutes,
    )
    report = build_ibkr_data_diagnostics_report(request)
    json_path, md_path = Journal().write_cycle(
        "ibkr_data_diagnostics",
        _report_dict(report),
    )

    console.print("[bold]IBKR data freshness diagnostics[/bold]")
    console.print("Offline report comparison only; no broker contact.")
    console.print("Order routing: disabled.")
    console.print("Submitted orders: false.")
    _print_ibkr_data_diagnostics_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("ibkr-delayed-data-diagnostics")
def ibkr_delayed_data_diagnostics(
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Symbol to diagnose. Only SPY is allowed."),
    ] = "SPY",
    broker_probe_report: Annotated[
        Path,
        typer.Option("--broker-probe-report", help="Ignored local broker-probe JSON path."),
    ] = Path("reports/latest_broker_probe.json"),
    history_snapshot_report: Annotated[
        Path,
        typer.Option(
            "--history-snapshot-report",
            help="Ignored local history-snapshot JSON path.",
        ),
    ] = Path("reports/latest_history_snapshot.json"),
    history_readiness_report: Annotated[
        Path,
        typer.Option(
            "--history-readiness-report",
            help="Ignored local history-readiness JSON path.",
        ),
    ] = Path("reports/latest_history_readiness.json"),
    market_probe_report: Annotated[
        Path,
        typer.Option(
            "--market-probe-report",
            help="Ignored delayed market-probe JSON path.",
        ),
    ] = Path("reports/latest_market_probe.json"),
    min_bars: Annotated[
        int,
        typer.Option("--min-bars", help="Minimum bars required for delayed shadow."),
    ] = 50,
    stale_after_minutes: Annotated[
        int,
        typer.Option(
            "--stale-after-minutes",
            help="Maximum latest-bar age for delayed engineering shadow.",
        ),
    ] = 30,
) -> None:
    """Diagnose SPY delayed-data engineering readiness without graduation."""

    request = IBKRDataDiagnosticsRequest(
        symbol=symbol,
        data_policy=ShadowDataPolicy.DELAYED_ENGINEERING,
        broker_probe_report_path=broker_probe_report.as_posix(),
        history_snapshot_report_path=history_snapshot_report.as_posix(),
        history_readiness_report_path=history_readiness_report.as_posix(),
        market_probe_report_path=market_probe_report.as_posix(),
        min_bars=min_bars,
        stale_after_minutes=stale_after_minutes,
    )
    report = build_ibkr_data_diagnostics_report(request)
    json_path, md_path = Journal().write_cycle(
        "ibkr_delayed_data_diagnostics",
        _report_dict(report),
    )

    console.print("[bold]IBKR delayed-data engineering diagnostics[/bold]")
    console.print("Offline report comparison only; no broker contact.")
    console.print("Delayed evidence is non-graduating and cannot unlock paper execution.")
    console.print("Order routing: disabled.")
    console.print("Submitted orders: false.")
    _print_ibkr_data_diagnostics_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("commodity-universe")
def commodity_universe(
    symbols: Annotated[
        str | None,
        typer.Option(help="Optional comma-separated commodity proxy symbols."),
    ] = None,
) -> None:
    """List broker-free commodity-linked security proxies for research."""

    request = CommodityResearchUniverseRequest(
        symbols=parse_symbols(symbols) if symbols else []
    )
    report = build_commodity_research_universe_report(request)
    json_path, md_path = Journal().write_cycle("commodity_universe", _report_dict(report))

    console.print("[bold]Broker-free commodity research universe[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("Direct futures contracts: disabled.")
    console.print("Signal evaluation: disabled.")
    _print_commodity_universe_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("history-index")
def history_index(
    symbols: Annotated[
        str | None,
        typer.Option(help="Optional comma-separated symbols to index."),
    ] = None,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Index local historical snapshots without importing broker clients."""

    selected_symbols = _parse_optional_symbols(symbols)
    report = build_history_index_report(
        base_dir=base_path,
        symbols=selected_symbols,
        bar_size=bar_size,
        what_to_show=what_to_show,
        snapshot_timestamp=snapshot_timestamp,
    )
    json_path, md_path = Journal().write_cycle("history_index", _report_dict(report))

    console.print("[bold]Offline historical snapshot index[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_history_index_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("history-load")
def history_load(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to load from local snapshots."),
    ] = "SPY,AAPL",
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Load local historical snapshots into normalized offline datasets."""

    request = HistoricalSnapshotLoadRequest(
        symbols=parse_symbols(symbols),
        bar_size=bar_size,
        what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    report = load_historical_snapshots(request)
    json_path, md_path = Journal().write_cycle("history_load", _report_dict(report))

    console.print("[bold]Offline historical snapshot load[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_history_load_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("data-quality-gate")
def data_quality_gate(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to validate from local snapshots."),
    ] = "SPY,AAPL,GLD,USO,DBA",
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = "5 mins",
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = "TRADES",
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
    min_bars: Annotated[
        int,
        typer.Option("--min-bars", help="Minimum loaded bars required per symbol."),
    ] = 50,
    max_zero_volume_bars: Annotated[
        int,
        typer.Option("--max-zero-volume-bars", help="Maximum zero-volume bars allowed."),
    ] = 0,
    min_average_volume: Annotated[
        str,
        typer.Option("--min-average-volume", help="Minimum average volume per bar."),
    ] = "0",
    min_average_dollar_volume: Annotated[
        str,
        typer.Option(
            "--min-average-dollar-volume",
            help="Minimum average dollar volume per bar.",
        ),
    ] = "0",
    max_missing_gap_count: Annotated[
        int,
        typer.Option("--max-missing-gap-count", help="Maximum timestamp gaps allowed."),
    ] = 0,
    allow_stale_snapshot: Annotated[
        bool,
        typer.Option("--allow-stale-snapshot/--reject-stale-snapshot"),
    ] = False,
) -> None:
    """Run broker-free data-quality gates over local historical snapshots."""

    config = _load_config_or_exit()
    request = DataQualityGateRequest(
        symbols=parse_symbols(symbols),
        bar_size=bar_size,
        what_to_show=what_to_show,
        base_data_path=base_path.as_posix(),
        min_bars=min_bars,
        max_zero_volume_bars=max_zero_volume_bars,
        min_average_volume=_parse_decimal_option(
            min_average_volume, "--min-average-volume"
        ),
        min_average_dollar_volume=_parse_decimal_option(
            min_average_dollar_volume, "--min-average-dollar-volume"
        ),
        max_missing_gap_count=max_missing_gap_count,
        allow_stale_snapshot=allow_stale_snapshot,
    )
    report = build_data_quality_gate_report(config, request)
    json_path, md_path = Journal().write_cycle("data_quality_gate", _report_dict(report))

    console.print("[bold]Broker-free data quality gate[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_data_quality_gate_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("history-inspect")
def history_inspect(
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Symbol to inspect from local snapshots."),
    ],
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Inspect one local historical snapshot dataset offline."""

    selected = parse_symbols([symbol])
    request = HistoricalSnapshotLoadRequest(
        symbols=selected,
        bar_size=bar_size,
        what_to_show=what_to_show,
        latest=True,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    report = load_historical_snapshots(request).model_copy(
        update={"command": "history-inspect"}
    )
    json_path, md_path = Journal().write_cycle("history_load", _report_dict(report))

    console.print("[bold]Offline historical snapshot inspect[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_history_load_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("backtest-feed")
def backtest_feed(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to adapt from local snapshots."),
    ] = "SPY,AAPL",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Build a broker-free aligned bar feed from local historical snapshots."""

    request = BacktestDataAdapterRequest(
        symbols=parse_symbols(symbols),
        bar_size=bar_size,
        what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
        alignment_mode=alignment,
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.bar_size,
        what_to_show=request.what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    report = build_backtest_feed_report(loader_report, request)
    json_path, md_path = Journal().write_cycle("backtest_feed", _report_dict(report))

    console.print("[bold]Broker-free backtest data feed[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("No strategy evaluation, order simulation, or P&L calculation was performed.")
    _print_backtest_feed_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("backtest-run")
def backtest_run(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to replay from local snapshots."),
    ] = "SPY,AAPL",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Replay a broker-free backtest data feed and write diagnostics."""

    request = BacktestRunRequest(
        symbols=parse_symbols(symbols),
        alignment_mode=alignment,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_backtest_run_report(feed, request)
    json_path, md_path = Journal().write_cycle("backtest_run", _report_dict(report))

    console.print("[bold]Broker-free backtest run[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("This run replayed data frames only.")
    console.print(
        "No strategy evaluation, order simulation, broker routing, or "
        "P&L calculation was performed."
    )
    _print_backtest_run_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("research-data-ingest")
def research_data_ingest(
    source_file: Annotated[
        Path,
        typer.Option("--source-file", help="Licensed Massive minute aggregate CSV or CSV.gz."),
    ],
    root: Annotated[
        Path,
        typer.Option("--root", help="External immutable research-data store root."),
    ] = Path("D:/MarketData/Quant-System"),
    symbol: Annotated[str, typer.Option(help="Research symbol; SPY only.")] = "SPY",
) -> None:
    """Archive and ingest one Massive SPY minute-aggregate flat file offline."""

    try:
        from trader.data.research_store import ingest_massive_minute_file
    except ImportError as exc:
        console.print(
            "[red]Research dependencies unavailable.[/red] "
            "Install the project with `.[research]`."
        )
        raise typer.Exit(code=2) from exc

    request = ResearchDataIngestRequest(
        source_path=source_file.as_posix(),
        root_path=root.as_posix(),
        symbol=symbol,
    )
    report = ingest_massive_minute_file(request)
    json_path, md_path = Journal().write_cycle("research_data_ingest", _report_dict(report))

    console.print("[bold]SPY immutable research-data ingestion[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("Submitted orders: false.")
    console.print(f"Rows selected: {report.rth_rows_selected}")
    console.print(f"Active partitions written: {len(report.partitions)}")
    console.print(f"Final status: {report.final_status}")
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("research-data-audit")
def research_data_audit(
    root: Annotated[
        Path,
        typer.Option("--root", help="External immutable research-data store root."),
    ] = Path("D:/MarketData/Quant-System"),
    symbol: Annotated[str, typer.Option(help="Research symbol; SPY only.")] = "SPY",
) -> None:
    """Audit active SPY Parquet partitions and lineage without contacting a broker."""

    try:
        from trader.data.research_store import audit_research_data_store
    except ImportError as exc:
        console.print(
            "[red]Research dependencies unavailable.[/red] "
            "Install the project with `.[research]`."
        )
        raise typer.Exit(code=2) from exc

    request = ResearchDataAuditRequest(root_path=root.as_posix(), symbol=symbol)
    report = audit_research_data_store(request)
    json_path, md_path = Journal().write_cycle("research_data_audit", _report_dict(report))

    console.print("[bold]SPY research-data store audit[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print(f"Active sessions: {report.active_session_count}")
    console.print(f"Active rows: {report.total_row_count}")
    console.print(f"Final status: {report.final_status}")
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("research-backtest")
def research_backtest(
    symbol: Annotated[str, typer.Option(help="Execution research symbol; SPY only.")] = "SPY",
    short_window: Annotated[int, typer.Option(help="Fast moving-average window.")] = 5,
    long_window: Annotated[int, typer.Option(help="Slow moving-average window.")] = 20,
    quantity: Annotated[int, typer.Option(help="Fixed integer simulated quantity.")] = 1,
    starting_cash: Annotated[str, typer.Option(help="Starting simulated cash.")] = "100000",
    spread_bps: Annotated[str, typer.Option(help="Modeled full spread in basis points.")] = "2",
    slippage_bps: Annotated[
        str,
        typer.Option(help="Modeled slippage per fill side in basis points."),
    ] = "1",
    commission_per_share: Annotated[
        str,
        typer.Option(help="Modeled per-share commission."),
    ] = "0.005",
    minimum_commission: Annotated[
        str,
        typer.Option(help="Modeled minimum commission per fill."),
    ] = "1.00",
    force_close_at_end: Annotated[
        bool,
        typer.Option("--force-close-at-end/--leave-open", help="Liquidate at final close."),
    ] = True,
    bar_size: Annotated[str | None, typer.Option("--bar-size")] = "5 mins",
    what_to_show: Annotated[str | None, typer.Option("--what-to-show")] = "TRADES",
    latest: Annotated[bool, typer.Option("--latest/--all")] = True,
    strict: Annotated[bool, typer.Option("--strict/--non-strict")] = True,
    snapshot_timestamp: Annotated[str | None, typer.Option("--snapshot-timestamp")] = None,
    base_path: Annotated[Path, typer.Option("--base-path")] = Path("data/historical"),
) -> None:
    """Run a cost-aware, broker-free SPY research simulation."""

    request = ResearchBacktestRequest(
        symbol=symbol,
        short_window=short_window,
        long_window=long_window,
        quantity=quantity,
        starting_cash=_parse_decimal_option(starting_cash, "--starting-cash"),
        spread_bps=_parse_decimal_option(spread_bps, "--spread-bps"),
        slippage_bps=_parse_decimal_option(slippage_bps, "--slippage-bps"),
        commission_per_share=_parse_decimal_option(
            commission_per_share,
            "--commission-per-share",
        ),
        minimum_commission=_parse_decimal_option(
            minimum_commission,
            "--minimum-commission",
        ),
        force_close_at_end=force_close_at_end,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=[request.symbol],
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [result.dataset for result in loader_report.results if result.dataset is not None]
    feed = build_backtest_feed(datasets, alignment_mode=BacktestAlignmentMode.INTERSECTION)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_research_backtest_report(feed, request)
    json_path, md_path = Journal().write_cycle("research_backtest", _report_dict(report))

    console.print("[bold]SPY broker-free research backtest[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("Submitted orders: false.")
    console.print("Promotion eligible: false.")
    _print_research_backtest_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("research-walk-forward")
def research_walk_forward(
    symbol: Annotated[str, typer.Option(help="Execution research symbol; SPY only.")] = "SPY",
    window_pairs: Annotated[
        str,
        typer.Option(
            "--window-pairs",
            help="Predeclared comma-separated short:long candidate grid.",
        ),
    ] = "5:20,10:30,20:50",
    fold_count: Annotated[int, typer.Option(help="Anchored validation fold count.")] = 3,
    minimum_train_bars: Annotated[
        int,
        typer.Option(help="Minimum bars in the first anchored training segment."),
    ] = 500,
    validation_bars: Annotated[
        int,
        typer.Option(help="Bars in each non-overlapping next-period validation segment."),
    ] = 100,
    holdout_bars: Annotated[
        int,
        typer.Option(help="Final bars reserved from all parameter selection."),
    ] = 200,
    minimum_closed_trades: Annotated[
        int,
        typer.Option(help="Minimum closed trades required for candidate eligibility."),
    ] = 1,
    drawdown_penalty: Annotated[
        str,
        typer.Option(help="Drawdown penalty in the deterministic selection score."),
    ] = "1",
    quantity: Annotated[int, typer.Option(help="Fixed integer simulated quantity.")] = 1,
    starting_cash: Annotated[str, typer.Option(help="Starting simulated cash.")] = "100000",
    spread_bps: Annotated[str, typer.Option(help="Modeled full spread in basis points.")] = "2",
    slippage_bps: Annotated[
        str,
        typer.Option(help="Modeled slippage per fill side in basis points."),
    ] = "1",
    commission_per_share: Annotated[
        str,
        typer.Option(help="Modeled per-share commission."),
    ] = "0.005",
    minimum_commission: Annotated[
        str,
        typer.Option(help="Modeled minimum commission per fill."),
    ] = "1.00",
    bar_size: Annotated[str | None, typer.Option("--bar-size")] = "5 mins",
    what_to_show: Annotated[str | None, typer.Option("--what-to-show")] = "TRADES",
    latest: Annotated[bool, typer.Option("--latest/--all")] = True,
    strict: Annotated[bool, typer.Option("--strict/--non-strict")] = True,
    snapshot_timestamp: Annotated[str | None, typer.Option("--snapshot-timestamp")] = None,
    base_path: Annotated[Path, typer.Option("--base-path")] = Path("data/historical"),
) -> None:
    """Run broker-free SPY walk-forward selection and one sealed holdout."""

    try:
        candidates = parse_research_candidates(window_pairs)
    except (TypeError, ValueError) as exc:
        console.print(f"[red]Invalid --window-pairs:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    request = ResearchWalkForwardRequest(
        symbol=symbol,
        candidates=candidates,
        fold_count=fold_count,
        minimum_train_bars=minimum_train_bars,
        validation_bars=validation_bars,
        holdout_bars=holdout_bars,
        minimum_closed_trades=minimum_closed_trades,
        drawdown_penalty=_parse_decimal_option(drawdown_penalty, "--drawdown-penalty"),
        quantity=quantity,
        starting_cash=_parse_decimal_option(starting_cash, "--starting-cash"),
        spread_bps=_parse_decimal_option(spread_bps, "--spread-bps"),
        slippage_bps=_parse_decimal_option(slippage_bps, "--slippage-bps"),
        commission_per_share=_parse_decimal_option(
            commission_per_share,
            "--commission-per-share",
        ),
        minimum_commission=_parse_decimal_option(
            minimum_commission,
            "--minimum-commission",
        ),
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=[request.symbol],
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [result.dataset for result in loader_report.results if result.dataset is not None]
    feed = build_backtest_feed(datasets, alignment_mode=BacktestAlignmentMode.INTERSECTION)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_research_walk_forward_report(feed, request)
    json_path, md_path = Journal().write_cycle("research_walk_forward", _report_dict(report))

    console.print("[bold]SPY walk-forward and sealed-holdout research[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("Submitted orders: false.")
    console.print("Promotion eligible: false.")
    _print_research_walk_forward_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("strategy-contract")
def strategy_contract(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to validate against local snapshots."),
    ] = "SPY,AAPL",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Validate the broker-free strategy interface contract."""

    request = StrategyContractValidationRequest(
        symbols=parse_symbols(symbols),
        alignment_mode=alignment,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_strategy_contract_report(feed, request)
    json_path, md_path = Journal().write_cycle("strategy_contract", _report_dict(report))

    console.print("[bold]Broker-free strategy contract[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("This command validates the strategy interface contract only.")
    console.print(
        "No real strategy evaluation, signal generation, order simulation, "
        "broker routing, or P&L calculation was performed."
    )
    _print_strategy_contract_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("strategy-runner")
def strategy_runner(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to replay through no-op diagnostics."),
    ] = "SPY,AAPL",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Run inert no-op strategy diagnostics over a broker-free feed."""

    request = InertStrategyRunnerRequest(
        symbols=parse_symbols(symbols),
        alignment_mode=alignment,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_inert_strategy_runner_report(feed, request)
    json_path, md_path = Journal().write_cycle("strategy_runner", _report_dict(report))

    console.print("[bold]Broker-free inert strategy runner[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("Diagnostic-only no-op strategy contract path.")
    console.print(
        "No real strategy evaluation, signal generation, order simulation, fill "
        "simulation, broker routing, portfolio accounting, or P&L calculation "
        "was performed."
    )
    _print_strategy_runner_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("signal-contract")
def signal_contract(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to validate against local snapshots."),
    ] = "SPY,AAPL",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Validate the disabled broker-free signal contract."""

    request = SignalContractValidationRequest(
        symbols=parse_symbols(symbols),
        alignment_mode=alignment,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_signal_contract_report(feed, request)
    json_path, md_path = Journal().write_cycle("signal_contract", _report_dict(report))

    console.print("[bold]Broker-free signal contract[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("This command validates the signal contract only.")
    console.print(
        "Signal evaluation is disabled; no trading signals, order intents, order "
        "simulation, fill simulation, broker routing, portfolio accounting, or "
        "P&L calculation was performed."
    )
    _print_signal_contract_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("signal-runner")
def signal_runner(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to replay through disabled signal diagnostics."),
    ] = "SPY,AAPL",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
) -> None:
    """Run disabled signal diagnostics over a broker-free feed."""

    request = DisabledSignalRunnerRequest(
        symbols=parse_symbols(symbols),
        alignment_mode=alignment,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_disabled_signal_runner_report(feed, request)
    json_path, md_path = Journal().write_cycle("signal_runner", _report_dict(report))

    console.print("[bold]Broker-free disabled signal runner[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("Disabled signal runner: true.")
    console.print(
        "This run exercised the disabled signal contract only. Signal evaluation "
        "is disabled."
    )
    console.print(
        "No trading signals, order intents, order simulation, fill simulation, "
        "broker routing, portfolio accounting, or P&L calculation was performed."
    )
    _print_signal_runner_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("signal-evaluate")
def signal_evaluate(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to evaluate against local snapshots."),
    ] = "SPY,AAPL",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = None,
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest/--all", help="Load latest matching snapshot per symbol."),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option("--strict/--non-strict", help="Fail on malformed records."),
    ] = False,
    snapshot_timestamp: Annotated[
        str | None,
        typer.Option("--snapshot-timestamp", help="Optional YYYYMMDDTHHMMSSZ filter."),
    ] = None,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
    short_window: Annotated[
        int,
        typer.Option("--short-window", help="Fast moving-average lookback."),
    ] = 5,
    long_window: Annotated[
        int,
        typer.Option("--long-window", help="Slow moving-average lookback."),
    ] = 20,
) -> None:
    """Run broker-free analytical signal evaluation over local historical data."""

    request = AnalyticalSignalEvaluationRequest(
        symbols=parse_symbols(symbols),
        alignment_mode=alignment,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        latest=latest,
        strict=strict,
        snapshot_timestamp=snapshot_timestamp,
        base_data_path=base_path.as_posix(),
        short_window=short_window,
        long_window=long_window,
    )
    loader_request = HistoricalSnapshotLoadRequest(
        symbols=request.symbols,
        bar_size=request.requested_bar_size,
        what_to_show=request.requested_what_to_show,
        latest=request.latest,
        strict=request.strict,
        snapshot_timestamp=request.snapshot_timestamp,
        base_data_path=request.base_data_path,
    )
    loader_report = load_historical_snapshots(loader_request)
    datasets = [
        result.dataset
        for result in loader_report.results
        if result.dataset is not None
    ]
    feed = build_backtest_feed(datasets, alignment_mode=request.alignment_mode)
    feed = feed.model_copy(
        update={
            "warnings": list(dict.fromkeys([*feed.warnings, *loader_report.warnings])),
            "errors": list(dict.fromkeys([*feed.errors, *loader_report.errors])),
        }
    )
    report = build_analytical_signal_evaluation_report(feed, request)
    json_path, md_path = Journal().write_cycle("signal_evaluation", _report_dict(report))

    console.print("[bold]Broker-free analytical signal evaluation[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("Signal evaluation enabled: true.")
    console.print("Observations are diagnostic-only and non-actionable.")
    console.print(
        "No trading signals, order intents, order simulation, fill simulation, "
        "broker routing, portfolio accounting, or P&L calculation was performed."
    )
    _print_signal_evaluation_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("evaluator-compare")
def evaluator_compare(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to compare against local snapshots."),
    ] = "SPY,AAPL,GLD,USO,DBA",
    window_pairs: Annotated[
        str,
        typer.Option(
            "--window-pairs",
            help="Comma-separated short:long moving-average windows.",
        ),
    ] = "5:20,10:30",
    alignment: Annotated[
        BacktestAlignmentMode,
        typer.Option("--alignment", help="Timestamp alignment mode."),
    ] = BacktestAlignmentMode.UNION,
    bar_size: Annotated[
        str | None,
        typer.Option("--bar-size", help="Optional bar-size filter."),
    ] = "5 mins",
    what_to_show: Annotated[
        str | None,
        typer.Option("--what-to-show", help="Optional data-type filter."),
    ] = "TRADES",
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
    train_fraction: Annotated[
        float,
        typer.Option("--train-fraction", help="Chronological train segment fraction."),
    ] = 0.7,
) -> None:
    """Compare broker-free analytical evaluator diagnostics over local data."""

    try:
        candidates = parse_window_candidates(window_pairs)
    except ValueError as exc:
        console.print(f"[red]Invalid --window-pairs:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    request = EvaluatorComparisonRequest(
        symbols=parse_symbols(symbols),
        candidates=candidates,
        alignment_mode=alignment,
        requested_bar_size=bar_size,
        requested_what_to_show=what_to_show,
        base_data_path=base_path.as_posix(),
        train_fraction=train_fraction,
    )
    report = build_evaluator_comparison_report(request)
    json_path, md_path = Journal().write_cycle("evaluator_comparison", _report_dict(report))

    console.print("[bold]Broker-free analytical evaluator comparison[/bold]")
    console.print("Broker contacted: false.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("Generated trading signals: false.")
    console.print("P&L calculated: false.")
    _print_evaluator_comparison_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("history-snapshot")
def history_snapshot(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to fetch and validate."),
    ] = "SPY,AAPL",
    duration: Annotated[
        str,
        typer.Option("--duration", help="IBKR historical duration string."),
    ] = "1 D",
    bar_size: Annotated[
        str,
        typer.Option("--bar-size", help="IBKR historical bar size."),
    ] = "5 mins",
    what_to_show: Annotated[
        str,
        typer.Option("--what-to-show", help="IBKR historical data type."),
    ] = "TRADES",
    use_rth: Annotated[
        int,
        typer.Option("--use-rth", help="Use regular trading hours: 1 or 0."),
    ] = 1,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Override IBKR connect/request timeout seconds."),
    ] = 30,
) -> None:
    """Fetch historical snapshots and immediately write a readiness report."""

    config = _load_config_or_exit()
    validated_timeout = _validate_timeout_option(timeout)
    request_timeout = validated_timeout if validated_timeout is not None else 30
    use_rth = _validate_use_rth_option(use_rth)
    selected_symbols = parse_symbols(symbols)
    snapshot_report = _fetch_historical_snapshot_report(
        config,
        selected_symbols,
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=use_rth,
        timeout=request_timeout,
    )
    snapshot_json, snapshot_md = Journal().write_cycle(
        "history_snapshot",
        _report_dict(snapshot_report),
    )
    readiness_report = build_readiness_report(
        config,
        manifest_paths=snapshot_report.manifest_paths,
    )
    readiness_json, readiness_md = Journal().write_cycle(
        "history_readiness",
        _report_dict(readiness_report),
    )

    console.print("[bold]Read-only historical snapshot[/bold]")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    _print_history_snapshot_result(snapshot_report)
    _print_history_readiness_result(readiness_report)
    console.print(f"Snapshot JSON report: {snapshot_json}")
    console.print(f"Snapshot Markdown report: {snapshot_md}")
    console.print(f"Readiness JSON report: {readiness_json}")
    console.print(f"Readiness Markdown report: {readiness_md}")
    if not snapshot_report.ok or not readiness_report.ok:
        raise typer.Exit(code=1)


@app.command("paper-readiness-run")
def paper_readiness_run(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols for the first paper readiness run."),
    ] = "SPY,AAPL,GLD,USO,DBA",
    commodity_symbols: Annotated[
        str,
        typer.Option(
            "--commodity-symbols",
            help="Comma-separated commodity-linked security proxies.",
        ),
    ] = "GLD,USO,DBA",
    duration: Annotated[
        str,
        typer.Option("--duration", help="IBKR historical duration string."),
    ] = "1 D",
    bar_size: Annotated[
        str,
        typer.Option("--bar-size", help="IBKR historical bar size."),
    ] = "5 mins",
    what_to_show: Annotated[
        str,
        typer.Option("--what-to-show", help="IBKR historical data type."),
    ] = "TRADES",
    use_rth: Annotated[
        int,
        typer.Option("--use-rth", help="Use regular trading hours: 1 or 0."),
    ] = 1,
    broker_timeout: Annotated[
        float,
        typer.Option("--broker-timeout", help="Broker/account probe timeout seconds."),
    ] = 15,
    history_timeout: Annotated[
        float,
        typer.Option("--history-timeout", help="Historical request timeout seconds."),
    ] = 30,
    broker_stage_pause: Annotated[
        float,
        typer.Option(
            "--broker-stage-pause",
            help="Pause seconds between broker-contact stages.",
        ),
    ] = 1,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
    short_window: Annotated[
        int,
        typer.Option("--short-window", help="Fast moving-average lookback."),
    ] = 5,
    long_window: Annotated[
        int,
        typer.Option("--long-window", help="Slow moving-average lookback."),
    ] = 20,
) -> None:
    """Run the sequential read-only paper-client readiness workflow."""

    config = _load_config_or_exit()
    broker_timeout = _validate_timeout_option(broker_timeout) or 15
    history_timeout = _validate_timeout_option(history_timeout) or 30
    broker_stage_pause = _validate_non_negative_seconds_option(broker_stage_pause, 30)
    use_rth = _validate_use_rth_option(use_rth)
    request = PaperReadinessRunRequest(
        symbols=parse_symbols(symbols),
        commodity_symbols=parse_symbols(commodity_symbols),
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=use_rth,
        broker_timeout_seconds=broker_timeout,
        history_timeout_seconds=history_timeout,
        broker_stage_pause_seconds=broker_stage_pause,
        base_data_path=base_path.as_posix(),
        short_window=short_window,
        long_window=long_window,
    )
    report = run_paper_readiness_run(config, request)
    json_path, md_path = Journal().write_cycle("paper_readiness_run", _report_dict(report))

    console.print("[bold]Read-only paper readiness run[/bold]")
    console.print("Broker contact: read-only account and market-data requests only.")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    console.print("Submitted orders: false.")
    console.print("Paper orders enabled: false.")
    console.print("Read-Only API expected: true.")
    _print_paper_readiness_run_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("alpha-shadow-run")
def alpha_shadow_run(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret campaign correlation ID for local reports.",
        ),
    ] = None,
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols for the first alpha shadow run."),
    ] = "SPY",
    duration: Annotated[
        str,
        typer.Option("--duration", help="IBKR historical duration string."),
    ] = "1 D",
    bar_size: Annotated[
        str,
        typer.Option("--bar-size", help="IBKR historical bar size."),
    ] = "5 mins",
    what_to_show: Annotated[
        str,
        typer.Option("--what-to-show", help="IBKR historical data type."),
    ] = "TRADES",
    use_rth: Annotated[
        int,
        typer.Option("--use-rth", help="Use regular trading hours: 1 or 0."),
    ] = 1,
    broker_timeout: Annotated[
        float,
        typer.Option("--broker-timeout", help="Broker/account probe timeout seconds."),
    ] = 15,
    history_timeout: Annotated[
        float,
        typer.Option("--history-timeout", help="Historical request timeout seconds."),
    ] = 30,
    broker_stage_pause: Annotated[
        float,
        typer.Option(
            "--broker-stage-pause",
            help="Pause seconds between broker-contact stages.",
        ),
    ] = 1,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical snapshot root."),
    ] = Path("data/historical"),
    short_window: Annotated[
        int,
        typer.Option("--short-window", help="Fast moving-average lookback."),
    ] = 5,
    long_window: Annotated[
        int,
        typer.Option("--long-window", help="Slow moving-average lookback."),
    ] = 20,
    min_bars: Annotated[
        int,
        typer.Option("--min-bars", help="Minimum SPY bars required."),
    ] = 50,
    max_zero_volume_bars: Annotated[
        int,
        typer.Option("--max-zero-volume-bars", help="Maximum SPY zero-volume bars."),
    ] = 0,
    min_average_volume: Annotated[
        str,
        typer.Option("--min-average-volume", help="Minimum SPY average bar volume."),
    ] = "100",
    min_average_dollar_volume: Annotated[
        str,
        typer.Option(
            "--min-average-dollar-volume",
            help="Minimum SPY average dollar volume.",
        ),
    ] = "5000",
    max_trade_notional: Annotated[
        str,
        typer.Option("--max-trade-notional", help="Maximum shadow trade notional."),
    ] = "1000",
    max_open_positions: Annotated[
        int,
        typer.Option("--max-open-positions", help="Maximum shadow open positions."),
    ] = 1,
) -> None:
    """Run the first broker-connected read-only alpha shadow workflow."""

    config = _load_config_or_exit()
    broker_timeout = _validate_timeout_option(broker_timeout) or 15
    history_timeout = _validate_timeout_option(history_timeout) or 30
    broker_stage_pause = _validate_non_negative_seconds_option(broker_stage_pause, 30)
    use_rth = _validate_use_rth_option(use_rth)
    request = AlphaShadowRunRequest(
        campaign_id=campaign_id,
        symbols=parse_symbols(symbols),
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=use_rth,
        broker_timeout_seconds=broker_timeout,
        history_timeout_seconds=history_timeout,
        broker_stage_pause_seconds=broker_stage_pause,
        base_data_path=base_path.as_posix(),
        short_window=short_window,
        long_window=long_window,
        min_bars=min_bars,
        max_zero_volume_bars=max_zero_volume_bars,
        min_average_volume=_parse_decimal_option(
            min_average_volume,
            "--min-average-volume",
        ),
        min_average_dollar_volume=_parse_decimal_option(
            min_average_dollar_volume,
            "--min-average-dollar-volume",
        ),
        max_trade_notional=_parse_decimal_option(
            max_trade_notional,
            "--max-trade-notional",
        ),
        max_open_positions=max_open_positions,
    )
    report = run_alpha_shadow_run(config, request)
    json_path, md_path = Journal().write_cycle("alpha_shadow_run", _report_dict(report))

    console.print("[bold]Read-only alpha shadow run[/bold]")
    console.print("Broker contact: read-only account and historical-data requests only.")
    console.print("Order routing: disabled.")
    console.print("Paper execution: disabled.")
    console.print("Submitted orders: false.")
    console.print("Read-Only API expected: true.")
    console.print("Simulator destination only.")
    _print_alpha_shadow_run_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("alpha-shadow-daemon")
def alpha_shadow_daemon(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret daemon campaign correlation ID.",
        ),
    ] = None,
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Daemon symbol. Only SPY is allowed."),
    ] = "SPY",
    session: Annotated[
        str,
        typer.Option("--session", help="Session profile. Only regular is allowed."),
    ] = "regular",
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", help="Seconds between shadow cycles."),
    ] = 300,
    max_cycles: Annotated[
        int,
        typer.Option("--max-cycles", help="Maximum controlled shadow cycles."),
    ] = 1,
    stale_after_minutes: Annotated[
        int,
        typer.Option(
            "--stale-after-minutes",
            help="Maximum source-bar age before the daemon halts failed.",
        ),
    ] = 1440,
    graduation_clean_sessions_required: Annotated[
        int,
        typer.Option(
            "--graduation-clean-sessions-required",
            help="Clean shadow sessions required before paper-daemon consideration.",
        ),
    ] = 5,
    kill_switch_path: Annotated[
        Path,
        typer.Option("--kill-switch-path", help="File path that halts the daemon safely."),
    ] = Path("state/alpha_shadow_daemon.kill"),
    heartbeat_path: Annotated[
        Path,
        typer.Option("--heartbeat-path", help="Ignored local daemon heartbeat JSON path."),
    ] = Path("state/alpha_shadow_daemon_heartbeat.json"),
    duration: Annotated[
        str,
        typer.Option("--duration", help="Historical snapshot duration."),
    ] = "1 D",
    bar_size: Annotated[
        str,
        typer.Option("--bar-size", help="Historical snapshot bar size."),
    ] = "5 mins",
    what_to_show: Annotated[
        str,
        typer.Option("--what-to-show", help="Historical data type."),
    ] = "TRADES",
    use_rth: Annotated[
        int,
        typer.Option("--use-rth", help="Use regular trading hours: 1 or 0."),
    ] = 1,
    broker_timeout: Annotated[
        float,
        typer.Option("--broker-timeout", help="Broker request timeout seconds."),
    ] = 15,
    history_timeout: Annotated[
        float,
        typer.Option("--history-timeout", help="Historical request timeout seconds."),
    ] = 30,
    broker_stage_pause: Annotated[
        float,
        typer.Option(
            "--broker-stage-pause",
            help="Pause seconds between broker-contact stages.",
        ),
    ] = 1,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical data base path."),
    ] = Path("data/historical"),
) -> None:
    """Run controlled read-only autonomous SPY shadow cycles."""

    config = _load_config_or_exit()
    request = AlphaShadowDaemonRequest(
        campaign_id=campaign_id,
        symbol=symbol,
        session=session,
        interval_seconds=interval_seconds,
        max_cycles=max_cycles,
        stale_after_minutes=stale_after_minutes,
        graduation_clean_sessions_required=graduation_clean_sessions_required,
        kill_switch_path=kill_switch_path.as_posix(),
        heartbeat_path=heartbeat_path.as_posix(),
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=_validate_use_rth_option(use_rth),
        broker_timeout_seconds=_validate_timeout_option(broker_timeout) or 15,
        history_timeout_seconds=_validate_timeout_option(history_timeout) or 30,
        broker_stage_pause_seconds=_validate_non_negative_seconds_option(
            broker_stage_pause,
            30,
        ),
        base_data_path=base_path.as_posix(),
    )
    report = run_alpha_shadow_daemon(config, request)
    json_path, md_path = Journal().write_cycle("alpha_shadow_daemon", _report_dict(report))

    console.print("[bold]Read-only alpha shadow daemon[/bold]")
    console.print("Broker contact: read-only account and historical-data requests only.")
    console.print("Order routing: disabled.")
    console.print("Paper execution: disabled.")
    console.print("Submitted orders: false.")
    console.print("Read-Only API expected: true.")
    console.print("Kill switch: create the configured kill-switch file to halt safely.")
    _print_alpha_shadow_daemon_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("alpha-shadow-daemon-delayed")
def alpha_shadow_daemon_delayed(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret delayed daemon campaign correlation ID.",
        ),
    ] = None,
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Daemon symbol. Only SPY is allowed."),
    ] = "SPY",
    session: Annotated[
        str,
        typer.Option("--session", help="Session profile. Only regular is allowed."),
    ] = "regular",
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", help="Seconds between delayed shadow cycles."),
    ] = 300,
    max_cycles: Annotated[
        int,
        typer.Option("--max-cycles", help="Maximum controlled delayed shadow cycles."),
    ] = 1,
    stale_after_minutes: Annotated[
        int,
        typer.Option(
            "--stale-after-minutes",
            help="Maximum source-bar age for delayed engineering shadow.",
        ),
    ] = 30,
    kill_switch_path: Annotated[
        Path,
        typer.Option("--kill-switch-path", help="File path that halts the daemon safely."),
    ] = Path("state/alpha_shadow_daemon_delayed.kill"),
    heartbeat_path: Annotated[
        Path,
        typer.Option("--heartbeat-path", help="Ignored local daemon heartbeat JSON path."),
    ] = Path("state/alpha_shadow_daemon_delayed_heartbeat.json"),
    duration: Annotated[
        str,
        typer.Option("--duration", help="Historical snapshot duration."),
    ] = "1 D",
    bar_size: Annotated[
        str,
        typer.Option("--bar-size", help="Historical snapshot bar size."),
    ] = "5 mins",
    what_to_show: Annotated[
        str,
        typer.Option("--what-to-show", help="Historical data type."),
    ] = "TRADES",
    use_rth: Annotated[
        int,
        typer.Option("--use-rth", help="Use regular trading hours: 1 or 0."),
    ] = 1,
    broker_timeout: Annotated[
        float,
        typer.Option("--broker-timeout", help="Broker request timeout seconds."),
    ] = 15,
    history_timeout: Annotated[
        float,
        typer.Option("--history-timeout", help="Historical request timeout seconds."),
    ] = 30,
    broker_stage_pause: Annotated[
        float,
        typer.Option(
            "--broker-stage-pause",
            help="Pause seconds between broker-contact stages.",
        ),
    ] = 1,
    base_path: Annotated[
        Path,
        typer.Option("--base-path", help="Historical data base path."),
    ] = Path("data/historical"),
) -> None:
    """Run read-only delayed-data SPY shadow cycles for engineering only."""

    config = _load_config_or_exit()
    request = AlphaShadowDaemonRequest(
        campaign_id=campaign_id,
        symbol=symbol,
        session=session,
        interval_seconds=interval_seconds,
        max_cycles=max_cycles,
        stale_after_minutes=stale_after_minutes,
        graduation_clean_sessions_required=1,
        kill_switch_path=kill_switch_path.as_posix(),
        heartbeat_path=heartbeat_path.as_posix(),
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=_validate_use_rth_option(use_rth),
        broker_timeout_seconds=_validate_timeout_option(broker_timeout) or 15,
        history_timeout_seconds=_validate_timeout_option(history_timeout) or 30,
        broker_stage_pause_seconds=_validate_non_negative_seconds_option(
            broker_stage_pause,
            30,
        ),
        base_data_path=base_path.as_posix(),
    )
    report = run_delayed_alpha_shadow_daemon(config, request)
    json_path, md_path = Journal().write_cycle(
        "alpha_shadow_daemon_delayed",
        _report_dict(report),
    )

    console.print("[bold]Delayed-data alpha shadow daemon[/bold]")
    console.print("Broker contact: read-only account and historical-data requests only.")
    console.print("Delayed evidence is engineering-only and non-graduating.")
    console.print("Order routing: disabled.")
    console.print("Paper execution: disabled.")
    console.print("Submitted orders: false.")
    console.print("Read-Only API expected: true.")
    console.print("Kill switch: create the configured kill-switch file to halt safely.")
    _print_alpha_shadow_daemon_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("alpha-shadow-daemon-summary")
def alpha_shadow_daemon_summary(
    report_glob: Annotated[
        str,
        typer.Option(
            "--report-glob",
            help="Glob for ignored alpha-shadow-daemon JSON reports.",
        ),
    ] = "reports/alpha_shadow_daemon_*.json",
    min_clean_sessions: Annotated[
        int,
        typer.Option(
            "--min-clean-sessions",
            help="Clean daemon sessions required before paper-daemon design.",
        ),
    ] = 5,
    max_report_age_hours: Annotated[
        int,
        typer.Option("--max-report-age-hours", help="Maximum source report age in hours."),
    ] = 168,
    require_same_commit: Annotated[
        str,
        typer.Option(
            "--require-same-commit",
            help="Require every source report to match the current commit: true or false.",
        ),
    ] = "true",
) -> None:
    """Summarize read-only alpha-shadow-daemon sessions without contacting IBKR."""

    request = AlphaShadowDaemonSummaryRequest(
        report_glob=report_glob,
        min_clean_sessions=min_clean_sessions,
        max_report_age_hours=max_report_age_hours,
        require_same_commit=_parse_bool_option(
            require_same_commit,
            "--require-same-commit",
        ),
    )
    report = run_alpha_shadow_daemon_summary(request)
    json_path, md_path = Journal().write_cycle(
        "alpha_shadow_daemon_summary",
        _report_dict(report),
    )

    console.print("[bold]Alpha shadow daemon session summary[/bold]")
    console.print("Offline report comparison only; no broker contact.")
    console.print("Order routing: disabled.")
    console.print("Paper execution: disabled.")
    console.print("Submitted orders: false.")
    console.print("Read-Only API expected: true.")
    _print_alpha_shadow_daemon_summary_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("paper-order-smoke")
def paper_order_smoke(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret campaign correlation ID for local reports.",
        ),
    ] = None,
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Paper smoke symbol. Only SPY is allowed."),
    ] = "SPY",
    quantity: Annotated[
        int,
        typer.Option("--quantity", help="Paper smoke quantity. Only 1 is allowed."),
    ] = 1,
    transmit: Annotated[
        str,
        typer.Option(
            "--transmit",
            help="Use 'false' for rehearsal or 'true' for a transmitted paper order.",
        ),
    ] = "false",
    allow_fill: Annotated[
        str,
        typer.Option("--allow-fill", help="Whether a transmitted paper fill is allowed."),
    ] = "false",
    cancel_after_seconds: Annotated[
        float,
        typer.Option(
            "--cancel-after-seconds",
            help="Seconds to wait before canceling an unfilled transmitted order.",
        ),
    ] = 30,
    confirm: Annotated[
        str,
        typer.Option("--confirm", help="Required confirmation string."),
    ] = "",
    max_trade_notional: Annotated[
        str,
        typer.Option("--max-trade-notional", help="Maximum paper smoke notional."),
    ] = "1000",
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Broker request timeout seconds."),
    ] = 30,
) -> None:
    """Run the gated IBKR paper-order lifecycle smoke test."""

    config = _load_config_or_exit()
    request = PaperOrderSmokeRequest(
        campaign_id=campaign_id,
        symbol=symbol,
        quantity=quantity,
        transmit=_parse_bool_option(transmit, "--transmit"),
        allow_fill=_parse_bool_option(allow_fill, "--allow-fill"),
        cancel_after_seconds=_validate_non_negative_seconds_option(
            cancel_after_seconds,
            120,
        ),
        confirm=confirm,
        max_trade_notional=_parse_decimal_option(
            max_trade_notional,
            "--max-trade-notional",
        ),
        timeout_seconds=_validate_timeout_option(timeout) or 30,
    )
    report = run_paper_order_smoke(config, request)
    json_path, md_path = Journal().write_cycle("paper_order_smoke", _report_dict(report))

    console.print("[bold]IBKR paper order smoke[/bold]")
    console.print("Scope: SPY BUY 1 LMT DAY only.")
    console.print("Live trading: disabled.")
    console.print("Live ports: rejected.")
    console.print(
        "Market orders, futures, options, algos, brackets, shorts, and batches: rejected."
    )
    console.print("IBKR Read-Only API should be disabled only while this command is running.")
    _print_paper_order_smoke_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("alpha-paper-run")
def alpha_paper_run(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret campaign correlation ID matching prerequisites.",
        ),
    ] = None,
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Alpha paper symbol. Only SPY is allowed."),
    ] = "SPY",
    quantity: Annotated[
        int,
        typer.Option("--quantity", help="Alpha paper quantity. Only 1 is allowed."),
    ] = 1,
    allow_fill: Annotated[
        str,
        typer.Option("--allow-fill", help="Whether a transmitted paper fill is allowed."),
    ] = "false",
    cancel_after_seconds: Annotated[
        float,
        typer.Option(
            "--cancel-after-seconds",
            help="Seconds to wait before canceling an unfilled transmitted order.",
        ),
    ] = 30,
    confirm: Annotated[
        str,
        typer.Option("--confirm", help="Required alpha paper confirmation string."),
    ] = "",
    max_trade_notional: Annotated[
        str,
        typer.Option("--max-trade-notional", help="Maximum alpha paper notional."),
    ] = "1000",
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Broker request timeout seconds."),
    ] = 30,
    max_report_age_hours: Annotated[
        int,
        typer.Option(
            "--max-report-age-hours",
            help="Maximum age for prerequisite alpha-shadow and paper-smoke reports.",
        ),
    ] = 24,
    alpha_shadow_report: Annotated[
        Path,
        typer.Option(
            "--alpha-shadow-report",
            help="Passing same-commit alpha-shadow report path.",
        ),
    ] = Path("reports/latest_alpha_shadow_run.json"),
    paper_smoke_report: Annotated[
        Path,
        typer.Option(
            "--paper-smoke-report",
            help="Passing same-commit transmitted paper-order-smoke report path.",
        ),
    ] = Path("reports/latest_paper_order_smoke.json"),
) -> None:
    """Run the first strategy-gated SPY paper alpha order."""

    config = _load_config_or_exit()
    request = AlphaPaperRunRequest(
        campaign_id=campaign_id,
        symbol=symbol,
        quantity=quantity,
        allow_fill=_parse_bool_option(allow_fill, "--allow-fill"),
        cancel_after_seconds=_validate_non_negative_seconds_option(
            cancel_after_seconds,
            120,
        ),
        confirm=confirm,
        max_trade_notional=_parse_decimal_option(
            max_trade_notional,
            "--max-trade-notional",
        ),
        timeout_seconds=_validate_timeout_option(timeout) or 30,
        max_report_age_hours=max_report_age_hours,
        alpha_shadow_report_path=alpha_shadow_report.as_posix(),
        paper_smoke_report_path=paper_smoke_report.as_posix(),
    )
    report = run_alpha_paper_run(config, request)
    json_path, md_path = Journal().write_cycle("alpha_paper_run", _report_dict(report))

    console.print("[bold]IBKR alpha paper run[/bold]")
    console.print("Scope: SPY BUY 1 LMT DAY only when shadow signal is BUY and risk approved.")
    console.print("Live trading: disabled.")
    console.print("Live ports: rejected.")
    console.print("Read-Only API should be disabled only while this command is running.")
    console.print(f"Required confirmation: {ALPHA_PAPER_CONFIRMATION}")
    _print_alpha_paper_run_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("paper-reconcile")
def paper_reconcile(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret campaign correlation ID matching source reports.",
        ),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Broker request timeout seconds."),
    ] = 30,
    paper_smoke_report: Annotated[
        Path,
        typer.Option(
            "--paper-smoke-report",
            help="Latest transmitted paper-order-smoke report path.",
        ),
    ] = Path("reports/latest_paper_order_smoke.json"),
    alpha_paper_report: Annotated[
        Path,
        typer.Option(
            "--alpha-paper-report",
            help="Latest alpha-paper-run report path.",
        ),
    ] = Path("reports/latest_alpha_paper_run.json"),
) -> None:
    """Run read-only post-paper-run broker reconciliation."""

    config = _load_config_or_exit()
    request = PaperReconcileRequest(
        campaign_id=campaign_id,
        timeout_seconds=_validate_timeout_option(timeout) or 30,
        paper_smoke_report_path=paper_smoke_report.as_posix(),
        alpha_paper_report_path=alpha_paper_report.as_posix(),
    )
    report = run_paper_reconcile(config, request)
    json_path, md_path = Journal().write_cycle("paper_reconcile", _report_dict(report))

    console.print("[bold]IBKR paper reconciliation[/bold]")
    console.print("Broker contact: read-only account, positions, and open-order checks only.")
    console.print("Order routing: disabled.")
    console.print("Submitted orders: false.")
    _print_paper_reconcile_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("alpha-test-summary")
def alpha_test_summary(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret campaign correlation ID matching source reports.",
        ),
    ] = None,
    alpha_shadow_report: Annotated[
        Path,
        typer.Option("--alpha-shadow-report", help="Alpha-shadow report path."),
    ] = Path("reports/latest_alpha_shadow_run.json"),
    paper_smoke_report: Annotated[
        Path,
        typer.Option("--paper-smoke-report", help="Paper-order-smoke report path."),
    ] = Path("reports/latest_paper_order_smoke.json"),
    alpha_paper_report: Annotated[
        Path,
        typer.Option("--alpha-paper-report", help="Alpha-paper-run report path."),
    ] = Path("reports/latest_alpha_paper_run.json"),
    paper_reconcile_report: Annotated[
        Path,
        typer.Option("--paper-reconcile-report", help="Paper-reconcile report path."),
    ] = Path("reports/latest_paper_reconcile.json"),
    max_report_age_hours: Annotated[
        int,
        typer.Option("--max-report-age-hours", help="Maximum source report age."),
    ] = 24,
) -> None:
    """Summarize one paper alpha test campaign from ignored local reports."""

    request = AlphaTestSummaryRequest(
        campaign_id=campaign_id,
        alpha_shadow_report_path=alpha_shadow_report.as_posix(),
        paper_smoke_report_path=paper_smoke_report.as_posix(),
        alpha_paper_report_path=alpha_paper_report.as_posix(),
        paper_reconcile_report_path=paper_reconcile_report.as_posix(),
        max_report_age_hours=max_report_age_hours,
    )
    report = run_alpha_test_summary(request)
    json_path, md_path = Journal().write_cycle("alpha_test_summary", _report_dict(report))

    console.print("[bold]IBKR alpha test summary[/bold]")
    console.print("Offline report aggregation only; no broker contact and no order APIs.")
    _print_alpha_test_summary_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("paper-ledger-update")
def paper_ledger_update(
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret campaign correlation ID matching source reports.",
        ),
    ] = None,
    alpha_test_summary_report: Annotated[
        Path,
        typer.Option(
            "--alpha-test-summary-report",
            help="Alpha-test-summary report path.",
        ),
    ] = Path("reports/latest_alpha_test_summary.json"),
    paper_reconcile_report: Annotated[
        Path,
        typer.Option("--paper-reconcile-report", help="Paper-reconcile report path."),
    ] = Path("reports/latest_paper_reconcile.json"),
    ledger_path: Annotated[
        Path,
        typer.Option(
            "--ledger-path",
            help="Ignored local paper ledger JSONL path.",
        ),
    ] = Path("state/paper_ledger.jsonl"),
) -> None:
    """Upsert one ignored local paper-campaign ledger row from source reports."""

    request = PaperLedgerUpdateRequest(
        campaign_id=campaign_id,
        alpha_test_summary_report_path=alpha_test_summary_report.as_posix(),
        paper_reconcile_report_path=paper_reconcile_report.as_posix(),
        ledger_path=ledger_path.as_posix(),
    )
    report = run_paper_ledger_update(request)
    json_path, md_path = Journal().write_cycle("paper_ledger_update", _report_dict(report))

    console.print("[bold]IBKR paper ledger update[/bold]")
    console.print("Offline ledger update only; no broker contact and no order APIs.")
    _print_paper_ledger_update_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("alpha-campaign-run")
def alpha_campaign_run(
    mode: Annotated[
        str,
        typer.Option("--mode", help="Campaign mode: shadow or paper."),
    ] = "shadow",
    campaign_id: Annotated[
        str | None,
        typer.Option(
            "--campaign-id",
            help="Optional no-secret campaign correlation ID for all campaign reports.",
        ),
    ] = None,
    broker_timeout: Annotated[
        float,
        typer.Option("--broker-timeout", help="Broker request timeout seconds."),
    ] = 30,
    history_timeout: Annotated[
        float,
        typer.Option("--history-timeout", help="Historical request timeout seconds."),
    ] = 45,
    broker_stage_pause: Annotated[
        float,
        typer.Option(
            "--broker-stage-pause",
            help="Pause seconds between broker-contact stages.",
        ),
    ] = 2,
    cancel_after_seconds: Annotated[
        float,
        typer.Option(
            "--cancel-after-seconds",
            help="Seconds to wait before canceling an unfilled alpha paper order.",
        ),
    ] = 30,
    allow_fill: Annotated[
        str,
        typer.Option("--allow-fill", help="Whether a transmitted paper fill is allowed."),
    ] = "false",
    max_report_age_hours: Annotated[
        int,
        typer.Option("--max-report-age-hours", help="Maximum source report age."),
    ] = 24,
    alpha_shadow_report: Annotated[
        Path,
        typer.Option(
            "--alpha-shadow-report",
            help="Source alpha-shadow report path for paper mode.",
        ),
    ] = Path("reports/latest_alpha_shadow_run.json"),
    paper_smoke_report: Annotated[
        Path,
        typer.Option(
            "--paper-smoke-report",
            help="Source transmitted paper-order-smoke report path for paper mode.",
        ),
    ] = Path("reports/latest_paper_order_smoke.json"),
    read_only_off_confirm: Annotated[
        str,
        typer.Option(
            "--read-only-off-confirm",
            help="Required paper-mode confirmation string.",
        ),
    ] = "",
) -> None:
    """Run one sequential SPY alpha campaign mode."""

    config = _load_config_or_exit()
    request = AlphaCampaignRunRequest(
        campaign_id=campaign_id,
        mode=AlphaCampaignRunMode(mode.strip().lower()),
        broker_timeout_seconds=_validate_timeout_option(broker_timeout) or 30,
        history_timeout_seconds=_validate_timeout_option(history_timeout) or 45,
        broker_stage_pause_seconds=_validate_non_negative_seconds_option(
            broker_stage_pause,
            120,
        ),
        cancel_after_seconds=_validate_non_negative_seconds_option(
            cancel_after_seconds,
            120,
        ),
        allow_fill=_parse_bool_option(allow_fill, "--allow-fill"),
        max_report_age_hours=max_report_age_hours,
        alpha_shadow_report_path=alpha_shadow_report.as_posix(),
        paper_smoke_report_path=paper_smoke_report.as_posix(),
        read_only_off_confirm=read_only_off_confirm,
    )
    report = run_alpha_campaign_run(config, request)
    json_path, md_path = Journal().write_cycle("alpha_campaign_run", _report_dict(report))

    console.print("[bold]IBKR alpha campaign run[/bold]")
    console.print(f"Mode: {report.mode}")
    console.print(f"Campaign ID: {report.campaign_id}")
    console.print("Scope: SPY-only staged paper-alpha orchestration.")
    console.print("Live trading, live ports, direct futures, options, and market orders: rejected.")
    if mode.strip().lower() == "paper":
        console.print(f"Required Read-Only-off confirmation: {READ_ONLY_OFF_CONFIRMATION}")
        console.print("Re-enable IBKR Read-Only API immediately after the paper window.")
    _print_alpha_campaign_run_result(report)
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def account(
    connect: Annotated[
        bool,
        typer.Option(
            "--connect/--mock",
            help="Attempt a read-only broker account snapshot; fallback output is clearly mock.",
        ),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Override IBKR connect/request timeout seconds."),
    ] = None,
) -> None:
    """Show an account snapshot without enabling execution."""

    config = _load_config_or_exit()
    timeout = _validate_timeout_option(timeout)
    if connect:
        report = _ibkr_client(config).diagnostic_report(
            timeout=timeout,
            include_managed_accounts=True,
            include_account=True,
        )
        if report.account_snapshot:
            console.print("[bold]Account snapshot[/bold]")
            console.print("Source: broker read-only account summary; no orders placed.")
            console.print_json(data=report.account_snapshot)
            return
        console.print(
            "[yellow]Broker account snapshot unavailable; falling back to mock data.[/yellow]"
        )

    snapshot = _account_client(config).snapshot()
    console.print("[bold]Account snapshot[/bold]")
    console.print("Source: mock data; this is not broker account data; no orders placed.")
    console.print_json(
        data={
            "account_id": snapshot.masked_account_id(),
            "equity": str(snapshot.equity),
            "cash": str(snapshot.cash),
            "buying_power": str(snapshot.buying_power),
            "daily_pnl": str(snapshot.daily_pnl),
            "is_mock": snapshot.is_mock,
        }
    )


@app.command()
def positions(
    connect: Annotated[
        bool,
        typer.Option(
            "--connect/--mock",
            help="Attempt a read-only broker positions snapshot; fallback output is clearly mock.",
        ),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Override IBKR connect/request timeout seconds."),
    ] = None,
) -> None:
    """Show positions without enabling execution."""

    config = _load_config_or_exit()
    timeout = _validate_timeout_option(timeout)
    if connect:
        report = _ibkr_client(config).diagnostic_report(
            timeout=timeout,
            include_managed_accounts=True,
            include_positions=True,
        )
        if report.positions_snapshot:
            console.print("[bold]Positions[/bold]")
            console.print("Source: broker read-only positions snapshot; no orders placed.")
            console.print_json(data=report.positions_snapshot)
            return
        console.print("[yellow]Broker positions unavailable; falling back to mock data.[/yellow]")

    snapshots = _account_client(config).positions()
    console.print("[bold]Positions[/bold]")
    console.print("Source: mock data; this is not broker position data; no orders placed.")
    console.print_json(data=[position.model_dump(mode="json") for position in snapshots])


@app.command()
def probe(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated symbols to probe."),
    ] = "SPY,QQQ,AAPL",
) -> None:
    """Probe deterministic mock market data."""

    selected_symbols = parse_symbols(symbols)
    quotes = deterministic_quotes(selected_symbols)
    table = Table(title="Market Probe")
    table.add_column("Symbol")
    table.add_column("Bid")
    table.add_column("Ask")
    table.add_column("Last")
    table.add_column("Source")
    for symbol, quote in quotes.items():
        table.add_row(
            symbol,
            str(quote.bid),
            str(quote.ask),
            str(quote.last),
            "mock deterministic data",
        )
    console.print(table)
    console.print("No broker socket was opened and no orders were placed.")


@app.command()
def plan(
    strategy: Annotated[
        str,
        typer.Option(help="Strategy name: momentum or mean_reversion."),
    ] = "momentum",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Keep the planning command in dry-run mode."),
    ] = True,
) -> None:
    """Generate signals and trade plans, then run risk checks."""

    if not dry_run:
        console.print("[red]Non-dry-run planning is disabled in this initial version.[/red]")
        raise typer.Exit(code=2)

    config = _load_config_or_exit()
    payload = build_plan_payload(config, strategy_name=strategy)
    json_path, md_path = Journal().write_cycle("plan", payload)

    console.print("[bold]Dry-run plan complete[/bold]")
    console.print("Source: deterministic mock data; no broker socket opened; no orders placed.")
    console.print(f"Final status: {payload['final_status']}")
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")


@app.command()
def simulate(
    plan_name: Annotated[
        str,
        typer.Option("--plan", help="Plan report to simulate, or 'latest'."),
    ] = "latest",
) -> None:
    """Simulate risk-approved plans from a saved report."""

    path = Path("reports/latest_plan.json") if plan_name == "latest" else Path(plan_name)
    if not path.exists():
        console.print(f"[red]Plan report not found:[/red] {path}")
        raise typer.Exit(code=1)

    config = _load_config_or_exit()
    payload = json.loads(path.read_text())
    decisions = [RiskDecision.model_validate(item) for item in payload.get("risk_decisions", [])]
    quotes = {
        symbol: MarketQuote.model_validate(quote)
        for symbol, quote in payload.get("quotes", {}).items()
    }
    results = ExecutionRouter(config).route(decisions, quotes, destination="simulator")

    report_payload = {
        **payload,
        "title": "Simulation Report",
        "execution_results": results,
        "final_status": "simulated" if any(result.fills for result in results) else "blocked",
    }
    json_path, md_path = Journal().write_cycle("simulation", report_payload)
    console.print("[bold]Simulation complete[/bold]")
    console.print("Destination: simulator; no broker orders placed.")
    console.print(f"JSON report: {json_path}")
    console.print(f"Markdown report: {md_path}")


@app.command()
def status() -> None:
    """Show current system status and safety posture."""

    config = _load_config_or_exit()
    blockers = []
    if not config.allow_paper_orders:
        blockers.append("paper broker execution disabled by ALLOW_PAPER_ORDERS=false")
    console.print("[bold]Quant system status[/bold]")
    console.print("Live trading: disabled and unsupported.")
    console.print("Default command behavior: dry-run.")
    console.print("Order routing: disabled.")
    console.print_json(
        data={
            "config": config.safe_summary(),
            "mock_data_available": True,
            "broker_orders_enabled": False,
            "safety_blockers": blockers,
        }
    )


def build_plan_payload(config: TraderConfig, *, strategy_name: str) -> dict[str, Any]:
    selected_strategy = get_strategy(strategy_name)
    symbols = config.universe
    quotes = deterministic_quotes(symbols)
    history = deterministic_history(symbols)
    account = _account_client(config).snapshot()
    positions = mock_positions()
    signals = selected_strategy.generate_signals(symbols, quotes, history)
    plans = build_trade_plans(signals, quotes, config)
    decisions = evaluate_trade_plans(plans, quotes, account, positions, config)
    approved = [decision for decision in decisions if decision.approved]
    blocked = [decision for decision in decisions if not decision.approved]
    final_status = "risk_approved" if approved and not blocked else "blocked"
    if not signals:
        final_status = "no_signals"

    return {
        "title": "Dry-Run Trade Plan",
        "config": config.safe_summary(),
        "account": account,
        "positions": positions,
        "quotes": quotes,
        "signals": signals,
        "plans": plans,
        "risk_decisions": decisions,
        "execution_results": [],
        "warnings": [
            "deterministic mock market data",
            "no broker socket opened",
            "no orders placed",
        ],
        "final_status": final_status,
    }


def _fetch_historical_snapshot_report(
    config: TraderConfig,
    symbols: list[str],
    *,
    duration: str,
    bar_size: str,
    what_to_show: str,
    use_rth: int,
    timeout: float,
) -> HistoricalSnapshotReport:
    report = _ibkr_client(config).request_historical_snapshots(
        symbols,
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=use_rth,
        timeout=timeout,
    )
    timestamp_slug = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stored_results = [
        write_historical_snapshot_result(result, timestamp_slug=timestamp_slug)
        for result in report.results
    ]
    return attach_snapshot_paths(report.model_copy(update={"results": stored_results}))


def _parse_optional_symbols(symbols: str | None) -> list[str]:
    if symbols is None or not symbols.strip():
        return []
    return parse_symbols(symbols)


def _load_config_or_exit() -> TraderConfig:
    try:
        return load_config()
    except ConfigError as exc:
        console.print(f"[red]Configuration rejected:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _validate_timeout_option(timeout: float | None) -> float | None:
    if timeout is not None and timeout <= 0:
        console.print("[red]Timeout must be greater than zero seconds.[/red]")
        raise typer.Exit(code=2)
    return timeout


def _validate_non_negative_seconds_option(value: float, maximum: float) -> float:
    if value < 0 or value > maximum:
        console.print(f"[red]Value must be between 0 and {maximum:g} seconds.[/red]")
        raise typer.Exit(code=2)
    return value


def _validate_use_rth_option(use_rth: int) -> int:
    if use_rth not in {0, 1}:
        console.print("[red]--use-rth must be 0 or 1.[/red]")
        raise typer.Exit(code=2)
    return use_rth


def _report_dict(
    report: (
        AnalyticalSignalEvaluationReport
        | AlphaCampaignRunReport
        | AlphaPaperRunReport
        | AlphaShadowDaemonReport
        | AlphaShadowDaemonSummaryReport
        | AlphaShadowRunReport
        | BacktestDataAdapterReport
        | BacktestRunReport
        | BrokerDiagnosticReport
        | CommodityResearchUniverseReport
        | DataQualityGateReport
        | DisabledSignalRunnerReport
        | EvaluatorComparisonReport
        | HistoricalLoaderReport
        | HistoricalReadinessReport
        | HistoricalSnapshotReport
        | IBKRDataDiagnosticsReport
        | InertStrategyRunnerReport
        | MarketDataDiagnosticReport
        | AlphaTestSummaryReport
        | PaperOrderSmokeReport
        | PaperLedgerUpdateReport
        | PaperReadinessRunReport
        | PaperReconcileReport
        | ResearchBacktestReport
        | ResearchDataAuditReport
        | ResearchDataIngestReport
        | ResearchWalkForwardReport
        | SignalContractReport
        | StrategyContractReport
    ),
) -> dict[str, Any]:
    return report.model_dump(mode="json")


def _print_backtest_feed_result(report: BacktestDataAdapterReport) -> None:
    summary = report.summary
    table = Table(title="Backtest Feed")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Alignment", _enum_value(report.request.alignment_mode))
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("No order APIs invoked", "true")
    table.add_row("Final status", report.final_status)
    if summary is not None:
        table.add_row("Total bars", str(summary.total_bars))
        table.add_row("Frame count", str(summary.frame_count))
        table.add_row(
            "First timestamp",
            summary.first_timestamp.isoformat() if summary.first_timestamp else "n/a",
        )
        table.add_row(
            "Last timestamp",
            summary.last_timestamp.isoformat() if summary.last_timestamp else "n/a",
        )
    console.print(table)

    if summary is not None:
        missing_table = Table(title="Missing Bars")
        missing_table.add_column("Symbol")
        missing_table.add_column("Missing bars")
        missing_table.add_column("Duplicates")
        for symbol in summary.symbols:
            missing_table.add_row(
                symbol,
                str(summary.missing_bars_by_symbol.get(symbol, 0)),
                str(summary.duplicate_timestamps_by_symbol.get(symbol, 0)),
            )
        console.print(missing_table)

    if report.warnings:
        console.print("[yellow]Backtest feed warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Backtest feed errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_backtest_run_result(report: BacktestRunReport) -> None:
    diagnostics = report.diagnostics
    table = Table(title="Backtest Run")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Alignment", _enum_value(report.request.alignment_mode))
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Strategy evaluated", str(report.strategy_evaluated).lower())
    table.add_row("Orders simulated", str(report.orders_simulated).lower())
    table.add_row("P&L calculated", str(report.pnl_calculated).lower())
    table.add_row("Final status", report.final_status)
    table.add_row("Frame count", str(diagnostics.frame_count))
    table.add_row("Observations", str(diagnostics.observations_count))
    table.add_row("Total bars observed", str(diagnostics.total_bars_observed))
    table.add_row(
        "First timestamp",
        diagnostics.first_timestamp.isoformat() if diagnostics.first_timestamp else "n/a",
    )
    table.add_row(
        "Last timestamp",
        diagnostics.last_timestamp.isoformat() if diagnostics.last_timestamp else "n/a",
    )
    table.add_row("Frames with missing bars", str(diagnostics.frames_with_missing_bars))
    console.print(table)

    missing_table = Table(title="Run Missing Bars")
    missing_table.add_column("Symbol")
    missing_table.add_column("Missing bars")
    for symbol in diagnostics.symbols:
        missing_table.add_row(
            symbol,
            str(diagnostics.missing_bars_by_symbol.get(symbol, 0)),
        )
    console.print(missing_table)

    if report.warnings:
        console.print("[yellow]Backtest run warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Backtest run errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_research_backtest_result(report: ResearchBacktestReport) -> None:
    table = Table(title="Research Backtest")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Symbol", report.request.symbol)
    table.add_row(
        "Windows",
        f"{report.request.short_window}/{report.request.long_window}",
    )
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Promotion eligible", str(report.promotion_eligible).lower())
    table.add_row("Fill count", str(len(report.fills)))
    table.add_row("Closed trades", str(len(report.trades)))
    if report.metrics is not None:
        table.add_row("Ending equity", str(report.metrics.ending_equity))
        table.add_row("Net P&L", str(report.metrics.net_pnl))
        table.add_row("Total return", f"{report.metrics.total_return_pct}%")
        table.add_row("Maximum drawdown", f"{report.metrics.max_drawdown_pct}%")
        table.add_row("Turnover ratio", str(report.metrics.turnover_ratio))
    console.print(table)
    if report.warnings:
        console.print("[yellow]Research backtest warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Research backtest errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_research_walk_forward_result(report: ResearchWalkForwardReport) -> None:
    table = Table(title="Research Validation")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Walk-forward completed", str(report.walk_forward_completed).lower())
    table.add_row("Completed folds", str(len([fold for fold in report.folds if fold.ok])))
    table.add_row("Holdout evaluations", str(report.holdout_evaluation_count))
    table.add_row("Holdout used for selection", str(report.holdout_used_for_selection).lower())
    table.add_row("Sealed holdout completed", str(report.sealed_holdout_completed).lower())
    table.add_row("Promotion eligible", str(report.promotion_eligible).lower())
    if report.selected_candidate is not None:
        table.add_row(
            "Selected candidate",
            f"{report.selected_candidate.short_window}:{report.selected_candidate.long_window}",
        )
    if report.holdout_trial is not None:
        table.add_row("Holdout return", f"{report.holdout_trial.total_return_pct}%")
        table.add_row("Holdout drawdown", f"{report.holdout_trial.max_drawdown_pct}%")
        table.add_row("Holdout trades", str(report.holdout_trial.closed_trade_count))
    console.print(table)
    if report.warnings:
        console.print("[yellow]Research validation warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Research validation errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_strategy_contract_result(report: StrategyContractReport) -> None:
    result = report.result
    table = Table(title="Strategy Contract")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Strategy", report.metadata.strategy_name)
    table.add_row("Version", report.metadata.strategy_version)
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Alignment", _enum_value(report.request.alignment_mode))
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Evaluated", str(report.evaluated).lower())
    table.add_row("Generated signals", str(report.generated_signals).lower())
    table.add_row("Generated orders", str(report.generated_orders).lower())
    table.add_row("Orders simulated", str(report.orders_simulated).lower())
    table.add_row("P&L calculated", str(report.pnl_calculated).lower())
    table.add_row("Final status", report.final_status)
    table.add_row("Contexts observed", str(result.contexts_observed))
    table.add_row("Diagnostics", str(len(report.diagnostics)))
    if report.feed_summary is not None:
        table.add_row("Feed status", _enum_value(report.feed_summary.feed_status))
        table.add_row("Feed frames", str(report.feed_summary.frame_count))
    console.print(table)

    sample = report.frame_context_sample
    context_table = Table(title="Frame Context Sample")
    context_table.add_column("Check")
    context_table.add_column("Value")
    if sample is not None:
        context_table.add_row("Timestamp", sample.timestamp.isoformat())
        context_table.add_row("Frame index", str(sample.frame_index))
        context_table.add_row("Available symbols", ", ".join(sample.available_symbols))
        context_table.add_row("Missing symbols", ", ".join(sample.missing_symbols) or "none")
    else:
        context_table.add_row("Sample", "none")
    console.print(context_table)

    if report.warnings:
        console.print("[yellow]Strategy contract warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Strategy contract errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_strategy_runner_result(report: InertStrategyRunnerReport) -> None:
    diagnostics = report.diagnostics
    table = Table(title="Inert Strategy Runner")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Strategy", report.metadata.strategy_name)
    table.add_row("Version", report.metadata.strategy_version)
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Alignment", _enum_value(report.request.alignment_mode))
    table.add_row("Diagnostic only", str(report.diagnostic_only).lower())
    table.add_row("No-op strategy observed", str(report.noop_strategy_observed).lower())
    table.add_row(
        "Real strategy evaluated",
        str(report.real_strategy_evaluated).lower(),
    )
    table.add_row("Generated signals", str(report.generated_signals).lower())
    table.add_row("Generated orders", str(report.generated_orders).lower())
    table.add_row("Orders simulated", str(report.orders_simulated).lower())
    table.add_row("Fills simulated", str(report.fills_simulated).lower())
    table.add_row("P&L calculated", str(report.pnl_calculated).lower())
    table.add_row("Portfolio accounting", str(report.portfolio_accounting).lower())
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Final status", report.final_status)
    table.add_row("Frame count", str(diagnostics.frame_count))
    table.add_row("Contexts built", str(diagnostics.contexts_built))
    table.add_row("Diagnostics emitted", str(diagnostics.diagnostics_emitted))
    table.add_row(
        "First timestamp",
        diagnostics.first_timestamp.isoformat() if diagnostics.first_timestamp else "n/a",
    )
    table.add_row(
        "Last timestamp",
        diagnostics.last_timestamp.isoformat() if diagnostics.last_timestamp else "n/a",
    )
    table.add_row(
        "Frames with missing symbols",
        str(diagnostics.missing_symbols_by_frame_count),
    )
    console.print(table)

    missing_table = Table(title="Runner Missing Symbols")
    missing_table.add_column("Symbol")
    missing_table.add_column("Missing frames")
    for symbol in diagnostics.symbols:
        missing_table.add_row(
            symbol,
            str(diagnostics.missing_symbols_by_symbol.get(symbol, 0)),
        )
    console.print(missing_table)

    if report.warnings:
        console.print("[yellow]Strategy runner warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Strategy runner errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_signal_contract_result(report: SignalContractReport) -> None:
    result = report.result
    table = Table(title="Signal Contract")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Contract", report.metadata.signal_contract_name)
    table.add_row("Version", report.metadata.signal_contract_version)
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Alignment", _enum_value(report.request.alignment_mode))
    table.add_row(
        "Signal contract validated",
        str(report.signal_contract_validated).lower(),
    )
    table.add_row(
        "Signal evaluation enabled",
        str(report.signal_evaluation_enabled).lower(),
    )
    table.add_row("Generated signals", str(report.generated_signals).lower())
    table.add_row("Signal count", str(report.signal_count))
    table.add_row("Generated orders", str(report.generated_orders).lower())
    table.add_row("Orders simulated", str(report.orders_simulated).lower())
    table.add_row("Fills simulated", str(report.fills_simulated).lower())
    table.add_row("P&L calculated", str(report.pnl_calculated).lower())
    table.add_row("Portfolio accounting", str(report.portfolio_accounting).lower())
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Final status", report.final_status)
    table.add_row("Contexts observed", str(result.contexts_observed))
    table.add_row("Diagnostics", str(len(report.diagnostics)))
    if report.feed_summary is not None:
        table.add_row("Feed status", _enum_value(report.feed_summary.feed_status))
        table.add_row("Feed frames", str(report.feed_summary.frame_count))
    console.print(table)

    sample = report.frame_context_sample
    context_table = Table(title="Signal Context Sample")
    context_table.add_column("Check")
    context_table.add_column("Value")
    if sample is not None:
        context_table.add_row("Timestamp", sample.timestamp.isoformat())
        context_table.add_row("Frame index", str(sample.frame_index))
        context_table.add_row("Available symbols", ", ".join(sample.available_symbols))
        context_table.add_row("Missing symbols", ", ".join(sample.missing_symbols) or "none")
    else:
        context_table.add_row("Sample", "none")
    console.print(context_table)

    if report.warnings:
        console.print("[yellow]Signal contract warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Signal contract errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_signal_runner_result(report: DisabledSignalRunnerReport) -> None:
    diagnostics = report.diagnostics
    table = Table(title="Disabled Signal Runner")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Contract", report.metadata.signal_contract_name)
    table.add_row("Version", report.metadata.signal_contract_version)
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Alignment", _enum_value(report.request.alignment_mode))
    table.add_row("Disabled signal runner", str(report.disabled_signal_runner).lower())
    table.add_row(
        "Signal contract validated",
        str(report.signal_contract_validated).lower(),
    )
    table.add_row(
        "Signal evaluation enabled",
        str(report.signal_evaluation_enabled).lower(),
    )
    table.add_row("Generated signals", str(report.generated_signals).lower())
    table.add_row("Signal count", str(report.signal_count))
    table.add_row("Generated orders", str(report.generated_orders).lower())
    table.add_row(
        "Order intents generated",
        str(report.order_intents_generated).lower(),
    )
    table.add_row("Orders simulated", str(report.orders_simulated).lower())
    table.add_row("Fills simulated", str(report.fills_simulated).lower())
    table.add_row("P&L calculated", str(report.pnl_calculated).lower())
    table.add_row("Portfolio accounting", str(report.portfolio_accounting).lower())
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Final status", report.final_status)
    table.add_row("Frame count", str(diagnostics.frame_count))
    table.add_row("Contexts built", str(diagnostics.contexts_built))
    table.add_row("Diagnostics emitted", str(diagnostics.diagnostics_emitted))
    table.add_row(
        "First timestamp",
        diagnostics.first_timestamp.isoformat() if diagnostics.first_timestamp else "n/a",
    )
    table.add_row(
        "Last timestamp",
        diagnostics.last_timestamp.isoformat() if diagnostics.last_timestamp else "n/a",
    )
    table.add_row(
        "Frames with missing symbols",
        str(diagnostics.missing_symbols_by_frame_count),
    )
    if report.feed_summary is not None:
        table.add_row("Feed status", _enum_value(report.feed_summary.feed_status))
        table.add_row("Feed frames", str(report.feed_summary.frame_count))
    console.print(table)

    missing_table = Table(title="Signal Runner Missing Symbols")
    missing_table.add_column("Symbol")
    missing_table.add_column("Missing frames")
    for symbol in diagnostics.symbols:
        missing_table.add_row(
            symbol,
            str(diagnostics.missing_symbols_by_symbol.get(symbol, 0)),
        )
    console.print(missing_table)

    if report.warnings:
        console.print("[yellow]Signal runner warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Signal runner errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_signal_evaluation_result(report: AnalyticalSignalEvaluationReport) -> None:
    diagnostics = report.diagnostics
    table = Table(title="Analytical Signal Evaluation")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Evaluator", report.metadata.name)
    table.add_row("Version", report.metadata.version)
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Alignment", _enum_value(report.request.alignment_mode))
    table.add_row(
        "Signal evaluation enabled",
        str(report.signal_evaluation_enabled).lower(),
    )
    table.add_row("Generated signals", str(report.generated_signals).lower())
    table.add_row("Signal count", str(report.signal_count))
    table.add_row(
        "Order intents generated",
        str(report.order_intents_generated).lower(),
    )
    table.add_row("Orders simulated", str(report.orders_simulated).lower())
    table.add_row("Fills simulated", str(report.fills_simulated).lower())
    table.add_row("P&L calculated", str(report.pnl_calculated).lower())
    table.add_row("Portfolio accounting", str(report.portfolio_accounting).lower())
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Final status", report.final_status)
    table.add_row("Frame count", str(diagnostics.frame_count))
    table.add_row("Contexts built", str(diagnostics.contexts_built))
    table.add_row("Observations", str(diagnostics.observations_count))
    table.add_row("Warmup observations", str(diagnostics.warmup_observations))
    table.add_row("Invalid data observations", str(diagnostics.invalid_data_observations))
    table.add_row(
        "First timestamp",
        diagnostics.first_timestamp.isoformat() if diagnostics.first_timestamp else "n/a",
    )
    table.add_row(
        "Last timestamp",
        diagnostics.last_timestamp.isoformat() if diagnostics.last_timestamp else "n/a",
    )
    if report.feed_summary is not None:
        table.add_row("Feed status", _enum_value(report.feed_summary.feed_status))
        table.add_row("Feed frames", str(report.feed_summary.frame_count))
    console.print(table)

    state_table = Table(title="Condition State Counts")
    state_table.add_column("State")
    state_table.add_column("Count")
    if diagnostics.observations_by_state:
        for state, count in sorted(diagnostics.observations_by_state.items()):
            state_table.add_row(state, str(count))
    else:
        state_table.add_row("none", "0")
    console.print(state_table)

    if report.warnings:
        console.print("[yellow]Signal evaluation warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Signal evaluation errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_evaluator_comparison_result(report: EvaluatorComparisonReport) -> None:
    table = Table(title="Evaluator Comparison")
    table.add_column("Candidate")
    table.add_column("Status")
    table.add_column("Observations")
    table.add_column("Train Met Rate")
    table.add_column("Test Met Rate")
    table.add_column("Delta")
    for result in report.results:
        candidate = f"{result.candidate.short_window}:{result.candidate.long_window}"
        table.add_row(
            candidate,
            _enum_value(result.final_status),
            str(result.total_observations),
            _format_optional_rate(result.train.condition_met_rate),
            _format_optional_rate(result.test.condition_met_rate),
            _format_optional_rate(result.condition_met_rate_delta),
        )
    console.print(table)
    console.print(f"Broker contacted: {str(report.broker_contacted).lower()}.")
    console.print(f"Generated signals: {str(report.generated_signals).lower()}.")
    console.print(f"P&L calculated: {str(report.pnl_calculated).lower()}.")
    console.print(f"Final status: {_enum_value(report.final_status)}")
    if report.warnings:
        console.print("[yellow]Evaluator comparison warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Evaluator comparison errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_paper_readiness_run_result(report: PaperReadinessRunReport) -> None:
    table = Table(title="Paper Readiness Run")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Selected universe", ", ".join(report.selected_universe))
    table.add_row("Commodity proxies", ", ".join(report.commodity_symbols))
    table.add_row(
        "Broker stage pause",
        f"{report.request.broker_stage_pause_seconds:g}s",
    )
    table.add_row("Broker connected", str(report.broker_connected).lower())
    table.add_row(
        "Account summary verified",
        str(report.account_summary_verified).lower(),
    )
    table.add_row(
        "History snapshot written",
        str(report.history_snapshot_written).lower(),
    )
    table.add_row("History load completed", str(report.history_load_completed).lower())
    table.add_row(
        "Signal evaluation completed",
        str(report.signal_evaluation_completed).lower(),
    )
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Paper orders enabled", str(report.paper_orders_enabled).lower())
    table.add_row("Read-Only API expected", str(report.read_only_api_expected).lower())
    table.add_row("Order routing", "disabled")
    table.add_row(
        "Partial symbols",
        ", ".join(report.partial_symbols) if report.partial_symbols else "none",
    )
    console.print(table)

    stages = Table(title="Sequential Stages")
    stages.add_column("Stage")
    stages.add_column("Status")
    stages.add_column("OK")
    stages.add_column("Reports")
    for stage in report.stages:
        stages.add_row(
            stage.name,
            _enum_value(stage.final_status),
            str(stage.ok).lower(),
            str(len(stage.report_paths)),
        )
    console.print(stages)

    if report.account_ids_masked:
        console.print(
            "Masked accounts: "
            + ", ".join(escape(account) for account in report.account_ids_masked)
        )
    if report.warnings:
        console.print("[yellow]Paper readiness warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Paper readiness errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_alpha_shadow_run_result(report: AlphaShadowRunReport) -> None:
    table = Table(title="Alpha Shadow Run")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Selected universe", ", ".join(report.selected_universe))
    table.add_row(
        "Broker stage pause",
        f"{report.request.broker_stage_pause_seconds:g}s",
    )
    table.add_row("Broker connected", str(report.broker_connected).lower())
    table.add_row(
        "Account summary verified",
        str(report.account_summary_verified).lower(),
    )
    table.add_row(
        "History snapshot written",
        str(report.history_snapshot_written).lower(),
    )
    table.add_row("History load completed", str(report.history_load_completed).lower())
    table.add_row("Data quality completed", str(report.data_quality_completed).lower())
    table.add_row(
        "Signal evaluation completed",
        str(report.signal_evaluation_completed).lower(),
    )
    table.add_row("Shadow risk mode", report.shadow_risk_mode)
    table.add_row("Shadow signals", str(report.shadow_signal_count))
    table.add_row("Trade plans", str(report.trade_plan_count))
    table.add_row("Risk decisions", str(report.risk_decision_count))
    table.add_row("Risk approved", str(report.risk_approved_count))
    table.add_row("Simulation results", str(report.simulation_result_count))
    table.add_row("Simulated fills", str(report.simulated_fill_count))
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Paper orders enabled", str(report.paper_orders_enabled).lower())
    table.add_row("Read-Only API expected", str(report.read_only_api_expected).lower())
    table.add_row("Order routing", "disabled")
    console.print(table)

    stages = Table(title="Sequential Alpha Stages")
    stages.add_column("Stage")
    stages.add_column("Status")
    stages.add_column("OK")
    stages.add_column("Reports")
    for stage in report.stages:
        stages.add_row(
            stage.name,
            _enum_value(stage.final_status),
            str(stage.ok).lower(),
            str(len(stage.report_paths)),
        )
    console.print(stages)

    if report.account_ids_masked:
        console.print(
            "Masked accounts: "
            + ", ".join(escape(account) for account in report.account_ids_masked)
        )
    if report.data_quality_status_by_symbol:
        statuses = ", ".join(
            f"{symbol}:{status}"
            for symbol, status in sorted(report.data_quality_status_by_symbol.items())
        )
        console.print(f"Data-quality status: {escape(statuses)}")
    if report.source_bar_timestamp_by_symbol:
        sources = ", ".join(
            f"{symbol}:{timestamp}"
            for symbol, timestamp in sorted(report.source_bar_timestamp_by_symbol.items())
        )
        console.print(f"Shadow quote source bars: {escape(sources)}")
    if report.warnings:
        console.print("[yellow]Alpha shadow warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Alpha shadow errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_alpha_shadow_daemon_result(report: AlphaShadowDaemonReport) -> None:
    table = Table(title="Alpha Shadow Daemon")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Commit SHA", report.commit_sha or "unknown")
    table.add_row("Campaign ID", report.campaign_id or "n/a")
    table.add_row("Cycles", str(report.cycle_count))
    table.add_row("Clean cycles", str(report.clean_cycle_count))
    table.add_row("Data policy", _enum_value(report.market_data_policy))
    table.add_row("Delayed data mode", str(report.delayed_data_mode).lower())
    table.add_row("Graduation eligible", str(report.graduation_eligible).lower())
    table.add_row("Graduation ready", str(report.graduation_ready).lower())
    table.add_row("Non-graduating reason", report.non_graduating_reason or "n/a")
    table.add_row("Broker-connected cycles", str(report.broker_connected_cycles))
    table.add_row(
        "Account-verified cycles",
        str(report.account_summary_verified_cycles),
    )
    table.add_row("Stale data detected", str(report.stale_data_detected).lower())
    table.add_row("Halted by kill switch", str(report.halted_by_kill_switch).lower())
    table.add_row("Heartbeat path", report.heartbeat_path)
    table.add_row("Kill switch path", report.kill_switch_path)
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Paper orders enabled", str(report.paper_orders_enabled).lower())
    table.add_row("Read-Only API expected", str(report.read_only_api_expected).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    console.print(table)

    if report.cycles:
        cycle_table = Table(title="Daemon Cycles")
        cycle_table.add_column("Cycle")
        cycle_table.add_column("Status")
        cycle_table.add_column("OK")
        cycle_table.add_column("Broker")
        cycle_table.add_column("Account")
        cycle_table.add_column("Stale")
        cycle_table.add_column("Reports")
        for cycle in report.cycles:
            cycle_table.add_row(
                str(cycle.cycle_index),
                _enum_value(cycle.final_status),
                str(cycle.ok).lower(),
                str(cycle.broker_connected).lower(),
                str(cycle.account_summary_verified).lower(),
                str(cycle.stale_data_detected).lower(),
                str(len(cycle.shadow_report_paths)),
            )
        console.print(cycle_table)
    if report.warnings:
        console.print("[yellow]Alpha shadow daemon warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Alpha shadow daemon errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_alpha_shadow_daemon_summary_result(
    report: AlphaShadowDaemonSummaryReport,
) -> None:
    table = Table(title="Alpha Shadow Daemon Summary")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Commit SHA", report.commit_sha or "unknown")
    table.add_row("Sessions", str(report.session_count))
    table.add_row("Clean sessions", str(report.clean_session_count))
    table.add_row("Min clean sessions", str(report.request.min_clean_sessions))
    table.add_row("Total cycles", str(report.total_cycles))
    table.add_row("Total clean cycles", str(report.total_clean_cycles))
    table.add_row("Stale sessions", str(report.stale_session_count))
    table.add_row("Stale cycles", str(report.stale_cycle_count))
    table.add_row("Broker-connected cycles", str(report.broker_connected_cycles))
    table.add_row(
        "Account-verified cycles",
        str(report.account_summary_verified_cycles),
    )
    table.add_row("Missing heartbeats", str(report.missing_heartbeat_count))
    table.add_row("Heartbeat mismatches", str(report.heartbeat_mismatch_count))
    table.add_row("Safety violations", str(report.safety_violation_count))
    table.add_row("Graduation ready", str(report.graduation_ready).lower())
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Paper orders enabled", str(report.paper_orders_enabled).lower())
    table.add_row("Read-Only API expected", str(report.read_only_api_expected).lower())
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    console.print(table)

    if report.source_reports:
        source_table = Table(title="Source Daemon Reports")
        source_table.add_column("Path")
        source_table.add_column("Campaign")
        source_table.add_column("Status")
        source_table.add_column("Policy")
        source_table.add_column("Eligible")
        source_table.add_column("Cycles")
        source_table.add_column("Clean")
        source_table.add_column("Broker")
        source_table.add_column("Account")
        source_table.add_column("Heartbeat")
        source_table.add_column("Safety")
        for source in report.source_reports:
            source_table.add_row(
                source.source_report_path,
                source.campaign_id or "n/a",
                source.final_status,
                source.market_data_policy,
                str(source.graduation_eligible).lower(),
                str(source.cycle_count),
                str(source.clean_cycle_count),
                str(source.broker_connected_cycles),
                str(source.account_summary_verified_cycles),
                str(source.heartbeat_present).lower(),
                str(_source_summary_safety_flag(source)).lower(),
            )
        console.print(source_table)
    if report.commit_shas:
        console.print("Source commits: " + ", ".join(escape(item) for item in report.commit_shas))
    if report.campaign_ids:
        console.print(
            "Source campaigns: " + ", ".join(escape(item) for item in report.campaign_ids)
        )
    if report.next_eligibility_reason:
        console.print("[bold]Next eligibility[/bold]")
        for reason in report.next_eligibility_reason:
            console.print(f"- {escape(reason)}")
    if report.warnings:
        console.print("[yellow]Daemon summary warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Daemon summary errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _source_summary_safety_flag(source: AlphaShadowDaemonReportEvidence) -> bool:
    return bool(
        source.submitted_orders
        or source.paper_orders_enabled
        or source.live_orders_enabled
        or source.order_routing_enabled
        or source.order_api_invoked
    )


def _print_paper_order_smoke_result(report: PaperOrderSmokeReport) -> None:
    table = Table(title="Paper Order Smoke")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Mode", report.mode)
    table.add_row("Host", report.host)
    table.add_row("Port", str(report.port))
    table.add_row("Client ID", str(report.client_id))
    table.add_row("Broker connected", str(report.broker_connected).lower())
    table.add_row(
        "Account summary verified",
        str(report.account_summary_verified).lower(),
    )
    table.add_row("Symbol", report.request.symbol)
    table.add_row("Quantity", str(report.request.quantity))
    table.add_row("Order type", _enum_value(report.request.order_type))
    table.add_row("Time in force", report.request.time_in_force)
    table.add_row("Transmit", str(report.transmitted).lower())
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Paper orders enabled", str(report.paper_orders_enabled).lower())
    table.add_row("Live orders enabled", str(report.live_orders_enabled).lower())
    table.add_row("Live route possible", str(report.live_route_possible).lower())
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    table.add_row("Existing open orders", str(report.existing_open_order_count))
    table.add_row(
        "Duplicate open order",
        str(report.duplicate_open_order_detected).lower(),
    )
    table.add_row("Limit price", str(report.limit_price or "n/a"))
    table.add_row("Notional", str(report.notional or "n/a"))
    table.add_row("Order ID", str(report.order_id or "n/a"))
    table.add_row("Perm ID", str(report.perm_id or "n/a"))
    table.add_row("Order status", report.order_status or "n/a")
    table.add_row("Fill quantity", str(report.fill_quantity))
    table.add_row("Cancel requested", str(report.cancel_requested).lower())
    table.add_row("Canceled", str(report.canceled).lower())
    console.print(table)

    if report.account_ids_masked:
        console.print(
            "Masked accounts: "
            + ", ".join(escape(account) for account in report.account_ids_masked)
        )
    if report.quote is not None:
        console.print(
            "Quote: "
            f"bid={report.quote.bid or 'n/a'} "
            f"ask={report.quote.ask or 'n/a'} "
            f"last={report.quote.last or 'n/a'} "
            f"stale={str(report.quote.stale).lower()}"
        )
    if report.callback_timeline:
        callback_table = Table(title="Order Callback Timeline")
        callback_table.add_column("Event")
        callback_table.add_column("Order ID")
        callback_table.add_column("Perm ID")
        callback_table.add_column("Status")
        callback_table.add_column("Message")
        for event in report.callback_timeline:
            callback_table.add_row(
                event.event_type,
                str(event.order_id or "n/a"),
                str(event.perm_id or "n/a"),
                event.status or "n/a",
                event.message or "",
            )
        console.print(callback_table)
    if report.warnings:
        console.print("[yellow]Paper order smoke warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Paper order smoke errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_alpha_paper_run_result(report: AlphaPaperRunReport) -> None:
    table = Table(title="Alpha Paper Run")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Mode", report.mode)
    table.add_row("Host", report.host)
    table.add_row("Port", str(report.port))
    table.add_row("Client ID", str(report.client_id))
    table.add_row(
        "Shadow report verified",
        str(report.alpha_shadow_report_verified).lower(),
    )
    table.add_row(
        "Paper smoke report verified",
        str(report.paper_smoke_report_verified).lower(),
    )
    table.add_row("Shadow signal", report.shadow_signal or "n/a")
    table.add_row("Risk approved", str(report.risk_approved).lower())
    table.add_row("No-trade reason", report.no_trade_reason or "n/a")
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Paper orders enabled", str(report.paper_orders_enabled).lower())
    table.add_row("Live orders enabled", str(report.live_orders_enabled).lower())
    table.add_row("Live route possible", str(report.live_route_possible).lower())
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    table.add_row("Order ID", str(report.order_id or "n/a"))
    table.add_row("Perm ID", str(report.perm_id or "n/a"))
    table.add_row("Order status", report.order_status or "n/a")
    table.add_row("Fill quantity", str(report.fill_quantity))
    table.add_row("Cancel requested", str(report.cancel_requested).lower())
    table.add_row("Canceled", str(report.canceled).lower())
    console.print(table)

    if report.account_ids_masked:
        console.print(
            "Masked accounts: "
            + ", ".join(escape(account) for account in report.account_ids_masked)
        )
    if report.source_report_paths:
        source_table = Table(title="Source Reports")
        source_table.add_column("Report")
        source_table.add_column("Path")
        for label, path in sorted(report.source_report_paths.items()):
            source_table.add_row(label, path)
        console.print(source_table)
    if report.warnings:
        console.print("[yellow]Alpha paper warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Alpha paper errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_paper_reconcile_result(report: PaperReconcileReport) -> None:
    table = Table(title="Paper Reconciliation")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Mode", report.mode)
    table.add_row("Host", report.host)
    table.add_row("Port", str(report.port))
    table.add_row("Client ID", str(report.client_id))
    table.add_row("Broker connected", str(report.broker_connected).lower())
    table.add_row("Account verified", str(report.account_summary_verified).lower())
    table.add_row("Account source", report.account_summary_source)
    table.add_row("Positions available", str(report.broker_positions_available).lower())
    table.add_row("Open orders", str(report.open_order_count))
    table.add_row("Latest order IDs", _format_ints(report.latest_order_ids))
    table.add_row("Latest perm IDs", _format_ints(report.latest_perm_ids))
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Paper orders enabled", str(report.paper_orders_enabled).lower())
    table.add_row(
        "Configured ALLOW_PAPER_ORDERS",
        str(report.configured_allow_paper_orders).lower(),
    )
    table.add_row("Live orders enabled", str(report.live_orders_enabled).lower())
    table.add_row("Read-Only API expected", str(report.read_only_api_expected).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    console.print(table)

    if report.account_ids_masked:
        console.print(
            "Masked accounts: "
            + ", ".join(escape(account) for account in report.account_ids_masked)
        )
    if report.open_orders:
        open_table = Table(title="Broker Open Orders")
        open_table.add_column("Order ID")
        open_table.add_column("Perm ID")
        open_table.add_column("Symbol")
        open_table.add_column("Action")
        open_table.add_column("Status")
        for open_order in report.open_orders:
            open_table.add_row(
                str(open_order.order_id),
                str(open_order.perm_id or "n/a"),
                open_order.symbol,
                open_order.action or "n/a",
                open_order.status or "n/a",
            )
        console.print(open_table)
    if report.latest_order_evidence:
        evidence_table = Table(title="Latest Local Order Evidence")
        evidence_table.add_column("Source")
        evidence_table.add_column("Status")
        evidence_table.add_column("Order ID")
        evidence_table.add_column("Perm ID")
        evidence_table.add_column("Fill Qty")
        evidence_table.add_column("Canceled")
        for evidence in report.latest_order_evidence:
            evidence_table.add_row(
                evidence.source,
                evidence.final_status or "unknown",
                str(evidence.order_id or "n/a"),
                str(evidence.perm_id or "n/a"),
                str(evidence.fill_quantity or "n/a"),
                str(evidence.canceled).lower(),
            )
        console.print(evidence_table)
    if report.source_report_paths:
        source_table = Table(title="Source Reports")
        source_table.add_column("Report")
        source_table.add_column("Path")
        for label, path in sorted(report.source_report_paths.items()):
            source_table.add_row(label, path)
        console.print(source_table)
    if report.warnings:
        console.print("[yellow]Paper reconciliation warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Paper reconciliation errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_alpha_test_summary_result(report: AlphaTestSummaryReport) -> None:
    table = Table(title="Alpha Test Summary")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Commit SHA", report.commit_sha or "unknown")
    table.add_row("Alpha shadow verified", str(report.alpha_shadow_verified).lower())
    table.add_row("Paper smoke verified", str(report.paper_smoke_verified).lower())
    table.add_row("Alpha paper verified", str(report.alpha_paper_verified).lower())
    table.add_row("Paper reconcile verified", str(report.paper_reconcile_verified).lower())
    table.add_row("Account verified", str(report.account_summary_verified).lower())
    table.add_row(
        "Open orders",
        str(report.open_order_count) if report.open_order_count is not None else "unknown",
    )
    table.add_row("Latest order IDs", _format_ints(report.latest_order_ids))
    table.add_row("Latest perm IDs", _format_ints(report.latest_perm_ids))
    table.add_row("Paper smoke status", report.paper_smoke_order_status or "n/a")
    table.add_row(
        "Paper smoke fill qty",
        str(report.paper_smoke_fill_quantity or "n/a"),
    )
    table.add_row(
        "Paper smoke canceled",
        _format_optional_bool(report.paper_smoke_canceled),
    )
    table.add_row("Alpha paper status", report.alpha_paper_order_status or "n/a")
    table.add_row(
        "Alpha paper fill qty",
        str(report.alpha_paper_fill_quantity or "n/a"),
    )
    table.add_row(
        "Alpha paper canceled",
        _format_optional_bool(report.alpha_paper_canceled),
    )
    table.add_row("Source submitted orders", str(report.submitted_orders).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Order API invoked by summary", str(report.order_api_invoked).lower())
    table.add_row(
        "Next alpha-window eligible",
        str(report.next_eligible_for_alpha_window).lower(),
    )
    console.print(table)

    if report.account_ids_masked:
        console.print(
            "Masked accounts: "
            + ", ".join(escape(account) for account in report.account_ids_masked)
        )
    if report.source_report_paths:
        source_table = Table(title="Source Reports")
        source_table.add_column("Report")
        source_table.add_column("Status")
        source_table.add_column("Path")
        for label, path in sorted(report.source_report_paths.items()):
            source_table.add_row(
                label,
                report.source_report_statuses.get(label, "unknown"),
                path,
            )
        console.print(source_table)
    if report.next_eligibility_reason:
        console.print("[bold]Next eligibility[/bold]")
        for reason in report.next_eligibility_reason:
            console.print(f"- {escape(reason)}")
    if report.warnings:
        console.print("[yellow]Alpha test summary warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Alpha test summary errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_paper_ledger_update_result(report: PaperLedgerUpdateReport) -> None:
    table = Table(title="Paper Ledger Update")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Commit SHA", report.commit_sha or "unknown")
    table.add_row("Campaign ID", report.campaign_id or "n/a")
    table.add_row("Ledger path", report.ledger_path)
    table.add_row("Entry written", str(report.ledger_entry_written).lower())
    table.add_row("Record count", str(report.ledger_record_count))
    table.add_row("Replaced existing", str(report.replaced_existing_entry).lower())
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Order routing", "disabled")
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    console.print(table)

    if report.ledger_entry is not None:
        entry_table = Table(title="Ledger Entry")
        entry_table.add_column("Field")
        entry_table.add_column("Value")
        entry_table.add_row("Open orders", str(report.ledger_entry.open_order_count))
        entry_table.add_row(
            "Positions query completed",
            str(report.ledger_entry.positions_query_completed).lower(),
        )
        entry_table.add_row(
            "Zero positions confirmed",
            str(report.ledger_entry.zero_positions_confirmed).lower(),
        )
        entry_table.add_row(
            "Account verified",
            str(report.ledger_entry.account_summary_verified).lower(),
        )
        entry_table.add_row(
            "Next eligible",
            str(report.ledger_entry.next_eligible_for_alpha_window).lower(),
        )
        entry_table.add_row(
            "Broker fingerprint",
            report.ledger_entry.broker_state_fingerprint or "missing",
        )
        entry_table.add_row(
            "Latest order IDs",
            _format_ints(report.ledger_entry.latest_order_ids),
        )
        entry_table.add_row(
            "Latest perm IDs",
            _format_ints(report.ledger_entry.latest_perm_ids),
        )
        console.print(entry_table)
    if report.source_report_paths:
        source_table = Table(title="Source Reports")
        source_table.add_column("Report")
        source_table.add_column("Path")
        for label, path in sorted(report.source_report_paths.items()):
            source_table.add_row(label, path)
        console.print(source_table)
    if report.warnings:
        console.print("[yellow]Paper ledger warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Paper ledger errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_alpha_campaign_run_result(report: AlphaCampaignRunReport) -> None:
    table = Table(title="Alpha Campaign Run")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Final status", _enum_value(report.final_status))
    table.add_row("Commit SHA", report.commit_sha or "unknown")
    table.add_row("Campaign ID", report.campaign_id or "n/a")
    table.add_row("Mode", _enum_value(report.mode))
    table.add_row("Stages", str(len(report.stages)))
    table.add_row("Alpha shadow completed", str(report.alpha_shadow_completed).lower())
    table.add_row("Alpha paper completed", str(report.alpha_paper_completed).lower())
    table.add_row("Paper reconcile completed", str(report.paper_reconcile_completed).lower())
    table.add_row("Alpha summary completed", str(report.alpha_test_summary_completed).lower())
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    table.add_row("Paper orders enabled at finish", str(report.paper_orders_enabled).lower())
    table.add_row("Read-Only restore required", str(report.read_only_restore_required).lower())
    console.print(table)

    if report.stages:
        stage_table = Table(title="Campaign Stages")
        stage_table.add_column("Stage")
        stage_table.add_column("Status")
        stage_table.add_column("OK")
        for stage in report.stages:
            stage_table.add_row(
                stage.name,
                _enum_value(stage.final_status),
                str(stage.ok).lower(),
            )
        console.print(stage_table)
    if report.report_paths:
        path_table = Table(title="Campaign Report Paths")
        path_table.add_column("Report")
        path_table.add_column("Path")
        for label, path in sorted(report.report_paths.items()):
            path_table.add_row(label, path)
        console.print(path_table)
    if report.warnings:
        console.print("[yellow]Alpha campaign warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Alpha campaign errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_broker_result(report: BrokerDiagnosticReport) -> None:
    table = Table(title="Broker Connectivity")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Config mode", report.mode)
    table.add_row("Host", report.host)
    table.add_row("Port", str(report.port))
    table.add_row("Client ID", str(report.client_id))
    table.add_row("Broker kind", report.broker_kind)
    table.add_row("ibapi import", "ok" if report.ibapi_available else "missing")
    table.add_row("Connection attempted", str(report.connection_attempted))
    table.add_row("Connected", str(report.connected))
    table.add_row(
        "Current time returned",
        str(report.server_time) if report.server_time else "unavailable",
    )
    table.add_row("Managed accounts returned", str(len(report.managed_accounts_masked)))
    table.add_row("Failure stage", report.failure_stage or "none")
    table.add_row("Order routing", "disabled")
    table.add_row("No order APIs invoked", "true")
    table.add_row("Final status", report.final_status)
    console.print(table)

    if report.ibapi_import_error:
        console.print(f"ibapi import error: {escape(report.ibapi_import_error)}")
    if report.managed_accounts_masked:
        accounts = ", ".join(
            account.account_id_masked for account in report.managed_accounts_masked
        )
        console.print(f"Managed accounts: {accounts}")
    if report.failure_stage:
        console.print(f"Diagnostic stage: {report.failure_stage}")
        console.print(f"Next step: {_broker_next_step(report)}")
    if report.warnings:
        console.print("[yellow]Warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Errors[/red]")
        for error in report.errors:
            code = f"IBKR {error.code}: " if error.code is not None else ""
            console.print(f"- {escape(code + error.message)}")


def _print_market_data_result(report: MarketDataDiagnosticReport) -> None:
    table = Table(title="Market Data Connectivity")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Config mode", report.mode)
    table.add_row("Host", report.host)
    table.add_row("Port", str(report.port))
    table.add_row("Client ID", str(report.client_id))
    table.add_row("Broker kind", report.broker_kind)
    table.add_row("ibapi import", "ok" if report.ibapi_available else "missing")
    table.add_row("Connection attempted", str(report.connection_attempted))
    table.add_row("Connected", str(report.connected))
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Requested data type", _enum_value(report.market_data_type_requested))
    table.add_row("Historical requested", str(report.include_historical))
    table.add_row("Final status", report.final_status)
    table.add_row("Order routing", "disabled")
    table.add_row("No order APIs invoked", "true")
    console.print(table)

    quote_table = Table(title="Quotes")
    quote_table.add_column("Symbol")
    quote_table.add_column("Resolved")
    quote_table.add_column("Type")
    quote_table.add_column("Bid")
    quote_table.add_column("Ask")
    quote_table.add_column("Last")
    quote_table.add_column("Close")
    quote_table.add_column("Bid Size")
    quote_table.add_column("Ask Size")
    quote_table.add_column("Last Size")
    quote_table.add_column("Spread")
    quote_table.add_column("Spread bps")
    quote_table.add_column("Age")
    quote_table.add_column("Stale")

    resolutions = {item.symbol: item for item in report.contract_resolutions}
    spreads = {item.symbol: item for item in report.spread_diagnostics}
    quotes = {item.symbol: item for item in report.quote_snapshots}
    for symbol in report.symbols_requested:
        resolution = resolutions.get(symbol)
        quote = quotes.get(symbol)
        spread = spreads.get(symbol)
        received_type = (
            _enum_value(quote.market_data_type.received)
            if quote and quote.market_data_type.received
            else "n/a"
        )
        quote_age = (
            str(quote.quote_age_seconds)
            if quote and quote.quote_age_seconds is not None
            else "n/a"
        )
        quote_table.add_row(
            symbol,
            str(bool(resolution and resolution.resolved)),
            received_type,
            str(quote.bid) if quote and quote.bid is not None else "n/a",
            str(quote.ask) if quote and quote.ask is not None else "n/a",
            str(quote.last) if quote and quote.last is not None else "n/a",
            str(quote.close) if quote and quote.close is not None else "n/a",
            str(quote.bid_size) if quote and quote.bid_size is not None else "n/a",
            str(quote.ask_size) if quote and quote.ask_size is not None else "n/a",
            str(quote.last_size) if quote and quote.last_size is not None else "n/a",
            str(spread.spread) if spread and spread.spread is not None else "n/a",
            str(spread.spread_bps) if spread and spread.spread_bps is not None else "n/a",
            quote_age,
            str(quote.stale) if quote else "n/a",
        )
    console.print(quote_table)

    if report.include_historical:
        history_table = Table(title="Historical Bars")
        history_table.add_column("Symbol")
        history_table.add_column("OK")
        history_table.add_column("Bars")
        history_table.add_column("Start")
        history_table.add_column("End")
        for item in report.historical_data:
            history_table.add_row(
                item.symbol,
                str(item.ok),
                str(item.historical_bars_count),
                item.historical_start or "n/a",
                item.historical_end or "n/a",
            )
        console.print(history_table)

    if report.failure_stage:
        console.print(f"Diagnostic stage: {report.failure_stage}")
    if report.warnings:
        console.print("[yellow]Warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Errors[/red]")
        for error in report.errors:
            code = f"IBKR {error.code}: " if error.code is not None else ""
            console.print(f"- {escape(code + error.message)}")


def _print_commodity_universe_result(report: CommodityResearchUniverseReport) -> None:
    table = Table(title="Commodity Proxy Universe")
    table.add_column("Symbol")
    table.add_column("Category")
    table.add_column("SecType")
    table.add_column("Exchange")
    table.add_column("Currency")
    table.add_column("Exposure")
    for instrument in report.instruments:
        table.add_row(
            instrument.symbol,
            _enum_value(instrument.category),
            instrument.ibkr_sec_type,
            instrument.exchange,
            instrument.currency,
            instrument.underlying_exposure,
        )
    if not report.instruments:
        table.add_row("none", "n/a", "n/a", "n/a", "n/a", "n/a")
    console.print(table)

    safety = Table(title="Commodity Universe Safety")
    safety.add_column("Check")
    safety.add_column("Value")
    safety.add_row("Commodity proxy universe", str(report.commodity_proxy_universe).lower())
    safety.add_row("Direct futures contracts", "disabled")
    safety.add_row(
        "Direct futures data",
        str(report.direct_futures_data_enabled).lower(),
    )
    safety.add_row("Broker contacted", str(report.broker_contacted).lower())
    safety.add_row(
        "Signal evaluation enabled",
        str(report.signal_evaluation_enabled).lower(),
    )
    safety.add_row("Generated signals", str(report.generated_signals).lower())
    safety.add_row("Signal count", str(report.signal_count))
    safety.add_row("Order routing", "disabled")
    safety.add_row("Final status", report.final_status)
    console.print(safety)

    if report.warnings:
        console.print("[yellow]Commodity universe warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Commodity universe errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_history_index_result(report: HistoricalLoaderReport) -> None:
    table = Table(title="Snapshot Index")
    table.add_column("Symbol")
    table.add_column("Bar Size")
    table.add_column("What")
    table.add_column("Snapshot")
    table.add_column("Manifest Bars")
    table.add_column("Bars File")
    for entry in report.snapshots_discovered:
        table.add_row(
            entry.symbol,
            entry.bar_size,
            entry.what_to_show,
            entry.snapshot_timestamp,
            str(entry.manifest_bar_count),
            entry.bars_path,
        )
    console.print(table)
    console.print(f"Broker contacted: {str(report.broker_contacted).lower()}.")
    console.print(f"Final status: {report.final_status}")
    _print_loader_messages(report)


def _print_history_load_result(report: HistoricalLoaderReport) -> None:
    table = Table(title="Loaded Historical Datasets")
    table.add_column("Symbol")
    table.add_column("Status")
    table.add_column("Bars")
    table.add_column("First")
    table.add_column("Last")
    table.add_column("Duplicates")
    table.add_column("Gaps")
    table.add_column("Zero Vol")
    table.add_column("Zero Samples")
    table.add_column("Avg Vol")
    table.add_column("Avg $ Vol")
    table.add_column("Malformed")
    table.add_column("Invalid OHLC")
    table.add_column("Negative Vol")
    for summary in report.summaries:
        table.add_row(
            summary.symbol,
            _enum_value(summary.load_status),
            str(summary.bars_count),
            summary.first_timestamp.isoformat() if summary.first_timestamp else "n/a",
            summary.last_timestamp.isoformat() if summary.last_timestamp else "n/a",
            str(summary.duplicate_timestamps_count),
            str(summary.missing_gap_count),
            str(summary.zero_volume_count),
            _format_sample_values(summary.zero_volume_sample_timestamps),
            _format_decimal(summary.average_volume),
            _format_decimal(summary.average_dollar_volume),
            str(summary.malformed_line_count),
            str(summary.invalid_ohlc_count),
            str(summary.negative_volume_count),
        )
    console.print(table)
    _print_zero_volume_samples(report.summaries)
    if report.results and not report.summaries:
        for result in report.results:
            console.print(f"{result.symbol}: {_enum_value(result.load_status)}")
    console.print(f"Broker contacted: {str(report.broker_contacted).lower()}.")
    console.print(f"Final status: {report.final_status}")
    _print_loader_messages(report)


def _print_data_quality_gate_result(report: DataQualityGateReport) -> None:
    table = Table(title="Data Quality Gate")
    table.add_column("Symbol")
    table.add_column("Status")
    table.add_column("Bars")
    table.add_column("Zero Vol")
    table.add_column("Zero Samples")
    table.add_column("Avg Vol")
    table.add_column("Avg $ Vol")
    table.add_column("Duplicates")
    table.add_column("Gaps")
    table.add_column("Invalid OHLC")
    table.add_column("Negative Vol")
    for result in report.results:
        table.add_row(
            result.symbol,
            _enum_value(result.status),
            str(result.bars_count),
            str(result.zero_volume_bars),
            _format_sample_values(result.zero_volume_sample_timestamps),
            _format_decimal(result.average_volume),
            _format_decimal(result.average_dollar_volume),
            str(result.duplicate_timestamps_count),
            str(result.missing_gap_count),
            str(result.invalid_ohlc_count),
            str(result.negative_volume_count),
        )
    console.print(table)
    _print_zero_volume_samples(report.results)
    console.print(f"Broker contacted: {str(report.broker_contacted).lower()}.")
    console.print(f"Final status: {_enum_value(report.final_status)}")
    if report.warnings:
        console.print("[yellow]Data-quality warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Data-quality errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_loader_messages(report: HistoricalLoaderReport) -> None:
    if report.warnings:
        console.print("[yellow]Loader warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Loader errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_history_snapshot_result(report: HistoricalSnapshotReport) -> None:
    table = Table(title="Historical Snapshot")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Config mode", report.mode)
    table.add_row("Host", report.host)
    table.add_row("Port", str(report.port))
    table.add_row("Client ID", str(report.client_id))
    table.add_row("Broker kind", report.broker_kind)
    table.add_row("ibapi import", "ok" if report.ibapi_available else "missing")
    table.add_row("Connection attempted", str(report.connection_attempted))
    table.add_row("Connected", str(report.connected))
    table.add_row("Symbols", ", ".join(report.symbols_requested))
    table.add_row("Duration", report.request.duration)
    table.add_row("Bar size", report.request.bar_size)
    table.add_row("What to show", report.request.what_to_show)
    table.add_row("Use RTH", str(report.request.use_rth))
    table.add_row("Final status", report.final_status)
    table.add_row("Order routing", "disabled")
    table.add_row("No order APIs invoked", "true")
    console.print(table)

    result_table = Table(title="Snapshot Files")
    result_table.add_column("Symbol")
    result_table.add_column("OK")
    result_table.add_column("Contract")
    result_table.add_column("Bars")
    result_table.add_column("First")
    result_table.add_column("Last")
    result_table.add_column("Snapshot")
    result_table.add_column("Manifest")
    for result in report.results:
        manifest = result.manifest
        result_table.add_row(
            result.symbol,
            str(result.ok),
            str(result.contract_resolution.contract_id)
            if result.contract_resolution and result.contract_resolution.contract_id
            else "n/a",
            str(len(result.bars)),
            manifest.first_bar_time if manifest and manifest.first_bar_time else "n/a",
            manifest.last_bar_time if manifest and manifest.last_bar_time else "n/a",
            result.snapshot_path or "n/a",
            result.manifest_path or "n/a",
        )
    console.print(result_table)

    if report.failure_stage:
        console.print(f"Diagnostic stage: {report.failure_stage}")
    if report.warnings:
        console.print("[yellow]Warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Errors[/red]")
        for error in report.errors:
            code = f"IBKR {error.code}: " if error.code is not None else ""
            console.print(f"- {escape(code + error.message)}")


def _print_history_readiness_result(report: HistoricalReadinessReport) -> None:
    table = Table(title="Historical Readiness")
    table.add_column("Symbol")
    table.add_column("Status")
    table.add_column("Bars")
    table.add_column("First")
    table.add_column("Last")
    table.add_column("Sorted")
    table.add_column("Duplicates")
    table.add_column("Gaps")
    table.add_column("Zero Vol")
    table.add_column("Zero Samples")
    table.add_column("Invalid OHLC")
    table.add_column("Negative Vol")
    table.add_column("Stale")
    for summary in report.summaries:
        table.add_row(
            summary.symbol,
            _enum_value(summary.readiness_status),
            str(summary.bars_count),
            summary.first_timestamp or "n/a",
            summary.last_timestamp or "n/a",
            str(summary.sorted_timestamps),
            str(summary.duplicate_timestamps_count),
            str(len(summary.missing_timestamp_gaps)),
            str(summary.zero_volume_bars),
            _format_sample_values(summary.zero_volume_sample_timestamps),
            str(summary.invalid_ohlc_bars),
            str(summary.negative_volume_bars),
            str(summary.stale_snapshot),
        )
    console.print(table)
    _print_zero_volume_samples(report.summaries)
    console.print(f"Final status: {report.final_status}")
    console.print("Order routing: disabled.")
    console.print("No order APIs invoked.")
    if report.warnings:
        console.print("[yellow]Readiness warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Readiness errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")


def _print_ibkr_data_diagnostics_result(report: IBKRDataDiagnosticsReport) -> None:
    table = Table(title="Strict SPY Shadow Precheck")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Symbol", report.symbol)
    table.add_row("Data policy", _enum_value(report.data_policy))
    table.add_row("Delayed data mode", str(report.delayed_data_mode))
    table.add_row("Graduation eligible", str(report.graduation_eligible))
    table.add_row("Non-graduating reason", report.non_graduating_reason or "n/a")
    table.add_row("Broker probe OK", str(report.broker_probe_ok))
    table.add_row("Broker connected", str(report.broker_connected))
    table.add_row("Account verified", str(report.broker_account_verified))
    table.add_row("History snapshot OK", str(report.history_snapshot_ok))
    table.add_row("History readiness OK", str(report.history_readiness_ok))
    table.add_row("Bars", f"{report.bar_count} / {report.min_bars}")
    table.add_row("Bar count passed", str(report.bar_count_passed))
    table.add_row("First bar", report.first_bar_timestamp or "n/a")
    table.add_row("Latest bar", report.latest_bar_timestamp or "n/a")
    latest_age = (
        f"{report.latest_bar_age_minutes:.2f} minutes"
        if report.latest_bar_age_minutes is not None
        else "n/a"
    )
    table.add_row("Latest bar age", latest_age)
    table.add_row("Freshness gate", f"<= {report.stale_after_minutes} minutes")
    table.add_row("Freshness passed", str(report.freshness_passed))
    table.add_row("Market-data type requested", report.market_data_type_requested or "n/a")
    table.add_row("Market-data type received", report.market_data_type_received or "n/a")
    table.add_row("Market-data hint", report.market_data_type_hint)
    table.add_row("Market probe OK", str(report.market_probe_ok))
    table.add_row("Market probe status", report.market_probe_final_status or "n/a")
    table.add_row("Market-data permission blocker", str(report.market_data_permission_blocker))
    table.add_row("Market-data permission hint", report.market_data_permission_hint or "n/a")
    table.add_row("Strict precheck passed", str(report.strict_shadow_precheck_passed))
    table.add_row("Delayed precheck passed", str(report.delayed_shadow_precheck_passed))
    table.add_row("Next action", report.next_recommended_action)
    table.add_row("Submitted orders", str(report.submitted_orders).lower())
    table.add_row("Order API invoked", str(report.order_api_invoked).lower())
    table.add_row("Broker contacted", str(report.broker_contacted).lower())
    table.add_row("Final status", _enum_value(report.final_status))
    console.print(table)

    if report.operator_hints:
        console.print("[bold]Operator hints[/bold]")
        for hint in report.operator_hints:
            console.print(f"- {escape(hint)}")
    if report.warnings:
        console.print("[yellow]Diagnostics warnings[/yellow]")
        for warning in report.warnings:
            console.print(f"- {escape(warning)}")
    if report.market_probe_warnings:
        console.print("[yellow]Market-probe warnings[/yellow]")
        for warning in report.market_probe_warnings:
            console.print(f"- {escape(warning)}")
    if report.errors:
        console.print("[red]Diagnostics errors[/red]")
        for error in report.errors:
            console.print(f"- {escape(error)}")
    if report.market_probe_errors:
        console.print("[red]Market-probe errors[/red]")
        for error in report.market_probe_errors:
            console.print(f"- {escape(error)}")


def _broker_next_step(report: BrokerDiagnosticReport) -> str:
    if report.failure_stage == "dependency_check":
        return "Install or repair ibapi, then rerun scripts/check-ibapi.sh."
    if report.failure_stage == "socket_connect":
        return (
            "Confirm paper TWS/Gateway is running, API socket clients are enabled, "
            "the port is paper-only, localhost is allowed, and client ID is unique."
        )
    if report.failure_stage == "current_time_request":
        return "Confirm the API session is fully ready and rerun broker-probe."
    if report.failure_stage == "managed_accounts_request":
        return "Confirm the session permits read-only managed account discovery."
    if report.failure_stage == "timeout":
        return (
            "Check API settings, duplicate client IDs, firewall/localhost access, "
            "and increase --timeout if TWS/Gateway is slow."
        )
    if report.failure_stage == "config_validation":
        return "Fix rejected config before attempting a broker socket."
    return "Inspect errors and rerun after correcting the reported blocker."


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _format_sample_values(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_ints(values: list[int]) -> str:
    return ", ".join(str(value) for value in values) if values else "none"


def _format_optional_bool(value: bool | None) -> str:
    return "n/a" if value is None else str(value).lower()


def _format_decimal(value: Decimal | None) -> str:
    return "n/a" if value is None else str(value)


def _parse_decimal_option(value: str, option_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        console.print(f"[red]{option_name} must be a decimal number.[/red]")
        raise typer.Exit(code=2) from None
    if parsed < 0:
        console.print(f"[red]{option_name} must be non-negative.[/red]")
        raise typer.Exit(code=2)
    return parsed


def _parse_bool_option(value: str, option_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    console.print(f"[red]{option_name} must be true or false.[/red]")
    raise typer.Exit(code=2)


def _print_zero_volume_samples(items: list[Any]) -> None:
    rows = [
        (
            str(item.symbol),
            list(item.zero_volume_sample_timestamps),
        )
        for item in items
        if item.zero_volume_sample_timestamps
    ]
    if not rows:
        return

    console.print("[yellow]Zero-volume samples[/yellow]")
    for symbol, samples in rows:
        console.print(
            f"- {escape(symbol)} sample timestamps: {escape(', '.join(samples))}"
        )


def _format_optional_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    app()
