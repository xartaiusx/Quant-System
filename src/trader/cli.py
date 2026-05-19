"""Command-line interface for safe dry-run trading workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from trader.broker.account import AccountClient
from trader.broker.ibkr_client import IBKRClient
from trader.config import ConfigError, TraderConfig, load_config
from trader.data.snapshots import deterministic_history, deterministic_quotes, mock_positions
from trader.data.universe import parse_symbols
from trader.execution.router import ExecutionRouter
from trader.models import (
    BrokerDiagnosticReport,
    MarketDataDiagnosticReport,
    MarketDataRequestType,
    MarketQuote,
    RiskDecision,
)
from trader.portfolio.construction import build_trade_plans
from trader.reporting.journal import Journal
from trader.risk.rules import evaluate_trade_plans
from trader.strategy import get_strategy

app = typer.Typer(
    help="Safety-first IBKR quantitative trading foundation. No command places orders.",
    no_args_is_help=True,
)
console = Console()


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
    result = IBKRClient(config).preflight(attempt_connection=connect, timeout=timeout)
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
    report = IBKRClient(config).diagnostic_report(timeout=timeout)
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
    report = IBKRClient(config).market_data_diagnostic(
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
        report = IBKRClient(config).diagnostic_report(
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

    snapshot = AccountClient(config).snapshot()
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
        report = IBKRClient(config).diagnostic_report(
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

    snapshots = AccountClient(config).positions()
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
    account = AccountClient(config).snapshot()
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


def _report_dict(report: BrokerDiagnosticReport | MarketDataDiagnosticReport) -> dict[str, Any]:
    return report.model_dump(mode="json")


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
