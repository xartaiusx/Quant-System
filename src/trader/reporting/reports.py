"""Markdown report formatting."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def markdown_summary(payload: Mapping[str, Any]) -> str:
    """Render a compact Markdown summary for a cycle payload."""

    if payload.get("report_type") == "broker_probe":
        return broker_probe_markdown(payload)
    if payload.get("report_type") == "market_probe":
        return market_probe_markdown(payload)
    if payload.get("report_type") == "history_snapshot":
        return history_snapshot_markdown(payload)
    if payload.get("report_type") == "history_readiness":
        return history_readiness_markdown(payload)

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
