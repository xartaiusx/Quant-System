"""Controlled read-only alpha shadow daemon."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any

from trader.alpha_shadow import run_alpha_shadow_run
from trader.config import PAPER_PORTS, TraderConfig, TradingMode
from trader.models import (
    AlphaShadowDaemonCycle,
    AlphaShadowDaemonReport,
    AlphaShadowDaemonRequest,
    AlphaShadowDaemonStatus,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    ShadowDataPolicy,
    new_campaign_id,
    utc_now,
)
from trader.reporting.journal import Journal

AlphaShadowRunner = Callable[[TraderConfig, AlphaShadowRunRequest], AlphaShadowRunReport]
SleepFn = Callable[[float], None]
NowFn = Callable[[], datetime]


def run_alpha_shadow_daemon(
    config: TraderConfig,
    request: AlphaShadowDaemonRequest | None = None,
    *,
    journal: Journal | None = None,
    alpha_shadow_runner: AlphaShadowRunner = run_alpha_shadow_run,
    sleep_fn: SleepFn = time.sleep,
    now_fn: NowFn = utc_now,
) -> AlphaShadowDaemonReport:
    """Run controlled read-only SPY shadow cycles."""

    selected_request = _request_with_campaign_id(request or AlphaShadowDaemonRequest())
    selected_journal = journal or Journal()
    warnings = [
        "alpha-shadow-daemon is read-only and must run with IBKR Read-Only API enabled.",
        "ALLOW_PAPER_ORDERS=false is required for every daemon cycle.",
        "The daemon writes ignored local heartbeat evidence and never routes orders.",
    ]
    errors = _config_errors(config)
    cycles: list[AlphaShadowDaemonCycle] = []
    halted_by_kill_switch = False

    if not errors:
        for cycle_index in range(1, selected_request.max_cycles + 1):
            if _kill_switch_active(selected_request.kill_switch_path):
                halted_by_kill_switch = True
                warnings.append("alpha-shadow-daemon halted by kill-switch file")
                break

            cycle = _run_cycle(
                config,
                selected_request,
                cycle_index=cycle_index,
                journal=selected_journal,
                alpha_shadow_runner=alpha_shadow_runner,
                now_fn=now_fn,
            )
            cycles.append(cycle)
            _write_heartbeat(selected_request, cycles, halted=False)
            cycles[-1] = cycle.model_copy(update={"heartbeat_written": True})

            if not cycle.ok:
                errors.extend(cycle.errors)
                break
            if cycle_index < selected_request.max_cycles:
                sleep_fn(float(selected_request.interval_seconds))

    final_status = _final_status(
        cycles=cycles,
        errors=errors,
        warnings=warnings,
        halted_by_kill_switch=halted_by_kill_switch,
    )
    _write_heartbeat(selected_request, cycles, halted=halted_by_kill_switch)
    return _build_report(
        selected_request,
        cycles=cycles,
        warnings=warnings,
        errors=errors,
        halted_by_kill_switch=halted_by_kill_switch,
        final_status=final_status,
    )


def run_delayed_alpha_shadow_daemon(
    config: TraderConfig,
    request: AlphaShadowDaemonRequest | None = None,
    *,
    journal: Journal | None = None,
    alpha_shadow_runner: AlphaShadowRunner = run_alpha_shadow_run,
    sleep_fn: SleepFn = time.sleep,
    now_fn: NowFn = utc_now,
) -> AlphaShadowDaemonReport:
    """Run delayed-data engineering shadow cycles that can never graduate."""

    selected_request = request or AlphaShadowDaemonRequest(stale_after_minutes=30)
    report = run_alpha_shadow_daemon(
        config,
        selected_request,
        journal=journal,
        alpha_shadow_runner=alpha_shadow_runner,
        sleep_fn=sleep_fn,
        now_fn=now_fn,
    )
    warnings = _unique(
        [
            *report.warnings,
            "Delayed-data shadow mode is engineering-only and non-graduating.",
            "Delayed-data shadow evidence must not unlock SPY paper execution.",
        ]
    )
    return report.model_copy(
        update={
            "title": "Delayed-data IBKR Alpha Shadow Daemon",
            "report_type": "alpha_shadow_daemon_delayed",
            "command": "alpha-shadow-daemon-delayed",
            "market_data_policy": ShadowDataPolicy.DELAYED_ENGINEERING,
            "delayed_data_mode": True,
            "graduation_eligible": False,
            "graduation_ready": False,
            "non_graduating_reason": (
                "delayed_data_engineering_mode_cannot_graduate_to_paper_execution"
            ),
            "warnings": warnings,
            "safety_statement": (
                "alpha-shadow-daemon-delayed runs controlled read-only SPY shadow "
                "cycles for engineering practice only. It expects IBKR Read-Only API "
                "to stay enabled, requires ALLOW_PAPER_ORDERS=false, labels reports "
                "as delayed-data evidence, and never invokes broker order APIs."
            ),
        }
    )


def _run_cycle(
    config: TraderConfig,
    request: AlphaShadowDaemonRequest,
    *,
    cycle_index: int,
    journal: Journal,
    alpha_shadow_runner: AlphaShadowRunner,
    now_fn: NowFn,
) -> AlphaShadowDaemonCycle:
    started_at = now_fn()
    cycle_campaign_id = f"{request.campaign_id}-cycle-{cycle_index:03d}"
    warnings: list[str] = []
    errors: list[str] = []
    shadow_report: AlphaShadowRunReport | None = None
    shadow_paths: dict[str, str] = {}

    try:
        shadow_report = alpha_shadow_runner(
            config,
            _shadow_request(request, cycle_campaign_id),
        )
        json_path, md_path = journal.write_cycle(
            "alpha_shadow_run",
            shadow_report.model_dump(mode="json"),
        )
        shadow_paths = {"json": json_path.as_posix(), "markdown": md_path.as_posix()}
    except Exception as exc:
        errors.append(f"alpha-shadow-run cycle raised {type(exc).__name__}: {exc}")

    stale_symbols: list[str] = []
    if shadow_report is not None:
        warnings.extend(shadow_report.warnings)
        if not shadow_report.ok:
            errors.extend(shadow_report.errors or ["alpha-shadow-run cycle failed"])
        if shadow_report.submitted_orders:
            errors.append("alpha-shadow-run unexpectedly submitted orders")
        if shadow_report.paper_orders_enabled:
            errors.append("alpha-shadow-run unexpectedly enabled paper orders")
        if shadow_report.live_orders_enabled:
            errors.append("alpha-shadow-run unexpectedly enabled live orders")
        if shadow_report.order_routing_enabled:
            errors.append("alpha-shadow-run unexpectedly enabled order routing")
        stale_symbols = _stale_symbols(
            shadow_report.source_bar_timestamp_by_symbol,
            now=now_fn(),
            stale_after_minutes=request.stale_after_minutes,
        )
        if stale_symbols:
            errors.append(
                "stale source data detected for "
                + ", ".join(stale_symbols)
                + f" beyond {request.stale_after_minutes} minutes"
            )

    final_status = (
        AlphaShadowDaemonStatus.FAILED
        if errors
        else AlphaShadowDaemonStatus.COMPLETED_WITH_WARNINGS
        if warnings
        else AlphaShadowDaemonStatus.COMPLETED
    )
    return AlphaShadowDaemonCycle(
        cycle_index=cycle_index,
        cycle_campaign_id=cycle_campaign_id,
        ok=final_status != AlphaShadowDaemonStatus.FAILED,
        final_status=final_status,
        started_at=started_at,
        finished_at=now_fn(),
        shadow_report_paths=shadow_paths,
        shadow_final_status=_enum_value(shadow_report.final_status)
        if shadow_report is not None
        else None,
        broker_connected=bool(shadow_report and shadow_report.broker_connected),
        account_summary_verified=bool(
            shadow_report and shadow_report.account_summary_verified
        ),
        source_bar_timestamp_by_symbol=(
            dict(shadow_report.source_bar_timestamp_by_symbol)
            if shadow_report is not None
            else {}
        ),
        stale_data_detected=bool(stale_symbols),
        stale_symbols=stale_symbols,
        warnings=_unique(warnings),
        errors=_unique(errors),
        submitted_orders=bool(shadow_report and shadow_report.submitted_orders),
        paper_orders_enabled=bool(shadow_report and shadow_report.paper_orders_enabled),
        live_orders_enabled=bool(shadow_report and shadow_report.live_orders_enabled),
        order_routing_enabled=bool(shadow_report and shadow_report.order_routing_enabled),
    )


def _shadow_request(
    request: AlphaShadowDaemonRequest,
    cycle_campaign_id: str,
) -> AlphaShadowRunRequest:
    return AlphaShadowRunRequest(
        campaign_id=cycle_campaign_id,
        symbols=[request.symbol],
        duration=request.duration,
        bar_size=request.bar_size,
        what_to_show=request.what_to_show,
        use_rth=request.use_rth,
        broker_timeout_seconds=request.broker_timeout_seconds,
        history_timeout_seconds=request.history_timeout_seconds,
        broker_stage_pause_seconds=request.broker_stage_pause_seconds,
        base_data_path=request.base_data_path,
        short_window=request.short_window,
        long_window=request.long_window,
        min_bars=request.min_bars,
        max_zero_volume_bars=request.max_zero_volume_bars,
        min_average_volume=request.min_average_volume,
        min_average_dollar_volume=request.min_average_dollar_volume,
        max_trade_notional=request.max_trade_notional,
        max_open_positions=request.max_open_positions,
    )


def _build_report(
    request: AlphaShadowDaemonRequest,
    *,
    cycles: list[AlphaShadowDaemonCycle],
    warnings: list[str],
    errors: list[str],
    halted_by_kill_switch: bool,
    final_status: AlphaShadowDaemonStatus,
) -> AlphaShadowDaemonReport:
    clean_cycle_count = sum(1 for cycle in cycles if cycle.ok and not cycle.stale_data_detected)
    return AlphaShadowDaemonReport(
        ok=final_status != AlphaShadowDaemonStatus.FAILED,
        request=request,
        commit_sha=_current_commit_sha(),
        campaign_id=request.campaign_id,
        cycles=cycles,
        cycle_count=len(cycles),
        clean_cycle_count=clean_cycle_count,
        graduation_ready=(
            clean_cycle_count >= request.graduation_clean_sessions_required
            and not errors
            and not halted_by_kill_switch
        ),
        heartbeat_path=request.heartbeat_path,
        kill_switch_path=request.kill_switch_path,
        halted_by_kill_switch=halted_by_kill_switch,
        stale_data_detected=any(cycle.stale_data_detected for cycle in cycles),
        broker_connected_cycles=sum(1 for cycle in cycles if cycle.broker_connected),
        account_summary_verified_cycles=sum(
            1 for cycle in cycles if cycle.account_summary_verified
        ),
        warnings=_unique(warnings),
        errors=_unique(errors),
        final_status=final_status,
    )


def _write_heartbeat(
    request: AlphaShadowDaemonRequest,
    cycles: list[AlphaShadowDaemonCycle],
    *,
    halted: bool,
) -> None:
    heartbeat_path = Path(request.heartbeat_path)
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "report_type": "alpha_shadow_daemon_heartbeat",
        "campaign_id": request.campaign_id,
        "timestamp": utc_now().isoformat(),
        "cycle_count": len(cycles),
        "last_cycle_status": _enum_value(cycles[-1].final_status) if cycles else None,
        "last_cycle_campaign_id": cycles[-1].cycle_campaign_id if cycles else None,
        "halted": halted,
        "submitted_orders": False,
        "paper_orders_enabled": False,
        "order_routing_enabled": False,
        "order_api_invoked": False,
    }
    heartbeat_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _stale_symbols(
    source_timestamps: dict[str, str],
    *,
    now: datetime,
    stale_after_minutes: int,
) -> list[str]:
    stale_symbols: list[str] = []
    for symbol, raw_timestamp in source_timestamps.items():
        parsed = _parse_timestamp(raw_timestamp)
        if parsed is None:
            stale_symbols.append(symbol)
            continue
        if (now.astimezone(UTC) - parsed.astimezone(UTC)).total_seconds() > (
            stale_after_minutes * 60
        ):
            stale_symbols.append(symbol)
    if not source_timestamps:
        stale_symbols.append("SPY")
    return stale_symbols


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = " ".join(value.split())
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d"):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=_local_tzinfo()).astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(UTC)
    return parsed.replace(tzinfo=_local_tzinfo()).astimezone(UTC)


def _local_tzinfo() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC


def _config_errors(config: TraderConfig) -> list[str]:
    errors: list[str] = []
    if config.ibkr_host != "127.0.0.1":
        errors.append("IBKR_HOST must be 127.0.0.1 for alpha-shadow-daemon")
    if config.ibkr_port not in PAPER_PORTS:
        errors.append(
            "IBKR_PORT must be 7497 (TWS paper) or 4002 (IB Gateway paper) "
            "for alpha-shadow-daemon"
        )
    if config.allow_paper_orders:
        errors.append("ALLOW_PAPER_ORDERS=true is not accepted for alpha-shadow-daemon")
    if config.allow_live_orders:
        errors.append("ALLOW_LIVE_ORDERS=true is not accepted")
    if config.trading_mode != TradingMode.PAPER:
        errors.append("TRADING_MODE must be paper for alpha-shadow-daemon")
    return errors


def _request_with_campaign_id(
    request: AlphaShadowDaemonRequest,
) -> AlphaShadowDaemonRequest:
    if request.campaign_id:
        return request
    return request.model_copy(update={"campaign_id": new_campaign_id()})


def _kill_switch_active(path: str) -> bool:
    return Path(path).exists()


def _final_status(
    *,
    cycles: list[AlphaShadowDaemonCycle],
    errors: list[str],
    warnings: list[str],
    halted_by_kill_switch: bool,
) -> AlphaShadowDaemonStatus:
    if errors or any(cycle.final_status == AlphaShadowDaemonStatus.FAILED for cycle in cycles):
        return AlphaShadowDaemonStatus.FAILED
    if halted_by_kill_switch:
        return AlphaShadowDaemonStatus.HALTED
    if warnings or any(
        cycle.final_status == AlphaShadowDaemonStatus.COMPLETED_WITH_WARNINGS
        for cycle in cycles
    ):
        return AlphaShadowDaemonStatus.COMPLETED_WITH_WARNINGS
    return AlphaShadowDaemonStatus.COMPLETED


def _current_commit_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit_sha = result.stdout.strip()
    return commit_sha or None


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
