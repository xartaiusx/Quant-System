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
    if payload.get("report_type") == "ibkr_session_compare":
        return ibkr_session_compare_markdown(payload)
    if payload.get("report_type") == "history_readiness":
        return history_readiness_markdown(payload)
    if payload.get("report_type") == "ibkr_data_diagnostics":
        return ibkr_data_diagnostics_markdown(payload)
    if payload.get("report_type") == "history_index":
        return history_index_markdown(payload)
    if payload.get("report_type") == "history_load":
        return history_load_markdown(payload)
    if payload.get("report_type") == "shadow_warmup_assembly":
        return shadow_warmup_assembly_markdown(payload)
    if payload.get("report_type") == "data_quality_gate":
        return data_quality_gate_markdown(payload)
    if payload.get("report_type") == "backtest_feed":
        return backtest_feed_markdown(payload)
    if payload.get("report_type") == "backtest_run":
        return backtest_run_markdown(payload)
    if payload.get("report_type") == "research_data_ingest":
        return research_data_ingest_markdown(payload)
    if payload.get("report_type") == "research_data_audit":
        return research_data_audit_markdown(payload)
    if payload.get("report_type") == "research_data_bakeoff":
        return research_data_bakeoff_markdown(payload)
    if payload.get("report_type") == "research_vendor_decision":
        return research_vendor_decision_markdown(payload)
    if payload.get("report_type") == "research_instrument_master":
        return research_instrument_master_markdown(payload)
    if payload.get("report_type") == "research_data_batch_import":
        return research_data_batch_import_markdown(payload)
    if payload.get("report_type") == "research_derived_views":
        return research_derived_views_markdown(payload)
    if payload.get("report_type") == "research_catalog_load":
        return research_catalog_load_markdown(payload)
    if payload.get("report_type") == "research_backtest":
        return research_backtest_markdown(payload)
    if payload.get("report_type") == "research_walk_forward":
        return research_walk_forward_markdown(payload)
    if payload.get("report_type") == "research_experiment":
        return research_experiment_markdown(payload)
    if payload.get("report_type") == "research_experiment_registration":
        return research_experiment_registration_markdown(payload)
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
    if payload.get("report_type") in {"alpha_shadow_daemon", "alpha_shadow_daemon_delayed"}:
        return alpha_shadow_daemon_markdown(payload)
    if payload.get("report_type") == "alpha_shadow_daemon_summary":
        return alpha_shadow_daemon_summary_markdown(payload)
    if payload.get("report_type") == "paper_order_smoke":
        return paper_order_smoke_markdown(payload)
    if payload.get("report_type") == "alpha_paper_run":
        return alpha_paper_run_markdown(payload)
    if payload.get("report_type") == "paper_reconcile":
        return paper_reconcile_markdown(payload)
    if payload.get("report_type") == "alpha_test_summary":
        return alpha_test_summary_markdown(payload)
    if payload.get("report_type") == "alpha_campaign_run":
        return alpha_campaign_run_markdown(payload)
    if payload.get("report_type") == "paper_ledger_update":
        return paper_ledger_update_markdown(payload)

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
                f"midpoint=`{spread.get('midpoint')}` spread=`{spread.get('spread')}` "
                f"spread_bps=`{spread.get('spread_bps')}` "
                f"received_at=`{quote.get('received_at')}` "
                f"transport_age_seconds=`{quote.get('transport_age_seconds')}` "
                f"transport_stale=`{quote.get('transport_stale')}` "
                f"market_event_time=`{quote.get('market_event_time')}` "
                f"market_event_age_seconds=`{quote.get('market_event_age_seconds')}` "
                f"market_freshness_known=`{quote.get('market_freshness_known')}`"
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
        f"- End datetime: `{request.get('end_datetime') or 'now'}`",
        f"- Volume unit: `{request.get('volume_unit', 'unknown')}`",
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


def ibkr_session_compare_markdown(payload: Mapping[str, Any]) -> str:
    """Render an offline IBKR snapshot revision comparison."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    revisions = payload.get("revisions", [])
    lines = [
        f"# {payload.get('title', 'IBKR Session Comparison')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbol: `{payload.get('symbol') or 'n/a'}`",
        f"- Parameters compatible: `{payload.get('parameters_compatible', False)}`",
        f"- Baseline bars: `{payload.get('baseline_bar_count', 0)}`",
        f"- Candidate bars: `{payload.get('candidate_bar_count', 0)}`",
        f"- Matching bars: `{payload.get('matching_bar_count', 0)}`",
        f"- Revised bars: `{payload.get('revised_bar_count', 0)}`",
        f"- Baseline-only bars: `{payload.get('baseline_only_count', 0)}`",
        f"- Candidate-only bars: `{payload.get('candidate_only_count', 0)}`",
        "- Volume comparison authoritative: "
        f"`{payload.get('volume_comparison_authoritative', False)}`",
        f"- Baseline volume unit: `{payload.get('baseline_volume_unit', 'unknown')}`",
        f"- Candidate volume unit: `{payload.get('candidate_volume_unit', 'unknown')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', False)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', False)}`",
        "",
        "## Revisions",
        "",
    ]
    if revisions:
        for revision in revisions:
            lines.append(
                f"- `{revision.get('timestamp', 'unknown')}` "
                f"fields=`{', '.join(revision.get('changed_fields', []))}`"
            )
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(warnings, errors))
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


def ibkr_data_diagnostics_markdown(payload: Mapping[str, Any]) -> str:
    """Render an offline strict SPY IBKR data-diagnostics report."""

    request = payload.get("request", {})
    source_paths = payload.get("source_report_paths", {})
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    operator_hints = payload.get("operator_hints", [])
    market_probe_warnings = payload.get("market_probe_warnings", [])
    market_probe_errors = payload.get("market_probe_errors", [])

    lines = [
        f"# {payload.get('title', 'IBKR Data Freshness Diagnostics')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'ibkr-data-diagnostics')}`",
        f"- Commit SHA: `{payload.get('commit_sha') or 'unknown'}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbol: `{payload.get('symbol', 'SPY')}`",
        f"- Data policy: `{payload.get('data_policy', 'strict_live')}`",
        f"- Delayed data mode: `{payload.get('delayed_data_mode', False)}`",
        f"- Graduation eligible: `{payload.get('graduation_eligible', True)}`",
        "- Non-graduating reason: "
        f"`{payload.get('non_graduating_reason') or 'n/a'}`",
        f"- Strict precheck passed: `{payload.get('strict_shadow_precheck_passed', False)}`",
        "- Delayed precheck passed: "
        f"`{payload.get('delayed_shadow_precheck_passed', False)}`",
        f"- Next action: `{payload.get('next_recommended_action', 'unknown')}`",
        "",
        "## Strict Inputs",
        "",
        f"- Minimum bars: `{payload.get('min_bars', request.get('min_bars', 'unknown'))}`",
        "- Stale after minutes: "
        f"`{payload.get('stale_after_minutes', request.get('stale_after_minutes', 'unknown'))}`",
        f"- Expected duration: `{request.get('expected_duration', 'unknown')}`",
        f"- Expected bar size: `{request.get('expected_bar_size', 'unknown')}`",
        f"- Expected what-to-show: `{request.get('expected_what_to_show', 'unknown')}`",
        f"- Expected use RTH: `{request.get('expected_use_rth', 'unknown')}`",
        "",
        "## Broker Evidence",
        "",
        f"- Broker probe OK: `{payload.get('broker_probe_ok', False)}`",
        f"- Broker connected: `{payload.get('broker_connected', False)}`",
        f"- Account verified: `{payload.get('broker_account_verified', False)}`",
        f"- Broker failure stage: `{payload.get('broker_failure_stage') or 'none'}`",
        "",
        "## SPY Data Evidence",
        "",
        f"- History snapshot OK: `{payload.get('history_snapshot_ok', False)}`",
        f"- History readiness OK: `{payload.get('history_readiness_ok', False)}`",
        f"- Bar count: `{payload.get('bar_count', 0)}`",
        f"- Bar count passed: `{payload.get('bar_count_passed', False)}`",
        f"- First bar: `{payload.get('first_bar_timestamp') or 'n/a'}`",
        f"- Latest raw bar: `{payload.get('latest_bar_timestamp') or 'n/a'}`",
        f"- Latest parse status: `{payload.get('latest_bar_parse_status', 'unknown')}`",
        f"- Latest start UTC: `{payload.get('latest_bar_start_utc') or 'n/a'}`",
        f"- Latest end UTC: `{payload.get('latest_bar_end_utc') or 'n/a'}`",
        "- Latest bar-start age minutes: "
        f"`{payload.get('latest_bar_start_age_minutes')}`",
        "- Latest completed interval-end age minutes: "
        f"`{payload.get('latest_bar_interval_end_age_minutes')}`",
        f"- Freshness passed: `{payload.get('freshness_passed', False)}`",
        f"- Market-data type requested: `{payload.get('market_data_type_requested') or 'n/a'}`",
        f"- Market-data type received: `{payload.get('market_data_type_received') or 'n/a'}`",
        f"- Market-data hint: `{payload.get('market_data_type_hint', 'unknown')}`",
        f"- Market probe OK: `{payload.get('market_probe_ok')}`",
        f"- Market probe final status: `{payload.get('market_probe_final_status') or 'n/a'}`",
        "- Market-data permission blocker: "
        f"`{payload.get('market_data_permission_blocker', False)}`",
        f"- Market-data permission hint: `{payload.get('market_data_permission_hint') or 'n/a'}`",
        "",
        "## Safety",
        "",
        f"- Submitted orders: `{payload.get('submitted_orders', False)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', False)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', False)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', False)}`",
        f"- Broker contacted by diagnostics: `{payload.get('broker_contacted', False)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', True)}`",
        "",
        str(
            payload.get(
                "safety_statement",
                "This diagnostics report is offline-only and no orders were routed.",
            )
        ),
        "",
        "## Source Reports",
        "",
    ]
    if isinstance(source_paths, Mapping) and source_paths:
        lines.extend(f"- {name}: `{path}`" for name, path in source_paths.items())
    else:
        lines.append("- None")

    lines.extend(["", "## Operator Hints", ""])
    if operator_hints:
        lines.extend(f"- {hint}" for hint in operator_hints)
    else:
        lines.append("- None")

    lines.extend(["", "## Market-Probe Warnings", ""])
    if market_probe_warnings:
        lines.extend(f"- {warning}" for warning in market_probe_warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Market-Probe Errors", ""])
    if market_probe_errors:
        lines.extend(f"- {error}" for error in market_probe_errors)
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
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


def shadow_warmup_assembly_markdown(payload: Mapping[str, Any]) -> str:
    """Render strict-live prior-session/current-live warmup evidence."""

    lines = [
        f"# {payload.get('title', 'SPY Strict-live Warmup Assembly')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Source snapshots: `{payload.get('source_snapshot_count', 0)}`",
        f"- Prior complete sessions: "
        f"`{_join_or_none(payload.get('prior_complete_session_dates', []))}`",
        f"- Current session: `{payload.get('current_session_date')}`",
        f"- Current live bars: `{payload.get('current_live_bar_count', 0)}`",
        f"- Assembled bars: `{payload.get('assembled_bar_count', 0)}`",
        f"- Minimum bars: `{payload.get('minimum_bar_count', 0)}`",
        f"- Newest live bar: `{payload.get('newest_live_bar_timestamp')}`",
        f"- Newest live bar age: "
        f"`{payload.get('newest_live_bar_age_minutes')} minutes`",
        f"- Freshness threshold: "
        f"`{payload.get('freshness_threshold_minutes')} minutes`",
        f"- Current session starts at open: "
        f"`{payload.get('current_session_starts_at_open', False)}`",
        f"- Current session contiguous: "
        f"`{payload.get('current_session_contiguous', False)}`",
        f"- Completed bars only: `{payload.get('completed_bars_only', False)}`",
        f"- Overlap bars: `{payload.get('overlap_bar_count', 0)}`",
        f"- Overlap values agree: `{payload.get('overlap_values_agree', False)}`",
        f"- Structural boundary agrees: "
        f"`{payload.get('structural_boundary_agrees', False)}`",
        f"- Boundary agreement passed: "
        f"`{payload.get('boundary_agreement_passed', False)}`",
        f"- Data fingerprint: `{payload.get('data_fingerprint')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
    ]
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
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


def research_data_ingest_markdown(payload: Mapping[str, Any]) -> str:
    """Render an offline immutable SPY research-data ingestion report."""

    request = payload.get("request", {})
    artifact = payload.get("artifact") or {}
    partitions = payload.get("partitions", [])
    findings = payload.get("findings", [])
    lines = [
        f"# {payload.get('title', 'SPY Research Data Ingestion')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbol: `{request.get('symbol', 'SPY')}`",
        f"- Dataset: `{request.get('dataset', 'minute_aggs_v1')}`",
        f"- Price view: `{request.get('price_view', 'raw')}`",
        f"- Catalog: `{payload.get('catalog_path')}`",
        f"- Source SHA-256: `{artifact.get('sha256', 'unavailable')}`",
        f"- Immutable raw preserved: `{payload.get('immutable_raw_preserved', False)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        f"- Promotion eligible: `{payload.get('promotion_eligible', True)}`",
        "",
        "## Counts",
        "",
        f"- Rows scanned: `{payload.get('rows_scanned', 0)}`",
        f"- SPY rows seen: `{payload.get('symbol_rows_seen', 0)}`",
        f"- RTH rows selected: `{payload.get('rth_rows_selected', 0)}`",
        f"- Outside-RTH rows excluded: `{payload.get('outside_rth_rows_excluded', 0)}`",
        f"- Partitions: `{len(partitions)}`",
        f"- Findings: `{len(findings)}`",
        f"- Idempotent replay: `{payload.get('idempotent_replay', False)}`",
    ]
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_data_audit_markdown(payload: Mapping[str, Any]) -> str:
    """Render an offline active research-partition audit report."""

    request = payload.get("request", {})
    lines = [
        f"# {payload.get('title', 'SPY Research Data Store Audit')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbol: `{request.get('symbol', 'SPY')}`",
        f"- Catalog: `{payload.get('catalog_path')}`",
        f"- Active sessions: `{payload.get('active_session_count', 0)}`",
        f"- Active rows: `{payload.get('total_row_count', 0)}`",
        f"- First session: `{payload.get('first_session_date')}`",
        f"- Last session: `{payload.get('last_session_date')}`",
        f"- Missing sessions: `{len(payload.get('missing_session_dates', []))}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        f"- Promotion eligible: `{payload.get('promotion_eligible', True)}`",
    ]
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_data_bakeoff_markdown(payload: Mapping[str, Any]) -> str:
    """Render the offline vendor due-diligence bake-off report."""

    samples = payload.get("sample_results", [])
    comparisons = payload.get("comparisons", [])
    lines = [
        f"# {payload.get('title', 'SPY Research Data Vendor Bake-off')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Manifest: `{payload.get('manifest_path')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Credentials read: `{payload.get('credentials_read', True)}`",
        f"- Network accessed: `{payload.get('network_accessed', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        f"- Procurement-ready vendors: "
        f"`{', '.join(payload.get('procurement_ready_vendors', [])) or 'none'}`",
        f"- Missing case tags: `{', '.join(payload.get('missing_case_tags', [])) or 'none'}`",
        "",
        "## Samples",
        "",
    ]
    if samples:
        for sample in samples:
            lines.append(
                f"- `{sample.get('sample_id')}` vendor=`{sample.get('vendor')}` "
                f"rows=`{sample.get('row_count', 0)}` ok=`{sample.get('ok', False)}`"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Comparisons", ""])
    if comparisons:
        for comparison in comparisons:
            lines.append(
                f"- `{comparison.get('comparison_type')}` "
                f"left=`{comparison.get('left_sample_id')}` "
                f"right=`{comparison.get('right_sample_id')}` "
                f"overlap=`{comparison.get('overlap_count', 0)}` "
                f"ok=`{comparison.get('ok', False)}`"
            )
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_data_batch_import_markdown(payload: Mapping[str, Any]) -> str:
    """Render deterministic local batch-import evidence."""

    request = payload.get("request", {})
    items = payload.get("items", [])
    lines = [
        f"# {payload.get('title', 'SPY Research Data Batch Import')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Vendor: `{request.get('vendor')}`",
        f"- Kind: `{request.get('kind')}`",
        f"- Source directory: `{request.get('source_dir')}`",
        f"- Files passed: `{payload.get('succeeded_count', 0)}`",
        f"- Files failed: `{payload.get('failed_count', 0)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Credentials read: `{payload.get('credentials_read', True)}`",
        f"- Network accessed: `{payload.get('network_accessed', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        "",
        "## Files",
        "",
    ]
    if items:
        for item in items:
            lines.append(
                f"- `{item.get('source_path')}` type=`{item.get('report_type')}` "
                f"partitions=`{item.get('partition_count', 0)}` "
                f"actions=`{item.get('action_count', 0)}` ok=`{item.get('ok', False)}`"
            )
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_derived_views_markdown(payload: Mapping[str, Any]) -> str:
    """Render source-hashed derived-view lineage evidence."""

    request = payload.get("request", {})
    partitions = payload.get("partitions", [])
    lines = [
        f"# {payload.get('title', 'SPY Derived Research Views')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Algorithm version: `{request.get('algorithm_version')}`",
        f"- Action fingerprint: `{payload.get('action_fingerprint')}`",
        f"- Partitions: `{len(partitions)}`",
        f"- Stale partitions superseded: "
        f"`{payload.get('stale_partitions_superseded', 0)}`",
        f"- Idempotent partitions: `{payload.get('idempotent_partition_count', 0)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        "",
        "## Active Evidence",
        "",
    ]
    if partitions:
        for partition in partitions:
            lines.append(
                f"- `{partition.get('session_date')}` "
                f"view=`{partition.get('price_view')}` "
                f"revision=`{partition.get('revision')}` "
                f"rows=`{partition.get('row_count')}`"
            )
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_catalog_load_markdown(payload: Mapping[str, Any]) -> str:
    """Render active catalog loader and fingerprint evidence."""

    request = payload.get("request", {})
    feed = payload.get("feed") or {}
    lines = [
        f"# {payload.get('title', 'SPY Research Catalog Load')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Price view: `{request.get('price_view')}`",
        f"- Bar size: `{request.get('bar_size')}`",
        f"- Start date: `{request.get('start_date')}`",
        f"- End date: `{request.get('end_date')}`",
        f"- Partitions loaded: `{len(payload.get('partitions', []))}`",
        f"- Bars loaded: `{feed.get('total_bars', 0)}`",
        f"- Dataset fingerprint: `{payload.get('dataset_fingerprint')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
    ]
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_backtest_markdown(payload: Mapping[str, Any]) -> str:
    """Render a cost-aware broker-free research backtest report."""

    request = payload.get("request", {})
    metrics = payload.get("metrics") or {}
    fills = payload.get("fills", [])
    orders = payload.get("orders", [])
    trades = payload.get("trades", [])
    capital_events = payload.get("capital_events", [])
    cost_scenarios = payload.get("cost_scenarios", [])
    lines = [
        f"# {payload.get('title', 'SPY Broker-free Research Backtest')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Symbol: `{request.get('symbol', 'SPY')}`",
        f"- Windows: `{request.get('short_window')}/{request.get('long_window')}`",
        f"- Sizing mode: `{request.get('sizing_mode')}`",
        f"- Quantity: `{request.get('quantity')}`",
        f"- Target allocation: `{request.get('target_allocation_pct')}%`",
        f"- Execution model: `{request.get('execution_model')}`",
        f"- Signal/execution timestamps aligned: "
        f"`{payload.get('signal_execution_timestamps_aligned', False)}`",
        f"- Signal dataset fingerprint: "
        f"`{payload.get('catalog_dataset_fingerprint')}`",
        f"- Execution dataset fingerprint: "
        f"`{payload.get('execution_dataset_fingerprint')}`",
        f"- Benchmark dataset fingerprint: "
        f"`{payload.get('benchmark_dataset_fingerprint')}`",
        f"- Corporate-action fingerprint: `{payload.get('action_fingerprint')}`",
        f"- Promotion eligible: `{payload.get('promotion_eligible', False)}`",
        f"- Non-promotion reason: `{payload.get('non_promotion_reason')}`",
        f"- Lookahead prevention: `{payload.get('lookahead_prevention')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        "",
        "## Cost Model",
        "",
        f"- Full spread: `{request.get('spread_bps')} bps`",
        f"- Slippage per side: `{request.get('slippage_bps')} bps`",
        f"- Commission per share: `{request.get('commission_per_share')}`",
        f"- Minimum commission: `{request.get('minimum_commission')}`",
        f"- Tick size: `{request.get('tick_size')}`",
        f"- Limit buffer: `{request.get('limit_buffer_bps')} bps`",
        f"- Maximum volume participation: "
        f"`{request.get('max_volume_participation')}`",
        "",
        "## Metrics",
        "",
        f"- Starting cash: `{metrics.get('starting_cash')}`",
        f"- Ending equity: `{metrics.get('ending_equity')}`",
        f"- Net P&L: `{metrics.get('net_pnl')}`",
        f"- Total return: `{metrics.get('total_return_pct')}%`",
        f"- SPY benchmark return: `{metrics.get('benchmark_return_pct')}%`",
        f"- Maximum drawdown: `{metrics.get('max_drawdown_pct')}%`",
        f"- Turnover ratio: `{metrics.get('turnover_ratio')}`",
        f"- Commissions: `{metrics.get('total_commissions')}`",
        f"- Spread cost: `{metrics.get('total_spread_cost')}`",
        f"- Slippage cost: `{metrics.get('total_slippage_cost')}`",
        f"- Tick-rounding cost: `{metrics.get('total_tick_rounding_cost')}`",
        f"- CAGR: `{metrics.get('cagr_pct')}%`",
        f"- Annualized volatility: `{metrics.get('annualized_volatility_pct')}%`",
        f"- Sharpe / Sortino / Calmar: "
        f"`{metrics.get('sharpe_ratio')} / {metrics.get('sortino_ratio')} / "
        f"{metrics.get('calmar_ratio')}`",
        f"- Drawdown duration bars / days: "
        f"`{metrics.get('max_drawdown_duration_bars', 0)} / "
        f"{metrics.get('max_drawdown_duration_days', 0)}`",
        f"- Benchmark-relative return: "
        f"`{metrics.get('benchmark_relative_return_pct')}%`",
        f"- Signals / fills / closed trades: "
        f"`{metrics.get('signal_count', 0)} / {metrics.get('fill_count', 0)} / "
        f"{metrics.get('closed_trade_count', 0)}`",
        f"- Win rate: `{metrics.get('win_rate_pct')}%`",
        f"- Exposure: `{metrics.get('exposure_pct')}%`",
        "",
        "## Simulated Fills",
        "",
    ]
    if fills:
        for fill in fills:
            lines.append(
                "- "
                f"`{fill.get('fill_timestamp')}` {fill.get('action')} "
                f"{fill.get('quantity')} @ `{fill.get('fill_price')}` "
                f"commission=`{fill.get('commission')}` reason=`{fill.get('reason')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Simulated LMT DAY Orders", ""])
    if orders:
        for order in orders:
            lines.append(
                f"- `{order.get('order_id')}` {order.get('action')} "
                f"requested=`{order.get('requested_quantity')}` "
                f"filled=`{order.get('filled_quantity')}` "
                f"limit=`{order.get('limit_price')}` status=`{order.get('status')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Closed Trades", ""])
    if trades:
        for trade in trades:
            lines.append(
                "- "
                f"entry=`{trade.get('entry_timestamp')}` exit=`{trade.get('exit_timestamp')}` "
                f"net_pnl=`{trade.get('net_pnl')}` holding_bars=`{trade.get('holding_bars')}` "
                f"reason=`{trade.get('exit_reason')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Capital Events", ""])
    if capital_events:
        for event in capital_events:
            lines.append(
                f"- `{event.get('ex_date')}` {event.get('action_type')} "
                f"quantity=`{event.get('quantity_before')} -> "
                f"{event.get('quantity_after')}` cash=`{event.get('cash_delta')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Cost Scenarios", ""])
    if cost_scenarios:
        for scenario in cost_scenarios:
            scenario_metrics = scenario.get("metrics") or {}
            lines.append(
                f"- `{scenario.get('name')}` multiplier=`{scenario.get('multiplier')}` "
                f"return=`{scenario_metrics.get('total_return_pct')}%` "
                f"drawdown=`{scenario_metrics.get('max_drawdown_pct')}%` "
                f"ok=`{scenario.get('ok', False)}`"
            )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_walk_forward_markdown(payload: Mapping[str, Any]) -> str:
    """Render chronological walk-forward and sealed-holdout evidence."""

    selected = payload.get("selected_candidate") or {}
    summary = payload.get("walk_forward_summary") or {}
    holdout = payload.get("holdout_trial") or {}
    request = payload.get("request", {})
    lines = [
        f"# {payload.get('title', 'SPY Walk-forward And Sealed Holdout Research')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Dataset fingerprint: `{payload.get('dataset_fingerprint')}`",
        f"- Catalog signal fingerprint: "
        f"`{payload.get('catalog_dataset_fingerprint')}`",
        f"- Catalog execution fingerprint: "
        f"`{payload.get('execution_dataset_fingerprint')}`",
        f"- Catalog benchmark fingerprint: "
        f"`{payload.get('benchmark_dataset_fingerprint')}`",
        f"- Corporate-action fingerprint: `{payload.get('action_fingerprint')}`",
        f"- Sizing mode: `{request.get('sizing_mode')}`",
        f"- Signal/execution timestamps aligned: "
        f"`{payload.get('signal_execution_timestamps_aligned', False)}`",
        f"- Development fingerprint: `{payload.get('development_fingerprint')}`",
        f"- Holdout fingerprint: `{payload.get('holdout_fingerprint')}`",
        f"- Candidate specification fingerprint: "
        f"`{payload.get('candidate_spec_fingerprint')}`",
        f"- Walk-forward completed: `{payload.get('walk_forward_completed', False)}`",
        f"- Holdout partition sealed before selection: "
        f"`{payload.get('holdout_partition_sealed_before_selection', False)}`",
        f"- Holdout used for selection: `{payload.get('holdout_used_for_selection', True)}`",
        f"- Holdout evaluation count: `{payload.get('holdout_evaluation_count', 0)}`",
        f"- Research validation completed: "
        f"`{payload.get('research_validation_completed', False)}`",
        f"- Promotion eligible: `{payload.get('promotion_eligible', False)}`",
        f"- Non-promotion reason: `{payload.get('non_promotion_reason')}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        "",
        "## Walk-forward Summary",
        "",
        f"- Completed folds: `{summary.get('completed_fold_count', 0)}`",
        f"- Unique selected candidates: "
        f"`{summary.get('unique_selected_candidate_count', 0)}`",
        f"- Compounded next-period return: "
        f"`{summary.get('compounded_validation_return_pct')}%`",
        f"- Worst next-period drawdown: "
        f"`{summary.get('worst_validation_drawdown_pct')}%`",
        f"- Next-period closed trades: "
        f"`{summary.get('total_validation_closed_trades', 0)}`",
        "",
        "## Fold Evidence",
        "",
    ]
    folds = payload.get("folds", [])
    if folds:
        for fold in folds:
            candidate = fold.get("selected_candidate") or {}
            validation = fold.get("validation_trial") or {}
            lines.append(
                f"- Fold `{fold.get('fold_index')}`: train=`{fold.get('train_bar_count')}` "
                f"validation=`{fold.get('validation_bar_count')}` selected="
                f"`{candidate.get('short_window')}:{candidate.get('long_window')}` "
                f"validation_return=`{validation.get('total_return_pct')}%` "
                f"validation_drawdown=`{validation.get('max_drawdown_pct')}%` "
                f"selection_used_validation=`{fold.get('selection_used_validation_data')}`"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Final Sealed Holdout",
            "",
            f"- Selected candidate: "
            f"`{selected.get('short_window')}:{selected.get('long_window')}`",
            f"- Selection score: `{payload.get('selected_development_score')}`",
            f"- Eligible: `{holdout.get('eligible', False)}`",
            f"- Return: `{holdout.get('total_return_pct')}%`",
            f"- Net P&L: `{holdout.get('net_pnl')}`",
            f"- Maximum drawdown: `{holdout.get('max_drawdown_pct')}%`",
            f"- Closed trades: `{holdout.get('closed_trade_count', 0)}`",
            "",
            "Operator rerun prevention is not enforced by software. Treat the final "
            "holdout as consumed after its first recorded evaluation.",
        ]
    )
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_experiment_markdown(payload: Mapping[str, Any]) -> str:
    """Render preregistration, annual validation, and holdout-access evidence."""

    diagnostics = payload.get("statistical_diagnostics") or {}
    holdout = payload.get("holdout_result") or {}
    lines = [
        f"# {payload.get('title', 'SPY Preregistered Research Experiment')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Experiment ID: `{payload.get('experiment_id')}`",
        f"- Phase: `{payload.get('phase')}`",
        f"- Spec fingerprint: `{payload.get('spec_fingerprint')}`",
        f"- Spec tracked in Git: `{payload.get('spec_git_tracked', False)}`",
        f"- Worktree clean: `{payload.get('worktree_clean', False)}`",
        f"- Commit SHA: `{payload.get('commit_sha')}`",
        f"- Strategy fingerprint: `{payload.get('strategy_fingerprint')}`",
        f"- Config fingerprint: `{payload.get('config_fingerprint')}`",
        f"- Environment fingerprint: `{payload.get('environment_fingerprint')}`",
        f"- Signal dataset: `{payload.get('signal_dataset_fingerprint')}`",
        f"- Execution dataset: `{payload.get('execution_dataset_fingerprint')}`",
        f"- Benchmark dataset: `{payload.get('benchmark_dataset_fingerprint')}`",
        f"- Corporate actions: `{payload.get('action_fingerprint')}`",
        f"- Holdout access recorded: "
        f"`{payload.get('holdout_access_recorded', False)}`",
        f"- Holdout consumed: `{payload.get('holdout_access_consumed', False)}`",
        f"- Research review ready: `{payload.get('research_review_ready', False)}`",
        f"- Promotion eligible: `{payload.get('promotion_eligible', False)}`",
        "",
        "## Acceptance Gates",
        "",
        f"- Positive validation years: "
        f"`{payload.get('positive_validation_year_count', 0)}`",
        f"- Aggregate validation base return: "
        f"`{payload.get('aggregate_validation_base_return_pct')}%`",
        f"- Aggregate validation 2x-cost return: "
        f"`{payload.get('aggregate_validation_two_x_return_pct')}%`",
        f"- Validation-year gate: `{payload.get('validation_year_gate_passed', False)}`",
        f"- 2x-cost gate: `{payload.get('two_x_cost_gate_passed', False)}`",
        f"- Holdout return: `{holdout.get('base_return_pct')}%`",
        f"- Holdout return gate: `{payload.get('holdout_return_gate_passed', False)}`",
        f"- Deflated Sharpe probability: "
        f"`{diagnostics.get('deflated_sharpe_probability')}`",
        f"- Deflated Sharpe gate: "
        f"`{payload.get('deflated_sharpe_gate_passed', False)}`",
        f"- Holdout drawdown: `{holdout.get('max_drawdown_pct')}%`",
        f"- Holdout benchmark drawdown: "
        f"`{payload.get('holdout_benchmark_drawdown_pct')}%`",
        f"- Holdout drawdown gate: "
        f"`{payload.get('holdout_drawdown_gate_passed', False)}`",
        "",
        "## Annual Validation",
        "",
    ]
    folds = payload.get("validation_folds", [])
    if folds:
        for fold in folds:
            candidate = fold.get("selected_candidate") or {}
            result = fold.get("validation_result") or {}
            lines.append(
                f"- `{fold.get('validation_year')}` selected="
                f"`{candidate.get('short_window')}:{candidate.get('long_window')}` "
                f"base=`{result.get('base_return_pct')}%` "
                f"2x=`{result.get('two_x_cost_return_pct')}%` "
                f"ok=`{fold.get('ok', False)}`"
            )
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_vendor_decision_markdown(payload: Mapping[str, Any]) -> str:
    """Render rights-first vendor scoring and procurement evidence."""

    results = payload.get("candidate_results", [])
    lines = [
        f"# {payload.get('title', 'SPY Research Data Vendor Decision')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Manifest: `{payload.get('manifest_path')}`",
        f"- Selected vendor: `{payload.get('selected_vendor') or 'none'}`",
        f"- Procurement blocked: `{payload.get('procurement_blocked', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Credentials read: `{payload.get('credentials_read', True)}`",
        f"- Network accessed: `{payload.get('network_accessed', True)}`",
        "",
        "## Candidates",
        "",
    ]
    if results:
        for result in results:
            lines.append(
                f"- `{result.get('vendor')}` score=`{result.get('weighted_score')}` "
                f"TCO=`${result.get('three_year_tco_usd')}` "
                f"rights=`{result.get('rights_gate_passed', False)}` "
                f"bakeoff=`{result.get('bakeoff_gate_passed', False)}` "
                f"budget=`{result.get('budget_gate_passed', False)}` "
                f"selected=`{result.get('selected', False)}`"
            )
            for reason in result.get("reasons", []):
                lines.append(f"  - Rejected: {reason}")
    else:
        lines.append("- None")
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_instrument_master_markdown(payload: Mapping[str, Any]) -> str:
    """Render immutable SPY identity registration evidence."""

    record = payload.get("record") or {}
    lines = [
        f"# {payload.get('title', 'SPY Research Instrument Master')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Manifest: `{payload.get('manifest_path')}`",
        f"- Catalog: `{payload.get('catalog_path')}`",
        f"- Internal ID: `{record.get('internal_id')}`",
        f"- Version: `{record.get('version')}`",
        f"- Symbol: `{record.get('symbol')}`",
        f"- IBKR conId: `{record.get('ibkr_con_id')}`",
        f"- Composite FIGI: `{record.get('composite_figi')}`",
        f"- Primary/routing exchange: "
        f"`{record.get('primary_exchange')}/{record.get('routing_exchange')}`",
        f"- Record fingerprint: `{payload.get('record_fingerprint')}`",
        f"- Idempotent replay: `{payload.get('idempotent_replay', False)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Credentials read: `{payload.get('credentials_read', True)}`",
        f"- Network accessed: `{payload.get('network_accessed', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        f"- Promotion eligible: `{payload.get('promotion_eligible', True)}`",
    ]
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
    return "\n".join(lines) + "\n"


def research_experiment_registration_markdown(payload: Mapping[str, Any]) -> str:
    """Render permanent experiment-registration and holdout-seal evidence."""

    seal = payload.get("sealed_period") or {}
    environment = payload.get("environment_manifest") or {}
    lines = [
        f"# {payload.get('title', 'SPY Research Experiment Registration')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Experiment ID: `{payload.get('experiment_id')}`",
        f"- Superseded experiment: `{payload.get('superseded_experiment_id')}`",
        f"- Spec fingerprint: `{payload.get('spec_fingerprint')}`",
        f"- Spec tracked in Git: `{payload.get('spec_git_tracked', False)}`",
        f"- Worktree clean: `{payload.get('worktree_clean', False)}`",
        f"- Commit SHA: `{payload.get('commit_sha')}`",
        f"- Idempotent replay: `{payload.get('idempotent_replay', False)}`",
        f"- Catalog: `{payload.get('catalog_path')}`",
        "",
        "## Permanent Holdout Seal",
        "",
        f"- Symbol: `{seal.get('symbol')}`",
        f"- Start: `{seal.get('start_date')}`",
        f"- End: `{seal.get('end_date')}`",
        f"- Purpose: `{seal.get('purpose')}`",
        "",
        "## Environment",
        "",
        f"- Dependency lock: `{environment.get('dependency_lock_path')}`",
        f"- Dependency fingerprint: `{environment.get('dependency_lock_fingerprint')}`",
        f"- Python: `{environment.get('python_version')}`",
        f"- IBKR API: `{environment.get('ibapi_version')}`",
        f"- Environment fingerprint: `{environment.get('environment_fingerprint')}`",
    ]
    lines.extend(_warnings_and_errors(payload.get("warnings", []), payload.get("errors", [])))
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
        f"- Warmup assembly completed: "
        f"`{payload.get('warmup_assembly_completed', False)}`",
        f"- Warmup prior sessions: "
        f"`{_join_or_none(payload.get('warmup_prior_session_dates', []))}`",
        f"- Warmup current live bars: "
        f"`{payload.get('warmup_current_live_bar_count', 0)}`",
        f"- Warmup assembled bars: `{payload.get('warmup_assembled_bar_count', 0)}`",
        f"- Warmup boundary agreement: "
        f"`{payload.get('warmup_boundary_agreement_passed', False)}`",
        f"- Warmup data fingerprint: `{payload.get('warmup_data_fingerprint')}`",
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
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
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


def alpha_shadow_daemon_markdown(payload: Mapping[str, Any]) -> str:
    """Render the controlled read-only alpha shadow daemon report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    cycles = payload.get("cycles", [])

    lines = [
        f"# {payload.get('title', 'Read-only IBKR Alpha Shadow Daemon')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'alpha-shadow-daemon')}`",
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Release fingerprint: `{payload.get('release_fingerprint')}`",
        f"- Release worktree clean: `{payload.get('release_worktree_clean', False)}`",
        f"- Config fingerprint: `{payload.get('config_fingerprint')}`",
        f"- Strategy fingerprint: `{payload.get('strategy_fingerprint')}`",
        f"- Data fingerprint: `{payload.get('data_fingerprint')}`",
        f"- Trading dates: `{_join_or_none(payload.get('trading_dates', []))}`",
        f"- Coverage windows: `{_join_or_none(payload.get('coverage_windows', []))}`",
        f"- Cycles: `{payload.get('cycle_count', 0)}`",
        f"- Clean cycles: `{payload.get('clean_cycle_count', 0)}`",
        f"- Data policy: `{payload.get('market_data_policy', 'strict_live')}`",
        f"- Delayed data mode: `{payload.get('delayed_data_mode', False)}`",
        f"- Graduation eligible: `{payload.get('graduation_eligible', True)}`",
        f"- Session evidence ready: `{payload.get('session_evidence_ready', False)}`",
        f"- Graduation ready: `{payload.get('graduation_ready', False)}`",
        "- Non-graduating reason: "
        f"`{payload.get('non_graduating_reason') or 'n/a'}`",
        f"- Broker-connected cycles: `{payload.get('broker_connected_cycles', 0)}`",
        "- Account-summary verified cycles: "
        f"`{payload.get('account_summary_verified_cycles', 0)}`",
        f"- Stale data detected: `{payload.get('stale_data_detected', False)}`",
        f"- Halted by kill switch: `{payload.get('halted_by_kill_switch', False)}`",
        f"- Heartbeat path: `{payload.get('heartbeat_path', 'unknown')}`",
        f"- Kill switch path: `{payload.get('kill_switch_path', 'unknown')}`",
        f"- Submitted orders: `{payload.get('submitted_orders', True)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', True)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', True)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Alpha shadow daemon safety scope unavailable.")),
        "",
        str(payload.get("commodity_scope", "Commodity scope unavailable.")),
        "",
        "## Cycles",
        "",
    ]
    if isinstance(cycles, list) and cycles:
        for cycle in cycles:
            if not isinstance(cycle, Mapping):
                continue
            lines.append(
                "- "
                f"`{cycle.get('cycle_index', 'n/a')}` "
                f"status=`{cycle.get('final_status', 'unknown')}` "
                f"ok=`{cycle.get('ok', False)}` "
                f"campaign_id=`{cycle.get('cycle_campaign_id', 'n/a')}` "
                f"broker=`{cycle.get('broker_connected', False)}` "
                f"account=`{cycle.get('account_summary_verified', False)}` "
                f"stale=`{cycle.get('stale_data_detected', False)}` "
                f"reports=`{len(cycle.get('shadow_report_paths', {}))}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Source Bars", ""])
    source_bar_lines = 0
    if isinstance(cycles, list) and cycles:
        for cycle in cycles:
            if not isinstance(cycle, Mapping):
                continue
            source_bars = cycle.get("source_bar_timestamp_by_symbol", {})
            if not isinstance(source_bars, Mapping) or not source_bars:
                continue
            for symbol, timestamp in sorted(source_bars.items()):
                lines.append(
                    f"- cycle `{cycle.get('cycle_index', 'n/a')}` `{symbol}`: `{timestamp}`"
                )
                source_bar_lines += 1
    if source_bar_lines == 0:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def alpha_shadow_daemon_summary_markdown(payload: Mapping[str, Any]) -> str:
    """Render the offline alpha-shadow-daemon session summary."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    source_reports = payload.get("source_reports", [])
    next_reasons = payload.get("next_eligibility_reason", [])

    lines = [
        f"# {payload.get('title', 'IBKR Alpha Shadow Daemon Session Summary')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'alpha-shadow-daemon-summary')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Sessions: `{payload.get('session_count', 0)}`",
        f"- Clean sessions: `{payload.get('clean_session_count', 0)}`",
        f"- Minimum clean sessions: `{_request_value(payload, 'min_clean_sessions', 5)}`",
        f"- Distinct trading dates: "
        f"`{payload.get('distinct_trading_date_count', 0)}`",
        f"- Minimum distinct trading dates: "
        f"`{_request_value(payload, 'min_distinct_trading_dates', 5)}`",
        f"- Trading dates: `{_join_or_none(payload.get('trading_dates', []))}`",
        f"- Coverage windows: `{_join_or_none(payload.get('coverage_windows', []))}`",
        f"- Total cycles: `{payload.get('total_cycles', 0)}`",
        f"- Total clean cycles: `{payload.get('total_clean_cycles', 0)}`",
        f"- Stale sessions: `{payload.get('stale_session_count', 0)}`",
        f"- Stale cycles: `{payload.get('stale_cycle_count', 0)}`",
        f"- Broker-connected cycles: `{payload.get('broker_connected_cycles', 0)}`",
        "- Account-summary verified cycles: "
        f"`{payload.get('account_summary_verified_cycles', 0)}`",
        f"- Missing heartbeats: `{payload.get('missing_heartbeat_count', 0)}`",
        f"- Heartbeat mismatches: `{payload.get('heartbeat_mismatch_count', 0)}`",
        f"- Unclean releases: `{payload.get('unclean_release_count', 0)}`",
        f"- Safety violations: `{payload.get('safety_violation_count', 0)}`",
        f"- Graduation ready: `{payload.get('graduation_ready', False)}`",
        f"- Engineering pilot ready: "
        f"`{payload.get('engineering_pilot_ready', False)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', True)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', True)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', True)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Daemon summary safety scope unavailable.")),
        "",
        str(payload.get("commodity_scope", "Commodity scope unavailable.")),
        "",
        "## Source Reports",
        "",
    ]
    if isinstance(source_reports, list) and source_reports:
        for source in source_reports:
            if not isinstance(source, Mapping):
                continue
            lines.append(
                "- "
                f"`{source.get('source_report_path', 'unknown')}` "
                f"campaign=`{source.get('campaign_id', 'n/a')}` "
                f"status=`{source.get('final_status', 'unknown')}` "
                f"policy=`{source.get('market_data_policy', 'strict_live')}` "
                f"eligible=`{source.get('graduation_eligible', True)}` "
                f"cycles=`{source.get('cycle_count', 0)}` "
                f"clean=`{source.get('clean_cycle_count', 0)}` "
                f"broker=`{source.get('broker_connected_cycles', 0)}` "
                f"account=`{source.get('account_summary_verified_cycles', 0)}` "
                f"stale=`{source.get('stale_data_detected', False)}` "
                f"heartbeat=`{source.get('heartbeat_present', False)}` "
                f"release_clean=`{source.get('release_worktree_clean', False)}` "
                f"safety_flag=`{_source_safety_flag(source)}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Commit And Campaign Drift", ""])
    commit_shas = payload.get("commit_shas", [])
    campaign_ids = payload.get("campaign_ids", [])
    lines.append(f"- Source commits: `{_join_or_none(commit_shas)}`")
    lines.append(f"- Source campaigns: `{_join_or_none(campaign_ids)}`")
    lines.append(
        f"- Release fingerprints: "
        f"`{_join_or_none(payload.get('release_fingerprints', []))}`"
    )
    lines.append(
        f"- Config fingerprints: "
        f"`{_join_or_none(payload.get('config_fingerprints', []))}`"
    )
    lines.append(
        f"- Strategy fingerprints: "
        f"`{_join_or_none(payload.get('strategy_fingerprints', []))}`"
    )
    lines.append(
        f"- Data fingerprints: "
        f"`{_join_or_none(payload.get('data_fingerprints', []))}`"
    )

    lines.extend(["", "## Next Eligibility", ""])
    if isinstance(next_reasons, list) and next_reasons:
        lines.extend(f"- {reason}" for reason in next_reasons)
    else:
        lines.append("- None")

    lines.extend(["", "## Warning Fingerprints", ""])
    warning_fingerprints = payload.get("warning_fingerprints", [])
    if isinstance(warning_fingerprints, list) and warning_fingerprints:
        lines.extend(f"- {warning}" for warning in warning_fingerprints)
    else:
        lines.append("- None")

    lines.extend(["", "## Error Fingerprints", ""])
    error_fingerprints = payload.get("error_fingerprints", [])
    if isinstance(error_fingerprints, list) and error_fingerprints:
        lines.extend(f"- {error}" for error in error_fingerprints)
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
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
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
    source_campaigns = payload.get("source_report_campaign_ids", {})
    account_ids = payload.get("account_ids_masked", [])
    request_symbol = request.get("symbol", "unknown") if isinstance(request, Mapping) else "unknown"

    lines = [
        f"# {payload.get('title', 'IBKR Alpha Paper Run')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'alpha-paper-run')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- Symbol: `{request_symbol}`",
        f"- Shadow report verified: `{payload.get('alpha_shadow_report_verified', False)}`",
        f"- Paper smoke report verified: `{payload.get('paper_smoke_report_verified', False)}`",
        f"- Research report verified: "
        f"`{payload.get('research_experiment_report_verified', False)}`",
        f"- Research review ready: `{payload.get('research_review_ready', False)}`",
        f"- Strict shadow summary verified: "
        f"`{payload.get('strict_shadow_summary_report_verified', False)}`",
        f"- Strict shadow graduation ready: "
        f"`{payload.get('strict_shadow_graduation_ready', False)}`",
        f"- Strict shadow engineering pilot ready: "
        f"`{payload.get('strict_shadow_engineering_pilot_ready', False)}`",
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
            campaign = (
                source_campaigns.get(label, "n/a")
                if isinstance(source_campaigns, Mapping)
                else "n/a"
            )
            lines.append(f"- `{label}`: `{path}` campaign_id=`{campaign}`")
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


def paper_reconcile_markdown(payload: Mapping[str, Any]) -> str:
    """Render the read-only post-paper-run reconciliation report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    source_paths = payload.get("source_report_paths", {})
    source_campaigns = payload.get("source_report_campaign_ids", {})
    source_compatibility = payload.get("source_report_compatibility", {})
    account_ids = payload.get("account_ids_masked", [])
    open_orders = payload.get("open_orders", [])
    executions = payload.get("executions_snapshot", [])
    commissions = payload.get("commission_reports", [])
    evidence = payload.get("latest_order_evidence", [])

    lines = [
        f"# {payload.get('title', 'IBKR Paper Reconciliation')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'paper-reconcile')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Broker kind: `{payload.get('broker_kind', 'unknown')}`",
        f"- Host: `{payload.get('host', 'unknown')}`",
        f"- Port: `{payload.get('port', 'unknown')}`",
        f"- Client ID: `{payload.get('client_id', 'unknown')}`",
        f"- Broker connected: `{payload.get('broker_connected', False)}`",
        f"- Account summary verified: `{payload.get('account_summary_verified', False)}`",
        f"- Account summary source: `{payload.get('account_summary_source', 'unknown')}`",
        f"- Broker positions available: `{payload.get('broker_positions_available', False)}`",
        f"- Positions query completed: `{payload.get('positions_query_completed', False)}`",
        f"- Zero positions confirmed: `{payload.get('zero_positions_confirmed', False)}`",
        f"- Positions source: `{payload.get('positions_source', 'unknown')}`",
        f"- Positions unavailable reason: `{payload.get('positions_unavailable_reason', 'n/a')}`",
        f"- Open-order count: `{payload.get('open_order_count', 0)}`",
        f"- Open-order source: `{payload.get('open_order_source', 'unknown')}`",
        "- Open-orders query completed: "
        f"`{payload.get('open_orders_query_completed', False)}`",
        "- Zero open orders confirmed: "
        f"`{payload.get('zero_open_orders_confirmed', False)}`",
        f"- Executions available: `{payload.get('executions_available', False)}`",
        f"- Executions source: `{payload.get('executions_source', 'unknown')}`",
        "- Executions query completed: "
        f"`{payload.get('executions_query_completed', False)}`",
        "- Zero executions confirmed: "
        f"`{payload.get('zero_executions_confirmed', False)}`",
        f"- Execution order IDs: `{_sample_values(payload.get('execution_order_ids', []))}`",
        f"- Latest order IDs: `{_sample_values(payload.get('latest_order_ids', []))}`",
        f"- Latest perm IDs: `{_sample_values(payload.get('latest_perm_ids', []))}`",
        f"- Broker state fingerprint: `{payload.get('broker_state_fingerprint', 'n/a')}`",
        f"- Submitted orders: `{payload.get('submitted_orders', True)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', True)}`",
        f"- Configured allow paper orders: `{payload.get('configured_allow_paper_orders', True)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', True)}`",
        f"- Read-Only API expected: `{payload.get('read_only_api_expected', False)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        f"- No order guarantee: `{payload.get('no_order_guarantee', False)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Reconciliation safety scope unavailable.")),
        "",
        "## Source Reports",
        "",
    ]
    if isinstance(source_paths, Mapping) and source_paths:
        for label, path in sorted(source_paths.items()):
            campaign = (
                source_campaigns.get(label, "n/a")
                if isinstance(source_campaigns, Mapping)
                else "n/a"
            )
            compatibility = (
                source_compatibility.get(label, "unknown")
                if isinstance(source_compatibility, Mapping)
                else "unknown"
            )
            lines.append(
                f"- `{label}`: `{path}` campaign_id=`{campaign}` "
                f"compatibility=`{compatibility}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Masked Accounts", ""])
    if account_ids:
        lines.extend(f"- `{account_id}`" for account_id in account_ids)
    else:
        lines.append("- None")

    lines.extend(["", "## Open Orders", ""])
    if isinstance(open_orders, list) and open_orders:
        for item in open_orders:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- "
                f"order_id=`{item.get('order_id', 'n/a')}` "
                f"perm_id=`{item.get('perm_id', 'n/a')}` "
                f"symbol=`{item.get('symbol', 'unknown')}` "
                f"action=`{item.get('action', 'n/a')}` "
                f"status=`{item.get('status', 'n/a')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Executions", ""])
    if isinstance(executions, list) and executions:
        for item in executions:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- "
                f"order_id=`{item.get('order_id', 'n/a')}` "
                f"perm_id=`{item.get('perm_id', 'n/a')}` "
                f"exec_id=`{item.get('exec_id', 'n/a')}` "
                f"symbol=`{item.get('symbol', 'unknown')}` "
                f"side=`{item.get('side', 'n/a')}` "
                f"shares=`{item.get('shares', 'n/a')}` "
                f"price=`{item.get('price', 'n/a')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Commissions", ""])
    if isinstance(commissions, list) and commissions:
        for item in commissions:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- "
                f"exec_id=`{item.get('exec_id', 'n/a')}` "
                f"commission=`{item.get('commission', 'n/a')}` "
                f"currency=`{item.get('currency', 'n/a')}` "
                f"realized_pnl=`{item.get('realized_pnl', 'n/a')}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Latest Order Evidence", ""])
    if isinstance(evidence, list) and evidence:
        for item in evidence:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- "
                f"`{item.get('source', 'unknown')}` "
                f"status=`{item.get('final_status', 'unknown')}` "
                f"campaign_id=`{item.get('campaign_id', 'n/a')}` "
                f"submitted=`{item.get('submitted_orders', False)}` "
                f"order_id=`{item.get('order_id', 'n/a')}` "
                f"perm_id=`{item.get('perm_id', 'n/a')}` "
                f"fill_quantity=`{item.get('fill_quantity', 'n/a')}` "
                f"canceled=`{item.get('canceled', False)}`"
            )
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def alpha_test_summary_markdown(payload: Mapping[str, Any]) -> str:
    """Render the offline alpha campaign summary report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    source_paths = payload.get("source_report_paths", {})
    source_statuses = payload.get("source_report_statuses", {})
    source_commits = payload.get("source_report_commits", {})
    source_timestamps = payload.get("source_report_timestamps", {})
    source_campaigns = payload.get("source_report_campaign_ids", {})
    account_ids = payload.get("account_ids_masked", [])
    next_reasons = payload.get("next_eligibility_reason", [])

    lines = [
        f"# {payload.get('title', 'IBKR Alpha Test Summary')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'alpha-test-summary')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
        f"- Alpha shadow verified: `{payload.get('alpha_shadow_verified', False)}`",
        f"- Paper smoke verified: `{payload.get('paper_smoke_verified', False)}`",
        f"- Alpha paper verified: `{payload.get('alpha_paper_verified', False)}`",
        f"- Paper reconcile verified: `{payload.get('paper_reconcile_verified', False)}`",
        f"- Account summary verified: `{payload.get('account_summary_verified', False)}`",
        f"- Open-order count: `{payload.get('open_order_count', 'unknown')}`",
        f"- Latest order IDs: `{_sample_values(payload.get('latest_order_ids', []))}`",
        f"- Latest perm IDs: `{_sample_values(payload.get('latest_perm_ids', []))}`",
        f"- Paper smoke order status: `{payload.get('paper_smoke_order_status', 'n/a')}`",
        f"- Paper smoke fill quantity: `{payload.get('paper_smoke_fill_quantity', 'n/a')}`",
        f"- Paper smoke canceled: `{payload.get('paper_smoke_canceled', 'n/a')}`",
        f"- Alpha paper order status: `{payload.get('alpha_paper_order_status', 'n/a')}`",
        f"- Alpha paper fill quantity: `{payload.get('alpha_paper_fill_quantity', 'n/a')}`",
        f"- Alpha paper canceled: `{payload.get('alpha_paper_canceled', 'n/a')}`",
        f"- Submitted orders in source evidence: `{payload.get('submitted_orders', False)}`",
        f"- Paper orders enabled now: `{payload.get('paper_orders_enabled', True)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Order API invoked by summary: `{payload.get('order_api_invoked', True)}`",
        "- Next eligible for alpha window: "
        f"`{payload.get('next_eligible_for_alpha_window', False)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Alpha summary safety scope unavailable.")),
        "",
        str(payload.get("commodity_scope", "Commodity scope unavailable.")),
        "",
        "## Source Reports",
        "",
    ]
    if isinstance(source_paths, Mapping) and source_paths:
        for label, path in sorted(source_paths.items()):
            status = (
                source_statuses.get(label, "unknown")
                if isinstance(source_statuses, Mapping)
                else "unknown"
            )
            commit = (
                source_commits.get(label, "unknown")
                if isinstance(source_commits, Mapping)
                else "unknown"
            )
            timestamp = (
                source_timestamps.get(label, "unknown")
                if isinstance(source_timestamps, Mapping)
                else "unknown"
            )
            campaign = (
                source_campaigns.get(label, "n/a")
                if isinstance(source_campaigns, Mapping)
                else "n/a"
            )
            lines.append(
                "- "
                f"`{label}`: `{path}` status=`{status}` "
                f"commit=`{commit}` timestamp=`{timestamp}` campaign_id=`{campaign}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Masked Accounts", ""])
    if account_ids:
        lines.extend(f"- `{account_id}`" for account_id in account_ids)
    else:
        lines.append("- None")

    lines.extend(["", "## Next Eligibility", ""])
    if isinstance(next_reasons, list) and next_reasons:
        lines.extend(f"- {reason}" for reason in next_reasons)
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def alpha_campaign_run_markdown(payload: Mapping[str, Any]) -> str:
    """Render the sequential alpha campaign run report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    stages = payload.get("stages", [])
    report_paths = payload.get("report_paths", {})

    lines = [
        f"# {payload.get('title', 'IBKR Alpha Campaign Run')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'alpha-campaign-run')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
        f"- Mode: `{payload.get('mode', 'unknown')}`",
        f"- Alpha shadow completed: `{payload.get('alpha_shadow_completed', False)}`",
        f"- Alpha paper completed: `{payload.get('alpha_paper_completed', False)}`",
        f"- Paper reconcile completed: `{payload.get('paper_reconcile_completed', False)}`",
        f"- Alpha summary completed: `{payload.get('alpha_test_summary_completed', False)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', False)}`",
        f"- Paper orders enabled at finish: `{payload.get('paper_orders_enabled', True)}`",
        f"- Live orders enabled: `{payload.get('live_orders_enabled', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        f"- Read-Only restore required: `{payload.get('read_only_restore_required', False)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Alpha campaign safety scope unavailable.")),
        "",
        "## Stages",
        "",
    ]
    if isinstance(stages, list) and stages:
        for stage in stages:
            if not isinstance(stage, Mapping):
                continue
            lines.append(
                "- "
                f"`{stage.get('name', 'unknown')}` "
                f"status=`{stage.get('final_status', 'unknown')}` "
                f"ok=`{stage.get('ok', False)}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Report Paths", ""])
    if isinstance(report_paths, Mapping) and report_paths:
        for label, path in sorted(report_paths.items()):
            lines.append(f"- `{label}`: `{path}`")
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def paper_ledger_update_markdown(payload: Mapping[str, Any]) -> str:
    """Render the offline paper ledger update report."""

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    source_paths = payload.get("source_report_paths", {})
    ledger_entry = payload.get("ledger_entry") or {}
    next_reasons = (
        ledger_entry.get("next_eligibility_reason", [])
        if isinstance(ledger_entry, Mapping)
        else []
    )

    lines = [
        f"# {payload.get('title', 'IBKR Paper Ledger Update')}",
        "",
        f"- Timestamp: `{payload.get('timestamp', 'unknown')}`",
        f"- Command: `{payload.get('command', 'paper-ledger-update')}`",
        f"- Final status: `{payload.get('final_status', 'unknown')}`",
        f"- Commit SHA: `{payload.get('commit_sha', 'unknown')}`",
        f"- Campaign ID: `{payload.get('campaign_id', 'n/a')}`",
        f"- Ledger path: `{payload.get('ledger_path', 'unknown')}`",
        f"- Ledger entry written: `{payload.get('ledger_entry_written', False)}`",
        f"- Ledger record count: `{payload.get('ledger_record_count', 0)}`",
        f"- Replaced existing entry: `{payload.get('replaced_existing_entry', False)}`",
        f"- Submitted orders: `{payload.get('submitted_orders', False)}`",
        f"- Paper orders enabled: `{payload.get('paper_orders_enabled', True)}`",
        f"- Broker contacted: `{payload.get('broker_contacted', True)}`",
        f"- Order routing enabled: `{payload.get('order_routing_enabled', True)}`",
        f"- Order API invoked: `{payload.get('order_api_invoked', True)}`",
        "",
        "## Safety",
        "",
        str(payload.get("safety_statement", "Paper ledger safety scope unavailable.")),
        "",
        "## Source Reports",
        "",
    ]
    if isinstance(source_paths, Mapping) and source_paths:
        for label, path in sorted(source_paths.items()):
            lines.append(f"- `{label}`: `{path}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Ledger Entry", ""])
    if isinstance(ledger_entry, Mapping) and ledger_entry:
        lines.extend(
            [
                f"- Recorded at: `{ledger_entry.get('recorded_at', 'unknown')}`",
                f"- Account verified: `{ledger_entry.get('account_summary_verified', False)}`",
                f"- Open-order count: `{ledger_entry.get('open_order_count', 'unknown')}`",
                "- Positions query completed: "
                f"`{ledger_entry.get('positions_query_completed', False)}`",
                "- Zero positions confirmed: "
                f"`{ledger_entry.get('zero_positions_confirmed', False)}`",
                f"- Latest order IDs: `{_sample_values(ledger_entry.get('latest_order_ids', []))}`",
                f"- Latest perm IDs: `{_sample_values(ledger_entry.get('latest_perm_ids', []))}`",
                "- Paper smoke order status: "
                f"`{ledger_entry.get('paper_smoke_order_status', 'n/a')}`",
                "- Paper smoke fill quantity: "
                f"`{ledger_entry.get('paper_smoke_fill_quantity', 'n/a')}`",
                "- Paper smoke canceled: "
                f"`{ledger_entry.get('paper_smoke_canceled', 'n/a')}`",
                "- Alpha paper order status: "
                f"`{ledger_entry.get('alpha_paper_order_status', 'n/a')}`",
                "- Alpha paper fill quantity: "
                f"`{ledger_entry.get('alpha_paper_fill_quantity', 'n/a')}`",
                "- Alpha paper canceled: "
                f"`{ledger_entry.get('alpha_paper_canceled', 'n/a')}`",
                "- Broker-state fingerprint: "
                f"`{ledger_entry.get('broker_state_fingerprint', 'missing')}`",
                "- Next eligible for alpha window: "
                f"`{ledger_entry.get('next_eligible_for_alpha_window', False)}`",
            ]
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Next Eligibility", ""])
    if isinstance(next_reasons, list) and next_reasons:
        lines.extend(f"- {reason}" for reason in next_reasons)
    else:
        lines.append("- None")

    lines.extend(_warnings_and_errors(warnings, errors))
    return "\n".join(lines) + "\n"


def _request_value(payload: Mapping[str, Any], key: str, default: Any) -> Any:
    request = payload.get("request", {})
    if not isinstance(request, Mapping):
        return default
    return request.get(key, default)


def _source_safety_flag(source: Mapping[str, Any]) -> bool:
    return bool(
        source.get("submitted_orders", False)
        or source.get("paper_orders_enabled", False)
        or source.get("live_orders_enabled", False)
        or source.get("order_routing_enabled", False)
        or source.get("order_api_invoked", False)
    )


def _join_or_none(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return "none"
    return ", ".join(str(value) for value in values)


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
