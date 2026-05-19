"""Command-line interface for safe dry-run trading workflows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from trader.backtest.data_adapter import build_backtest_feed, build_backtest_feed_report
from trader.backtest.engine import build_backtest_run_report
from trader.config import ConfigError, TraderConfig, load_config
from trader.data.historical import (
    attach_snapshot_paths,
    build_readiness_report,
    write_historical_snapshot_result,
)
from trader.data.historical_loader import (
    build_history_index_report,
    load_historical_snapshots,
)
from trader.data.snapshots import deterministic_history, deterministic_quotes, mock_positions
from trader.data.universe import parse_symbols
from trader.execution.router import ExecutionRouter
from trader.models import (
    BacktestAlignmentMode,
    BacktestDataAdapterReport,
    BacktestDataAdapterRequest,
    BacktestRunReport,
    BacktestRunRequest,
    BrokerDiagnosticReport,
    HistoricalLoaderReport,
    HistoricalReadinessReport,
    HistoricalSnapshotLoadRequest,
    HistoricalSnapshotReport,
    MarketDataDiagnosticReport,
    MarketDataRequestType,
    MarketQuote,
    RiskDecision,
    StrategyContractReport,
    StrategyContractValidationRequest,
)
from trader.portfolio.construction import build_trade_plans
from trader.reporting.journal import Journal
from trader.risk.rules import evaluate_trade_plans
from trader.strategy import get_strategy
from trader.strategy.interface import build_strategy_contract_report

app = typer.Typer(
    help="Safety-first IBKR quantitative trading foundation. No command places orders.",
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


def _validate_use_rth_option(use_rth: int) -> int:
    if use_rth not in {0, 1}:
        console.print("[red]--use-rth must be 0 or 1.[/red]")
        raise typer.Exit(code=2)
    return use_rth


def _report_dict(
    report: (
        BacktestDataAdapterReport
        | BacktestRunReport
        | BrokerDiagnosticReport
        | HistoricalLoaderReport
        | HistoricalReadinessReport
        | HistoricalSnapshotReport
        | MarketDataDiagnosticReport
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
            str(summary.malformed_line_count),
            str(summary.invalid_ohlc_count),
            str(summary.negative_volume_count),
        )
    console.print(table)
    if report.results and not report.summaries:
        for result in report.results:
            console.print(f"{result.symbol}: {_enum_value(result.load_status)}")
    console.print(f"Broker contacted: {str(report.broker_contacted).lower()}.")
    console.print(f"Final status: {report.final_status}")
    _print_loader_messages(report)


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
            str(summary.invalid_ohlc_bars),
            str(summary.negative_volume_bars),
            str(summary.stale_snapshot),
        )
    console.print(table)
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


if __name__ == "__main__":
    app()
