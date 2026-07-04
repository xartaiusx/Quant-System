"""Markdown report formatting."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def markdown_summary(payload: Mapping[str, Any]) -> str:
    """Render a compact Markdown summary for a cycle payload."""

    if payload.get("report_type") == "broker_probe":
        return broker_probe_markdown(payload)
    if payload.get("report_type") == "account_summary":
        return account_summary_markdown(payload)
    if payload.get("report_type") == "market_probe":
        return market_probe_markdown(payload)
    if payload.get("report_type") == "history_snapshot":
        return history_snapshot_markdown(payload)
    if payload.get("report_type") == "history_readiness":
        return history_readiness_markdown(payload)
    if payload.get("report_type") == "history_index":
        return history_index_markdown(payload)
    if payload.get("report_type") == "history_load":
        return history_load_markdown(payload)
    if payload.get("report_type") == "data_quality_gate":
        return data_quality_gate_markdown(payload)
    if payload.get("report_type") == "backtest_feed":
        return backtest_feed_markdown(payload)
    if payload.get("report_type") == "backtest_run":
        return backtest_run_markdown(payload)
    if payload.get("report_type") == "strategy_contract":
        return strategy_contract_markdown(payload)
    if payload.get("report_type") == "strategy_runner":
        return strategy_runner_markdown(payload)
    if payload.get("report_type") == "signal_contract":
        return signal_contract_markdown(payload)
    if payload.get("report_type") == "signal_runner":
        return signal_runner_markdown(payload)
    if payload.get("report_type") == "signal_evaluation":
        return signal_evaluation_markdown(payload)
    if payload.get("report_type") == "evaluator_comparison":
        return evaluator_comparison_markdown(payload)
    if payload.get("report_type") == "commodity_universe":
        return commodity_universe_markdown(payload)
    if payload.get("report_type") == "paper_readiness_run":
        return paper_readiness_run_markdown(payload)
    if payload.get("report_type") == "alpha_shadow_run":
        return alpha_shadow_run_markdown(payload)
    if payload.get("report_type") == "paper_order_smoke":
        return paper_order_smoke_markdown(payload)
    if payload.get("report_type") == "alpha_paper_run":
        return alpha_paper_run_markdown(payload)

    lines = [
        f"# {payload.get('title', 'Trading Report')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Mode: `{payload.get('config', {}).get('trading_mode', 'unknown')}`",
        f"- Universe: `{', '.join(payload.get('config', {}).get('universe', []))}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        "",
        "## Counts",
        "",
        f"- Signals: `{len(payload.get('signals', []))}`",
        f"- Plans: `{len(payload.get('plans', []))}`",
        f"- Risk decisions: `{len(payload.get('risk_decisions', []))}`",
        f"- Execution results: `{len(payload.get('execution_results', []))}`",
        "",
        "## Warnings",
        "",
    ]
    warnings = payload.get("warnings", [])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    blocked = [
        decision
        for decision in payload.get("risk_decisions", [])
        if not decision.get("approved", False)
    ]
    if blocked:
        lines.extend(["", "## Blockers", ""])
        lines.extend(
            f"- `{decision.get('symbol')}`: `{decision.get('blocked_reason')}`"
            for decision in blocked
        )

    return "\n".join(lines) + "\n"


def broker_probe_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-probe specific Markdown report."""

    errors = payload.get("errors", [])
    warnings = payload.get("warnings", [])
    managed_accounts = payload.get("managed_accounts_masked", [])
    time_probe = payload.get("time_probe") or {}

    lines = [
        f"# {payload.get('title', 'Read-only Broker Probe')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Broker kind: `{payload.get('broker_kind', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- ibapi available: `{payload.get('ibapi_available', False)}`",
        f"- ibapi import error: `{payload.get('ibapi_import_error')}`",
        f"- Connection attempted: `{payload.get('connection_attempted', False)}`",
        f"- Connected: `{payload.get('connected', False)}`",
        f"- Failure stage: `{payload.get('failure_stage') or 'none'}`",
        f"- Server time: `{payload.get('server_time') or time_probe.get('server_time')}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', False)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## No-Order Guarantee",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report is read-only and no orders were routed.",
            )
        ),
        "",
        "No order APIs invoked.",
        "",
        "## Managed Accounts",
        "",
    ]
    if managed_accounts:
        for account in managed_accounts:
            if isinstance(account, Mapping):
                lines.append(f"- `{account.get('account_id_masked', 'masked')}`")
            else:
                lines.append(f"- `{account}`")
    else:
        lines.append("- None returned")

    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Errors", ""])
    if errors:
        for error in errors:
            if isinstance(error, Mapping):
                code = error.get("code")
                prefix = f"IBKR {code}: " if code is not None else ""
                lines.append(f"- {prefix}{error.get('message', 'unknown error')}")
            else:
                lines.append(f"- {error}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def account_summary_markdown(payload: Mapping[str, Any]) -> str:
    """Render a read-only account-summary report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    account_ids = payload.get("account_ids_masked", [])
    account_fields = payload.get("account_summary_fields_by_account", {})

    lines = [
        f"# {payload.get('title', 'Read-only Broker Account Summary')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'account --connect')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Account summary verified: `{payload.get('account_summary_verified', False)}`",
        f"- Account summary source: `{payload.get('account_summary_source', 'unknown')}`",
        f"- Broker connected: `{payload.get('broker_connected', False)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', False)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', False)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', False)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Masked Accounts",
        "",
    ]
    if account_ids:
        for account_id in account_ids:
            fields = (
                account_fields.get(account_id, [])
                if isinstance(account_fields, Mapping)
                else []
            )
            lines.append(f"- `{account_id}` fields=`{', '.join(fields)}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def market_probe_markdown(payload: Mapping[str, Any]) -> str:
    """Render a read-only market-probe specific Markdown report."""

    errors = payload.get("errors", [])
    warnings = payload.get("warnings", [])
    quotes = payload.get("quote_snapshots", [])
    resolutions = payload.get("contract_resolutions", [])
    spreads = payload.get("spread_diagnostics", [])
    historical = payload.get("historical_data", [])

    lines = [
        f"# {payload.get('title', 'Read-only Market Data Probe')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Broker kind: `{payload.get('broker_kind', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- Symbols: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Data type requested: `{payload.get('market_data_type_requested', 'unknown')}`",
        f"- Historical requested: `{payload.get('include_historical', False)}`",
        f"- Connected: `{payload.get('connected', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', False)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## No-Order Guarantee",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This market-data report is read-only and no orders were routed.",
            )
        ),
        "",
        "No order APIs invoked.",
        "",
        "## Contract Resolution",
        "",
    ]
    if resolutions:
        for item in resolutions:
            lines.append(
                "- "
                f"`{item.get('symbol')}` resolved=`{item.get('resolved')}` "
                f"ambiguous=`{item.get('ambiguous')}` "
                f"contract=`{item.get('selected_contract_description')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Quotes", ""])
    if quotes:
        spread_by_symbol = {
            item.get("symbol"): item for item in spreads if isinstance(item, Mapping)
        }
        for quote in quotes:
            symbol = quote.get("symbol")
            spread = spread_by_symbol.get(symbol, {})
            market_type = quote.get("market_data_type", {})
            lines.append(
                "- "
                f"`{symbol}` type=`{market_type.get('received')}` "
                f"bid=`{quote.get('bid')}` ask=`{quote.get('ask')}` "
                f"last=`{quote.get('last')}` close=`{quote.get('close')}` "
                f"spread=`{spread.get('spread')}` spread_bps=`{spread.get('spread_bps')}` "
                f"stale=`{quote.get('stale')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Historical Data", ""])
    if historical:
        for item in historical:
            lines.append(
                "- "
                f"`{item.get('symbol')}` ok=`{item.get('ok')}` "
                f"bars=`{item.get('historical_bars_count')}` "
                f"start=`{item.get('historical_start')}` end=`{item.get('historical_end')}`"
            )
    else:
        lines.append("- Not requested or unavailable")

    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Errors", ""])
    if errors:
        for error in errors:
            if isinstance(error, Mapping):
                code = error.get("code")
                prefix = f"IBKR {code}: " if code is not None else ""
                lines.append(f"- {prefix}{error.get('message', 'unknown error')}")
            else:
                lines.append(f"- {error}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def history_snapshot_markdown(payload: Mapping[str, Any]) -> str:
    """Render a read-only historical snapshot report."""

    request = payload.get("request", {})
    results = payload.get("results", [])
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])

    lines = [
        f"# {payload.get('title', 'Read-only Historical Snapshot')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Broker kind: `{payload.get('broker_kind', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- Symbols: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Duration: `{request.get('duration', 'unknown')}`",
        f"- Bar size: `{request.get('bar_size', 'unknown')}`",
        f"- What to show: `{request.get('what_to_show', 'unknown')}`",
        f"- Use RTH: `{request.get('use_rth', 'unknown')}`",
        f"- Connected: `{payload.get('connected', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', False)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## No-Order Guarantee",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This historical snapshot report is read-only and no orders were routed.",
            )
        ),
        "",
        "No order APIs invoked.",
        "",
        "## Snapshots",
        "",
    ]
    if results:
        for result in results:
            manifest = result.get("manifest") or {}
            lines.append(
                "- "
                f"`{result.get('symbol')}` ok=`{result.get('ok')}` "
                f"bars=`{len(result.get('bars', []))}` "
                f"first=`{manifest.get('first_bar_time')}` "
                f"last=`{manifest.get('last_bar_time')}` "
                f"snapshot=`{result.get('snapshot_path')}` "
                f"manifest=`{result.get('manifest_path')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Errors", ""])
    if errors:
        for error in errors:
            if isinstance(error, Mapping):
                code = error.get("code")
                prefix = f"IBKR {code}: " if code is not None else ""
                lines.append(f"- {prefix}{error.get('message', 'unknown error')}")
            else:
                lines.append(f"- {error}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def history_readiness_markdown(payload: Mapping[str, Any]) -> str:
    """Render a historical snapshot readiness report."""

    summaries = payload.get("summaries", [])
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])

    lines = [
        f"# {payload.get('title', 'Historical Snapshot Readiness')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Broker kind: `{payload.get('broker_kind', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- Symbols: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', False)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## No-Order Guarantee",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This readiness report is read-only and no orders were routed.",
            )
        ),
        "",
        "No order APIs invoked.",
        "",
        "## Readiness",
        "",
    ]
    if summaries:
        for summary in summaries:
            lines.append(
                "- "
                f"`{summary.get('symbol')}` status=`{summary.get('readiness_status')}` "
                f"bars=`{summary.get('bars_count')}` "
                f"first=`{summary.get('first_timestamp')}` "
                f"last=`{summary.get('last_timestamp')}` "
                f"duplicates=`{summary.get('duplicate_timestamps_count')}` "
                f"gaps=`{len(summary.get('missing_timestamp_gaps', []))}` "
                f"zero_volume=`{summary.get('zero_volume_bars')}` "
                "zero_samples="
                f"`{_sample_values(summary.get('zero_volume_sample_timestamps', []))}` "
                f"invalid_ohlc=`{summary.get('invalid_ohlc_bars')}` "
                f"negative_volume=`{summary.get('negative_volume_bars')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Errors", ""])
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def history_index_markdown(payload: Mapping[str, Any]) -> str:
    """Render an offline historical snapshot index report."""

    entries = payload.get("snapshots_discovered", [])
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    request = payload.get("request", {})
    lines = [
        f"# {payload.get('title', 'Offline Historical Snapshot Index')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'history-index')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Base data path: `{payload.get('base_data_path', 'data/historical')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Bar size filter: `{request.get('bar_size')}`",
        f"- What-to-show filter: `{request.get('what_to_show')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## No-Order Guarantee",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This offline report reads local files only and no orders were routed.",
            )
        ),
        "",
        "No order APIs invoked.",
        "",
        "## Snapshots",
        "",
    ]
    if entries:
        for entry in entries:
            lines.append(
                "- "
                f"`{entry.get('symbol')}` `{entry.get('bar_size')}` "
                f"`{entry.get('what_to_show')}` snapshot=`{entry.get('snapshot_timestamp')}` "
                f"manifest_bars=`{entry.get('manifest_bar_count')}` "
                f"bars=`{entry.get('bars_path')}`"
            )
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def history_load_markdown(payload: Mapping[str, Any]) -> str:
    """Render an offline historical snapshot load report."""

    summaries = payload.get("summaries", [])
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    request = payload.get("request", {})
    lines = [
        f"# {payload.get('title', 'Offline Historical Snapshot Loader')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'history-load')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Base data path: `{payload.get('base_data_path', 'data/historical')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Latest only: `{request.get('latest')}`",
        f"- Strict: `{request.get('strict')}`",
        f"- Bar size filter: `{request.get('bar_size')}`",
        f"- What-to-show filter: `{request.get('what_to_show')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## No-Order Guarantee",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This offline report reads local files only and no orders were routed.",
            )
        ),
        "",
        "No order APIs invoked.",
        "",
        "## Datasets",
        "",
    ]
    if summaries:
        for summary in summaries:
            lines.append(
                "- "
                f"`{summary.get('symbol')}` status=`{summary.get('load_status')}` "
                f"bars=`{summary.get('bars_count')}` "
                f"first=`{summary.get('first_timestamp')}` "
                f"last=`{summary.get('last_timestamp')}` "
                f"duplicates=`{summary.get('duplicate_timestamps_count')}` "
                f"gaps=`{summary.get('missing_gap_count')}` "
                f"zero_volume=`{summary.get('zero_volume_count')}` "
                "zero_samples="
                f"`{_sample_values(summary.get('zero_volume_sample_timestamps', []))}` "
                f"malformed=`{summary.get('malformed_line_count')}` "
                f"invalid_ohlc=`{summary.get('invalid_ohlc_count')}` "
                f"negative_volume=`{summary.get('negative_volume_count')}`"
            )
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def data_quality_gate_markdown(payload: Mapping[str, Any]) -> str:
    """Render an offline historical data-quality gate report."""

    request = payload.get("request", {})
    results = payload.get("results", [])
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])

    lines = [
        f"# {payload.get('title', 'Broker-free Data Quality Gate')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'data-quality-gate')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Loader final status: `{payload.get('loader_final_status', 'unknown')}`",
        f"- Readiness final status: `{payload.get('readiness_final_status', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Base data path: `{request.get('base_data_path', 'data/historical')}`",
        f"- Bar size filter: `{request.get('bar_size')}`",
        f"- What-to-show filter: `{request.get('what_to_show')}`",
        f"- Minimum bars: `{request.get('min_bars')}`",
        f"- Max zero-volume bars: `{request.get('max_zero_volume_bars')}`",
        f"- Minimum average volume: `{request.get('min_average_volume')}`",
        f"- Minimum average dollar volume: `{request.get('min_average_dollar_volume')}`",
        f"- Max missing gaps: `{request.get('max_missing_gap_count')}`",
        f"- Allow stale snapshot: `{request.get('allow_stale_snapshot')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Signal evaluation enabled: `{payload.get('signal_evaluation_enabled', True)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Signal count: `{payload.get('signal_count', 0)}`",
        f"- Order intents generated: `{payload.get('order_intents_generated', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        f"- Futures contracts enabled: `{payload.get('futures_contracts_enabled', True)}`",
        f"- Direct futures data enabled: `{payload.get('direct_futures_data_enabled', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This data-quality gate reads local historical snapshots only and "
                "does not contact a broker.",
            )
        ),
        "",
        "No order APIs invoked.",
        "",
        "## Symbol Gates",
        "",
    ]
    if results:
        for result in results:
            issue_codes = [
                issue.get("code", "unknown")
                for issue in result.get("issues", [])
                if isinstance(issue, Mapping)
            ]
            lines.append(
                "- "
                f"`{result.get('symbol')}` status=`{result.get('status')}` "
                f"bars=`{result.get('bars_count')}` "
                f"zero_volume=`{result.get('zero_volume_bars')}` "
                f"zero_samples=`{_sample_values(result.get('zero_volume_sample_timestamps', []))}` "
                f"avg_volume=`{result.get('average_volume')}` "
                f"avg_dollar_volume=`{result.get('average_dollar_volume')}` "
                f"duplicates=`{result.get('duplicate_timestamps_count')}` "
                f"gaps=`{result.get('missing_gap_count')}` "
                f"malformed=`{result.get('malformed_line_count')}` "
                f"invalid_ohlc=`{result.get('invalid_ohlc_count')}` "
                f"negative_volume=`{result.get('negative_volume_count')}` "
                f"stale=`{result.get('stale_snapshot')}` "
                f"issues=`{', '.join(issue_codes) if issue_codes else 'none'}`"
            )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def backtest_feed_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free backtest feed report."""

    request = payload.get("request", {})
    summary = payload.get("summary") or {}
    sources = payload.get("source_datasets", [])
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    missing = summary.get("missing_bars_by_symbol", {})
    duplicates = summary.get("duplicate_timestamps_by_symbol", {})

    lines = [
        f"# {payload.get('title', 'Broker-free Backtest Data Feed')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'backtest-feed')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Alignment mode: `{request.get('alignment_mode', 'union')}`",
        f"- Bar size filter: `{request.get('bar_size')}`",
        f"- What-to-show filter: `{request.get('what_to_show')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report reads local files only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_strategy_execution_statement",
                "No strategy evaluation, order simulation, or P&L calculation was performed.",
            )
        ),
        "",
        "## Feed Summary",
        "",
        f"- Feed status: `{summary.get('feed_status', 'unknown')}`",
        f"- Total bars: `{summary.get('total_bars', 0)}`",
        f"- Frame count: `{summary.get('frame_count', 0)}`",
        f"- First timestamp: `{summary.get('first_timestamp')}`",
        f"- Last timestamp: `{summary.get('last_timestamp')}`",
        "",
        "## Alignment Diagnostics",
        "",
    ]
    if summary.get("symbols"):
        for symbol in summary.get("symbols", []):
            lines.append(
                "- "
                f"`{symbol}` missing=`{missing.get(symbol, 0)}` "
                f"duplicates=`{duplicates.get(symbol, 0)}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Source Datasets", ""])
    if sources:
        for source in sources:
            lines.append(
                "- "
                f"`{source.get('symbol')}` status=`{source.get('load_status')}` "
                f"bars=`{source.get('bars_count')}` "
                f"snapshot=`{source.get('snapshot_timestamp')}` "
                f"bars_path=`{source.get('bars_path')}`"
            )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def backtest_run_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free backtest run report."""

    request = payload.get("request", {})
    diagnostics = payload.get("diagnostics") or {}
    feed_summary = payload.get("feed_summary") or {}
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    missing = diagnostics.get("missing_bars_by_symbol", {})

    lines = [
        f"# {payload.get('title', 'Broker-free Backtest Run')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'backtest-run')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Alignment mode: `{request.get('alignment_mode', 'union')}`",
        f"- Bar size filter: `{request.get('requested_bar_size')}`",
        f"- What-to-show filter: `{request.get('requested_what_to_show')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        f"- Strategy evaluated: `{payload.get('strategy_evaluated', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report reads local files only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "This run replayed data frames only. No strategy evaluation, "
                "order simulation, broker routing, or P&L calculation was performed.",
            )
        ),
        "",
        "## Run Summary",
        "",
        f"- Run status: `{diagnostics.get('run_status', 'unknown')}`",
        f"- Feed status: `{diagnostics.get('feed_status', 'unknown')}`",
        f"- Frame count: `{diagnostics.get('frame_count', 0)}`",
        f"- Observations: `{diagnostics.get('observations_count', 0)}`",
        f"- Total bars observed: `{diagnostics.get('total_bars_observed', 0)}`",
        f"- First timestamp: `{diagnostics.get('first_timestamp')}`",
        f"- Last timestamp: `{diagnostics.get('last_timestamp')}`",
        f"- Frames with missing bars: `{diagnostics.get('frames_with_missing_bars', 0)}`",
        "",
        "## Feed Summary",
        "",
        f"- Feed frames: `{feed_summary.get('frame_count', 0)}`",
        f"- Feed bars: `{feed_summary.get('total_bars', 0)}`",
        f"- Feed status: `{feed_summary.get('feed_status', 'unknown')}`",
        "",
        "## Missing Bars",
        "",
    ]
    if diagnostics.get("symbols"):
        for symbol in diagnostics.get("symbols", []):
            lines.append(f"- `{symbol}` missing=`{missing.get(symbol, 0)}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def strategy_contract_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free strategy contract report."""

    request = payload.get("request", {})
    metadata = payload.get("metadata", {})
    result = payload.get("result", {})
    feed_summary = payload.get("feed_summary") or {}
    sample = payload.get("frame_context_sample") or {}
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])

    lines = [
        f"# {payload.get('title', 'Broker-free Strategy Contract')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'strategy-contract')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Strategy: `{metadata.get('strategy_name', 'unknown')}`",
        f"- Strategy version: `{metadata.get('strategy_version', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Alignment mode: `{request.get('alignment_mode', 'union')}`",
        f"- Bar size filter: `{request.get('requested_bar_size')}`",
        f"- What-to-show filter: `{request.get('requested_what_to_show')}`",
        f"- Broker required: `{metadata.get('broker_required', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        f"- Evaluated: `{payload.get('evaluated', True)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Generated orders: `{payload.get('generated_orders', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report reads local files only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "This command validates the strategy interface contract only. No real "
                "strategy evaluation, signal generation, order simulation, broker "
                "routing, or P&L calculation was performed.",
            )
        ),
        "",
        "## Contract Summary",
        "",
        f"- Contexts observed: `{result.get('contexts_observed', 0)}`",
        f"- Diagnostics: `{len(payload.get('diagnostics', []))}`",
        f"- Required fields: `{', '.join(metadata.get('required_fields', []))}`",
        f"- Supported bar sizes: `{', '.join(metadata.get('supported_bar_sizes', []))}`",
        "",
        "## Feed Summary",
        "",
        f"- Feed status: `{feed_summary.get('feed_status', 'unknown')}`",
        f"- Feed frames: `{feed_summary.get('frame_count', 0)}`",
        f"- Feed bars: `{feed_summary.get('total_bars', 0)}`",
        "",
        "## Frame Context Sample",
        "",
    ]
    if sample:
        lines.extend(
            [
                f"- Timestamp: `{sample.get('timestamp')}`",
                f"- Frame index: `{sample.get('frame_index')}`",
                f"- Available symbols: `{', '.join(sample.get('available_symbols', []))}`",
                f"- Missing symbols: `{', '.join(sample.get('missing_symbols', []))}`",
            ]
        )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def strategy_runner_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free inert strategy runner report."""

    request = payload.get("request", {})
    metadata = payload.get("metadata", {})
    diagnostics = payload.get("diagnostics") or {}
    feed_summary = payload.get("feed_summary") or {}
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    missing = diagnostics.get("missing_symbols_by_symbol", {})

    lines = [
        f"# {payload.get('title', 'Broker-free Inert Strategy Runner')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'strategy-runner')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Strategy: `{metadata.get('strategy_name', 'unknown')}`",
        f"- Strategy version: `{metadata.get('strategy_version', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Alignment mode: `{request.get('alignment_mode', 'union')}`",
        f"- Bar size filter: `{request.get('requested_bar_size')}`",
        f"- What-to-show filter: `{request.get('requested_what_to_show')}`",
        f"- Diagnostic only: `{payload.get('diagnostic_only', False)}`",
        f"- No-op strategy observed: `{payload.get('noop_strategy_observed', False)}`",
        f"- Real strategy evaluated: `{payload.get('real_strategy_evaluated', True)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Generated orders: `{payload.get('generated_orders', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- Fills simulated: `{payload.get('fills_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        f"- Portfolio accounting: `{payload.get('portfolio_accounting', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report reads local files only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "This run exercised the no-op strategy contract only. No real "
                "strategy evaluation, signal generation, order simulation, broker "
                "routing, portfolio accounting, or P&L calculation was performed.",
            )
        ),
        "",
        "## Runner Summary",
        "",
        f"- Runner status: `{diagnostics.get('runner_status', 'unknown')}`",
        f"- Feed status: `{diagnostics.get('feed_status', 'unknown')}`",
        f"- Frame count: `{diagnostics.get('frame_count', 0)}`",
        f"- Contexts built: `{diagnostics.get('contexts_built', 0)}`",
        f"- Diagnostics emitted: `{diagnostics.get('diagnostics_emitted', 0)}`",
        f"- First timestamp: `{diagnostics.get('first_timestamp')}`",
        f"- Last timestamp: `{diagnostics.get('last_timestamp')}`",
        f"- Frames with missing symbols: `{diagnostics.get('missing_symbols_by_frame_count', 0)}`",
        "",
        "## Feed Summary",
        "",
        f"- Feed frames: `{feed_summary.get('frame_count', 0)}`",
        f"- Feed bars: `{feed_summary.get('total_bars', 0)}`",
        f"- Feed status: `{feed_summary.get('feed_status', 'unknown')}`",
        "",
        "## Missing Symbols",
        "",
    ]
    if diagnostics.get("symbols"):
        for symbol in diagnostics.get("symbols", []):
            lines.append(f"- `{symbol}` missing_frames=`{missing.get(symbol, 0)}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def signal_contract_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free disabled signal contract report."""

    request = payload.get("request", {})
    metadata = payload.get("metadata", {})
    result = payload.get("result", {})
    feed_summary = payload.get("feed_summary") or {}
    sample = payload.get("frame_context_sample") or {}
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])

    required_fields = [
        item.get("name", "")
        for item in metadata.get("required_fields", [])
        if isinstance(item, Mapping)
    ]
    lines = [
        f"# {payload.get('title', 'Broker-free Signal Contract')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'signal-contract')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Signal contract: `{metadata.get('signal_contract_name', 'unknown')}`",
        f"- Signal contract version: `{metadata.get('signal_contract_version', 'unknown')}`",
        f"- Contract enabled: `{metadata.get('enabled', True)}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Alignment mode: `{request.get('alignment_mode', 'union')}`",
        f"- Bar size filter: `{request.get('requested_bar_size')}`",
        f"- What-to-show filter: `{request.get('requested_what_to_show')}`",
        f"- Broker required: `{metadata.get('broker_required', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        f"- Signal contract validated: `{payload.get('signal_contract_validated', False)}`",
        f"- Signal evaluation enabled: `{payload.get('signal_evaluation_enabled', True)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Signal count: `{payload.get('signal_count', 0)}`",
        f"- Generated orders: `{payload.get('generated_orders', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- Fills simulated: `{payload.get('fills_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        f"- Portfolio accounting: `{payload.get('portfolio_accounting', True)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report reads local files only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "This command validates the signal contract only. Signal evaluation is "
                "disabled. No trading signals, order intents, order simulation, broker "
                "routing, fills, portfolio accounting, or P&L calculation were produced.",
            )
        ),
        "",
        "## Contract Summary",
        "",
        f"- Contexts observed: `{result.get('contexts_observed', 0)}`",
        f"- Diagnostics: `{len(payload.get('diagnostics', []))}`",
        f"- Required fields: `{', '.join(required_fields)}`",
        f"- Supported symbols: `{', '.join(metadata.get('supported_symbols', []))}`",
        f"- Supported bar sizes: `{', '.join(metadata.get('supported_bar_sizes', []))}`",
        "",
        "## Feed Summary",
        "",
        f"- Feed status: `{feed_summary.get('feed_status', 'unknown')}`",
        f"- Feed frames: `{feed_summary.get('frame_count', 0)}`",
        f"- Feed bars: `{feed_summary.get('total_bars', 0)}`",
        "",
        "## Frame Context Sample",
        "",
    ]
    if sample:
        lines.extend(
            [
                f"- Timestamp: `{sample.get('timestamp')}`",
                f"- Frame index: `{sample.get('frame_index')}`",
                f"- Available symbols: `{', '.join(sample.get('available_symbols', []))}`",
                f"- Missing symbols: `{', '.join(sample.get('missing_symbols', []))}`",
            ]
        )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def signal_runner_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free disabled signal runner report."""

    request = payload.get("request", {})
    metadata = payload.get("metadata", {})
    diagnostics = payload.get("diagnostics") or {}
    feed_summary = payload.get("feed_summary") or {}
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    missing = diagnostics.get("missing_symbols_by_symbol", {})

    lines = [
        f"# {payload.get('title', 'Broker-free Disabled Signal Runner')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'signal-runner')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Signal contract: `{metadata.get('signal_contract_name', 'unknown')}`",
        f"- Signal contract version: `{metadata.get('signal_contract_version', 'unknown')}`",
        f"- Contract enabled: `{metadata.get('enabled', True)}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Alignment mode: `{request.get('alignment_mode', 'union')}`",
        f"- Bar size filter: `{request.get('requested_bar_size')}`",
        f"- What-to-show filter: `{request.get('requested_what_to_show')}`",
        f"- Disabled signal runner: `{payload.get('disabled_signal_runner', False)}`",
        f"- Signal contract validated: `{payload.get('signal_contract_validated', False)}`",
        f"- Signal evaluation enabled: `{payload.get('signal_evaluation_enabled', True)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Signal count: `{payload.get('signal_count', 0)}`",
        f"- Generated orders: `{payload.get('generated_orders', True)}`",
        f"- Order intents generated: `{payload.get('order_intents_generated', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- Fills simulated: `{payload.get('fills_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        f"- Portfolio accounting: `{payload.get('portfolio_accounting', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report reads local files only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "This run exercised the disabled signal contract only. Signal "
                "evaluation is disabled. No trading signals, order intents, order "
                "simulation, broker routing, fills, portfolio accounting, or P&L "
                "calculation was performed.",
            )
        ),
        "",
        "## Runner Summary",
        "",
        f"- Runner status: `{diagnostics.get('runner_status', 'unknown')}`",
        f"- Feed status: `{diagnostics.get('feed_status', 'unknown')}`",
        f"- Frame count: `{diagnostics.get('frame_count', 0)}`",
        f"- Contexts built: `{diagnostics.get('contexts_built', 0)}`",
        f"- Diagnostics emitted: `{diagnostics.get('diagnostics_emitted', 0)}`",
        f"- First timestamp: `{diagnostics.get('first_timestamp')}`",
        f"- Last timestamp: `{diagnostics.get('last_timestamp')}`",
        f"- Frames with missing symbols: `{diagnostics.get('missing_symbols_by_frame_count', 0)}`",
        "",
        "## Feed Summary",
        "",
        f"- Feed frames: `{feed_summary.get('frame_count', 0)}`",
        f"- Feed bars: `{feed_summary.get('total_bars', 0)}`",
        f"- Feed status: `{feed_summary.get('feed_status', 'unknown')}`",
        "",
        "## Missing Symbols",
        "",
    ]
    if diagnostics.get("symbols"):
        for symbol in diagnostics.get("symbols", []):
            lines.append(f"- `{symbol}` missing_frames=`{missing.get(symbol, 0)}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def signal_evaluation_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free analytical signal evaluation report."""

    request = payload.get("request", {})
    metadata = payload.get("metadata", {})
    diagnostics = payload.get("diagnostics") or {}
    feed_summary = payload.get("feed_summary") or {}
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    state_counts = diagnostics.get("observations_by_state", {})

    lines = [
        f"# {payload.get('title', 'Broker-free Analytical Signal Evaluation')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'signal-evaluate')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Evaluator: `{metadata.get('name', 'unknown')}`",
        f"- Evaluator version: `{metadata.get('version', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Alignment mode: `{request.get('alignment_mode', 'union')}`",
        f"- Bar size filter: `{request.get('requested_bar_size')}`",
        f"- What-to-show filter: `{request.get('requested_what_to_show')}`",
        f"- Signal evaluation enabled: `{payload.get('signal_evaluation_enabled', False)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Signal count: `{payload.get('signal_count', 0)}`",
        f"- Order intents generated: `{payload.get('order_intents_generated', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- Fills simulated: `{payload.get('fills_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        f"- Portfolio accounting: `{payload.get('portfolio_accounting', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report reads local files only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "This run emitted non-actionable analytical observations only. No "
                "trading signals, order intents, order simulation, broker routing, "
                "portfolio accounting, or P&L calculation was performed.",
            )
        ),
        "",
        "## Evaluation Summary",
        "",
        f"- Evaluation status: `{diagnostics.get('evaluation_status', 'unknown')}`",
        f"- Feed status: `{diagnostics.get('feed_status', 'unknown')}`",
        f"- Frame count: `{diagnostics.get('frame_count', 0)}`",
        f"- Contexts built: `{diagnostics.get('contexts_built', 0)}`",
        f"- Observations: `{diagnostics.get('observations_count', 0)}`",
        f"- First timestamp: `{diagnostics.get('first_timestamp')}`",
        f"- Last timestamp: `{diagnostics.get('last_timestamp')}`",
        f"- Warmup observations: `{diagnostics.get('warmup_observations', 0)}`",
        f"- Invalid-data observations: `{diagnostics.get('invalid_data_observations', 0)}`",
        "",
        "## Feed Summary",
        "",
        f"- Feed frames: `{feed_summary.get('frame_count', 0)}`",
        f"- Feed bars: `{feed_summary.get('total_bars', 0)}`",
        f"- Feed status: `{feed_summary.get('feed_status', 'unknown')}`",
        "",
        "## Condition States",
        "",
    ]
    if state_counts:
        for state, count in sorted(state_counts.items()):
            lines.append(f"- `{state}` observations=`{count}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def evaluator_comparison_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free analytical evaluator comparison report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    results = payload.get("results", [])

    lines = [
        f"# {payload.get('title', 'Broker-free Analytical Evaluator Comparison')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'evaluator-compare')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Signal count: `{payload.get('signal_count', 0)}`",
        f"- Order intents generated: `{payload.get('order_intents_generated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This comparison is broker-free and diagnostic only.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "No trading signals or execution artifacts were produced.",
            )
        ),
        "",
        "## Candidates",
        "",
    ]
    if results:
        for result in results:
            candidate = result.get("candidate", {})
            train = result.get("train", {})
            test = result.get("test", {})
            lines.append(
                "- "
                f"`{candidate.get('short_window')}:{candidate.get('long_window')}` "
                f"status=`{result.get('final_status')}` "
                f"observations=`{result.get('total_observations')}` "
                f"train_met_rate=`{train.get('condition_met_rate')}` "
                f"test_met_rate=`{test.get('condition_met_rate')}` "
                f"delta=`{result.get('condition_met_rate_delta')}`"
            )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def commodity_universe_markdown(payload: Mapping[str, Any]) -> str:
    """Render a broker-free commodity research universe report."""

    instruments = payload.get("instruments", [])
    categories = payload.get("categories", {})
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])

    lines = [
        f"# {payload.get('title', 'Broker-free Commodity Research Universe')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'commodity-universe')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbols requested: `{', '.join(payload.get('symbols_requested', []))}`",
        f"- Commodity proxy universe: `{payload.get('commodity_proxy_universe', False)}`",
        f"- Futures contracts enabled: `{payload.get('futures_contracts_enabled', True)}`",
        f"- Direct futures data enabled: `{payload.get('direct_futures_data_enabled', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Signal evaluation enabled: `{payload.get('signal_evaluation_enabled', True)}`",
        f"- Generated signals: `{payload.get('generated_signals', True)}`",
        f"- Signal count: `{payload.get('signal_count', 0)}`",
        f"- Order intents generated: `{payload.get('order_intents_generated', True)}`",
        f"- Orders simulated: `{payload.get('orders_simulated', True)}`",
        f"- Fills simulated: `{payload.get('fills_simulated', True)}`",
        f"- P&L calculated: `{payload.get('pnl_calculated', True)}`",
        f"- Portfolio accounting: `{payload.get('portfolio_accounting', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This report is offline-only and does not contact a broker.",
            )
        ),
        "",
        str(
            payload.get(
                "no_execution_statement",
                "This command lists commodity-linked security proxies for research only.",
            )
        ),
        "",
        "## Instruments",
        "",
    ]
    if instruments:
        for instrument in instruments:
            lines.append(
                "- "
                f"`{instrument.get('symbol')}` category=`{instrument.get('category')}` "
                f"sec_type=`{instrument.get('ibkr_sec_type')}` "
                f"exposure=`{instrument.get('underlying_exposure')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Categories", ""])
    if categories:
        for category, symbols in sorted(categories.items()):
            lines.append(f"- `{category}`: `{', '.join(symbols)}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def paper_readiness_run_markdown(payload: Mapping[str, Any]) -> str:
    """Render the read-only paper readiness orchestration report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    stages = payload.get("stages", [])
    report_paths = payload.get("report_paths", {})
    account_ids = payload.get("account_ids_masked", [])
    partial_symbols = payload.get("partial_symbols", [])
    request = payload.get("request", {})
    broker_stage_pause = (
        request.get("broker_stage_pause_seconds", "unknown")
        if isinstance(request, Mapping)
        else "unknown"
    )

    lines = [
        f"# {payload.get('title', 'Read-only IBKR Paper Readiness Run')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'paper-readiness-run')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Selected universe: `{', '.join(payload.get('selected_universe', []))}`",
        f"- Commodity symbols: `{', '.join(payload.get('commodity_symbols', []))}`",
        f"- Broker stage pause seconds: `{broker_stage_pause}`",
        f"- Broker connected: `{payload.get('broker_connected', False)}`",
        f"- Account summary verified: `{payload.get('account_summary_verified', False)}`",
        f"- History snapshot written: `{payload.get('history_snapshot_written', False)}`",
        f"- History load completed: `{payload.get('history_load_completed', False)}`",
        f"- Commodity universe verified: `{payload.get('commodity_universe_verified', False)}`",
        f"- Signal evaluation completed: `{payload.get('signal_evaluation_completed', False)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', True)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', True)}`",
        f"- Configured allow paper orders: `{payload.get('configured_allow_paper_orders', True)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Broker contact read-only: `{payload.get('broker_contact_read_only', False)}`",
        f"- Futures contracts enabled: `{payload.get('futures_contracts_enabled', True)}`",
        f"- Direct futures data enabled: `{payload.get('direct_futures_data_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This readiness run is read-only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "futures_scope_statement",
                "Direct futures contracts remain out of scope.",
            )
        ),
        "",
        "## Stages",
        "",
    ]
    if stages:
        for stage in stages:
            lines.append(
                "- "
                f"`{stage.get('name', 'unknown')}` "
                f"status=`{stage.get('final_status', 'unknown')}` "
                f"ok=`{stage.get('ok', False)}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Masked Accounts", ""])
    if account_ids:
        lines.extend(f"- `{account_id}`" for account_id in account_ids)
    else:
        lines.append("- None")

    lines.extend(["", "## Partial Symbols", ""])
    if partial_symbols:
        lines.extend(f"- `{symbol}`" for symbol in partial_symbols)
    else:
        lines.append("- None")

    lines.extend(["", "## Report Paths", ""])
    if report_paths:
        for label, path in sorted(report_paths.items()):
            lines.append(f"- `{label}`: `{path}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def alpha_shadow_run_markdown(payload: Mapping[str, Any]) -> str:
    """Render the read-only alpha shadow orchestration report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    stages = payload.get("stages", [])
    report_paths = payload.get("report_paths", {})
    account_ids = payload.get("account_ids_masked", [])
    data_quality = payload.get("data_quality_status_by_symbol", {})
    source_bars = payload.get("source_bar_timestamp_by_symbol", {})
    request = payload.get("request", {})
    broker_stage_pause = (
        request.get("broker_stage_pause_seconds", "unknown")
        if isinstance(request, Mapping)
        else "unknown"
    )

    lines = [
        f"# {payload.get('title', 'Read-only IBKR Alpha Shadow Run')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'alpha-shadow-run')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Selected universe: `{', '.join(payload.get('selected_universe', []))}`",
        f"- Broker stage pause seconds: `{broker_stage_pause}`",
        f"- Broker connected: `{payload.get('broker_connected', False)}`",
        f"- Account summary verified: `{payload.get('account_summary_verified', False)}`",
        f"- History snapshot written: `{payload.get('history_snapshot_written', False)}`",
        f"- History load completed: `{payload.get('history_load_completed', False)}`",
        f"- Data quality completed: `{payload.get('data_quality_completed', False)}`",
        f"- Signal evaluation completed: `{payload.get('signal_evaluation_completed', False)}`",
        f"- Shadow risk mode: `{payload.get('shadow_risk_mode', 'unknown')}`",
        f"- Shadow signals: `{payload.get('shadow_signal_count', 0)}`",
        f"- Trade plans: `{payload.get('trade_plan_count', 0)}`",
        f"- Risk decisions: `{payload.get('risk_decision_count', 0)}`",
        f"- Risk approved: `{payload.get('risk_approved_count', 0)}`",
        f"- Simulation results: `{payload.get('simulation_result_count', 0)}`",
        f"- Simulated fills: `{payload.get('simulated_fill_count', 0)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', True)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', True)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Broker contact read-only: `{payload.get('broker_contact_read_only', False)}`",
        f"- Paper execution enabled: `{payload.get('paper_execution_enabled', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Scope",
        "",
        str(
            payload.get(
                "no_order_guarantee_statement",
                "This alpha shadow run is read-only and no orders were routed.",
            )
        ),
        "",
        str(
            payload.get(
                "no_paper_execution_statement",
                "No paper orders are submitted by this command.",
            )
        ),
        "",
        "## Stages",
        "",
    ]
    if stages:
        for stage in stages:
            lines.append(
                "- "
                f"`{stage.get('name', 'unknown')}` "
                f"status=`{stage.get('final_status', 'unknown')}` "
                f"ok=`{stage.get('ok', False)}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Data Quality", ""])
    if isinstance(data_quality, Mapping) and data_quality:
        for symbol, status in sorted(data_quality.items()):
            lines.append(f"- `{symbol}`: `{status}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Shadow Quote Source Bars", ""])
    if isinstance(source_bars, Mapping) and source_bars:
        for symbol, timestamp in sorted(source_bars.items()):
            lines.append(f"- `{symbol}`: `{timestamp}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Masked Accounts", ""])
    if account_ids:
        lines.extend(f"- `{account_id}`" for account_id in account_ids)
    else:
        lines.append("- None")

    lines.extend(["", "## Report Paths", ""])
    if report_paths:
        for label, path in sorted(report_paths.items()):
            lines.append(f"- `{label}`: `{path}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def paper_order_smoke_markdown(payload: Mapping[str, Any]) -> str:
    """Render the gated paper-order smoke report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    request = payload.get("request", {})
    quote = payload.get("quote", {})
    callback_timeline = payload.get("callback_timeline", [])
    account_ids = payload.get("account_ids_masked", [])
    request_symbol = request.get("symbol", "unknown") if isinstance(request, Mapping) else "unknown"
    request_quantity = (
        request.get("quantity", "unknown") if isinstance(request, Mapping) else "unknown"
    )
    request_order_type = (
        request.get("order_type", "unknown") if isinstance(request, Mapping) else "unknown"
    )
    request_tif = (
        request.get("time_in_force", "unknown")
        if isinstance(request, Mapping)
        else "unknown"
    )

    lines = [
        f"# {payload.get('title', 'IBKR Paper Order Smoke Run')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'paper-order-smoke')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- Symbol: `{request_symbol}`",
        f"- Quantity: `{request_quantity}`",
        f"- Order type: `{request_order_type}`",
        f"- Time in force: `{request_tif}`",
        f"- Transmit: `{payload.get('transmitted', False)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', False)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', False)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', True)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', True)}`",
        f"- Live route possible: `{payload.get('live_route_possible', True)}`",
        f"- Broker connected: `{payload.get('broker_connected', False)}`",
        f"- Account summary verified: `{payload.get('account_summary_verified', False)}`",
        f"- Existing open orders: `{payload.get('existing_open_order_count', 0)}`",
        f"- Duplicate open order detected: `{payload.get('duplicate_open_order_detected', False)}`",
        f"- Limit price: `{payload.get('limit_price', 'n/a')}`",
        f"- Notional: `{payload.get('notional', 'n/a')}`",
        f"- Order ID: `{payload.get('order_id', 'n/a')}`",
        f"- Perm ID: `{payload.get('perm_id', 'n/a')}`",
        f"- Order status: `{payload.get('order_status', 'n/a')}`",
        f"- Fill quantity: `{payload.get('fill_quantity', '0')}`",
        f"- Cancel requested: `{payload.get('cancel_requested', False)}`",
        f"- Canceled: `{payload.get('canceled', False)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Paper-order smoke safety scope unavailable.")),
        "",
        "## Masked Accounts",
        "",
    ]
    if account_ids:
        lines.extend(f"- `{account_id}`" for account_id in account_ids)
    else:
        lines.append("- None")

    lines.extend(["", "## Quote", ""])
    if isinstance(quote, Mapping) and quote:
        lines.extend(
            [
                f"- Bid: `{quote.get('bid', 'n/a')}`",
                f"- Ask: `{quote.get('ask', 'n/a')}`",
                f"- Last: `{quote.get('last', 'n/a')}`",
                f"- Close: `{quote.get('close', 'n/a')}`",
                f"- Timestamp: `{quote.get('quote_timestamp', 'n/a')}`",
                f"- Stale: `{quote.get('stale', True)}`",
            ]
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Callback Timeline", ""])
    if isinstance(callback_timeline, list) and callback_timeline:
        for event in callback_timeline:
            if not isinstance(event, Mapping):
                continue
            lines.append(
                "- "
                f"`{event.get('event_type', 'unknown')}` "
                f"order_id=`{event.get('order_id', 'n/a')}` "
                f"perm_id=`{event.get('perm_id', 'n/a')}` "
                f"status=`{event.get('status', 'n/a')}` "
                f"message=`{event.get('message', '')}`"
            )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def alpha_paper_run_markdown(payload: Mapping[str, Any]) -> str:
    """Render the strategy-gated alpha paper run report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    request = payload.get("request", {})
    paper_order = payload.get("paper_order_report", {})
    source_paths = payload.get("source_report_paths", {})
    account_ids = payload.get("account_ids_masked", [])
    request_symbol = request.get("symbol", "unknown") if isinstance(request, Mapping) else "unknown"

    lines = [
        f"# {payload.get('title', 'IBKR Alpha Paper Run')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'alpha-paper-run')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- Symbol: `{request_symbol}`",
        f"- Shadow report verified: `{payload.get('alpha_shadow_report_verified', False)}`",
        f"- Paper smoke report verified: `{payload.get('paper_smoke_report_verified', False)}`",
        f"- Shadow signal: `{payload.get('shadow_signal', 'n/a')}`",
        f"- Risk approved: `{payload.get('risk_approved', False)}`",
        f"- No-trade reason: `{payload.get('no_trade_reason', 'n/a')}`",
        f"- Submitted orders: `{payload.get('submitted_orders', False)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', False)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', True)}`",
        f"- Live route possible: `{payload.get('live_route_possible', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', False)}`",
        f"- Order ID: `{payload.get('order_id', 'n/a')}`",
        f"- Perm ID: `{payload.get('perm_id', 'n/a')}`",
        f"- Order status: `{payload.get('order_status', 'n/a')}`",
        f"- Fill quantity: `{payload.get('fill_quantity', '0')}`",
        f"- Cancel requested: `{payload.get('cancel_requested', False)}`",
        f"- Canceled: `{payload.get('canceled', False)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Alpha paper run safety scope unavailable.")),
        "",
        "## Source Reports",
        "",
    ]
    if isinstance(source_paths, Mapping) and source_paths:
        for label, path in sorted(source_paths.items()):
            lines.append(f"- `{label}`: `{path}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Masked Accounts", ""])
    if account_ids:
        lines.extend(f"- `{account_id}`" for account_id in account_ids)
    else:
        lines.append("- None")

    lines.extend(["", "## Paper Order Evidence", ""])
    if isinstance(paper_order, Mapping) and paper_order:
        lines.extend(
            [
                f"- Final status: `{paper_order.get('final_status', 'unknown')}`",
                f"- Submitted orders: `{paper_order.get('submitted_orders', False)}`",
                f"- Transmitted: `{paper_order.get('transmitted', False)}`",
                f"- Order ID: `{paper_order.get('order_id', 'n/a')}`",
                f"- Perm ID: `{paper_order.get('perm_id', 'n/a')}`",
                f"- Order status: `{paper_order.get('order_status', 'n/a')}`",
                f"- Fill quantity: `{paper_order.get('fill_quantity', '0')}`",
                f"- Canceled: `{paper_order.get('canceled', False)}`",
            ]
        )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def _warnings_and_errors(warnings: list[Any], errors: list[Any]) -> list[str]:
    lines = ["", "## Warnings", ""]
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")
    lines.extend(["", "## Errors", ""])
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- None")
    return lines


def _sample_values(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return "none"
    return ", ".join(str(value) for value in values)
