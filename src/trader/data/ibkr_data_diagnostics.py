"""Offline IBKR data freshness diagnostics for strict shadow readiness."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from trader.models import (
    BrokerDiagnosticReport,
    HistoricalReadinessReport,
    HistoricalSnapshotReport,
    IBKRDataDiagnosticsReport,
    IBKRDataDiagnosticsRequest,
    IBKRDataDiagnosticsStatus,
    MarketDataDiagnosticReport,
    utc_now,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def build_ibkr_data_diagnostics_report(
    request: IBKRDataDiagnosticsRequest | None = None,
    *,
    now: datetime | None = None,
) -> IBKRDataDiagnosticsReport:
    """Diagnose strict SPY data readiness from ignored local reports only."""

    selected_request = request or IBKRDataDiagnosticsRequest()
    current_time = now or utc_now()
    current_commit = _current_commit_sha()
    source_paths = {
        "broker_probe_report": selected_request.broker_probe_report_path,
        "history_snapshot_report": selected_request.history_snapshot_report_path,
        "history_readiness_report": selected_request.history_readiness_report_path,
    }
    if selected_request.market_probe_report_path is not None:
        source_paths["market_probe_report"] = selected_request.market_probe_report_path

    warnings: list[str] = []
    errors: list[str] = []

    broker_report, broker_payload, broker_errors = _load_report(
        Path(selected_request.broker_probe_report_path),
        BrokerDiagnosticReport,
        label="broker-probe report",
    )
    snapshot_report, snapshot_payload, snapshot_errors = _load_report(
        Path(selected_request.history_snapshot_report_path),
        HistoricalSnapshotReport,
        label="history-snapshot report",
    )
    readiness_report, readiness_payload, readiness_errors = _load_report(
        Path(selected_request.history_readiness_report_path),
        HistoricalReadinessReport,
        label="history-readiness report",
    )
    market_payload: Mapping[str, Any] | None = None
    market_report: MarketDataDiagnosticReport | None = None
    if selected_request.market_probe_report_path is not None:
        market_path = Path(selected_request.market_probe_report_path)
        if market_path.exists():
            market_report, market_payload, market_errors = _load_report(
                market_path,
                MarketDataDiagnosticReport,
                label="market-probe report",
            )
            errors.extend(market_errors)
        else:
            warnings.append("market-probe report is unavailable; market-data type is inferred")

    errors.extend(broker_errors)
    errors.extend(snapshot_errors)
    errors.extend(readiness_errors)

    if broker_report is not None:
        errors.extend(
            _shared_commit_errors(
                _payload_commit_sha(broker_payload),
                current_commit,
                "broker-probe",
            )
        )
    if snapshot_report is not None:
        errors.extend(
            _shared_commit_errors(
                _payload_commit_sha(snapshot_payload),
                current_commit,
                "history-snapshot",
            )
        )
    if readiness_report is not None:
        errors.extend(
            _shared_commit_errors(
                _payload_commit_sha(readiness_payload),
                current_commit,
                "history-readiness",
            )
        )
    if market_report is not None:
        market_commit_errors = _shared_commit_errors(
            _payload_commit_sha(market_payload),
            current_commit,
            "market-probe",
        )
        if market_commit_errors:
            warnings.extend(market_commit_errors)

    broker_probe_ok = bool(broker_report and broker_report.ok)
    broker_connected = bool(broker_report and broker_report.connected)
    broker_account_verified = bool(
        broker_report and broker_report.ok and broker_report.managed_accounts_masked
    )
    if broker_report is not None and not broker_account_verified:
        errors.append("broker-probe lacks managed-account evidence")

    snapshot_ok = bool(snapshot_report and snapshot_report.ok)
    readiness_ok = bool(readiness_report and readiness_report.ok)
    if snapshot_report is not None and not snapshot_ok:
        errors.append("history-snapshot report did not pass")
    if readiness_report is not None and not readiness_ok:
        errors.append("history-readiness report did not pass")
    if snapshot_report is not None:
        errors.extend(_request_setting_errors(selected_request, snapshot_report))

    bar_context = _bar_context(selected_request, snapshot_report, current_time)
    bar_count_passed = bar_context.bar_count >= selected_request.min_bars
    freshness_passed = (
        bar_context.latest_bar_age_seconds is not None
        and bar_context.latest_bar_age_seconds
        <= selected_request.stale_after_minutes * 60
    )
    if not bar_count_passed:
        errors.append(
            f"{selected_request.symbol} bars observed {bar_context.bar_count}; "
            f"expected at least {selected_request.min_bars}"
        )
    if not freshness_passed:
        if bar_context.latest_bar_age_minutes is None:
            errors.append(f"{selected_request.symbol} latest bar timestamp is unavailable")
        else:
            errors.append(
                f"{selected_request.symbol} latest bar age "
                f"{bar_context.latest_bar_age_minutes:.2f} minutes exceeds "
                f"{selected_request.stale_after_minutes} minutes"
            )

    market_requested, market_received = _market_data_context(market_report)
    market_hint = _market_data_hint(
        latest_bar_age_minutes=bar_context.latest_bar_age_minutes,
        stale_after_minutes=selected_request.stale_after_minutes,
        market_data_type_requested=market_requested,
        market_data_type_received=market_received,
    )
    strict_shadow_ready = (
        broker_probe_ok
        and broker_connected
        and broker_account_verified
        and snapshot_ok
        and readiness_ok
        and bar_count_passed
        and freshness_passed
        and not errors
    )
    operator_hints = _operator_hints(
        broker_account_verified=broker_account_verified,
        bar_count_passed=bar_count_passed,
        freshness_passed=freshness_passed,
        latest_bar_age_minutes=bar_context.latest_bar_age_minutes,
    )
    final_status = _final_status(errors=errors, warnings=warnings)
    return IBKRDataDiagnosticsReport(
        ok=final_status != IBKRDataDiagnosticsStatus.FAILED,
        request=selected_request,
        commit_sha=current_commit,
        source_report_paths=source_paths,
        symbol=selected_request.symbol,
        broker_probe_ok=broker_probe_ok,
        broker_connected=broker_connected,
        broker_account_verified=broker_account_verified,
        broker_failure_stage=broker_report.failure_stage if broker_report else None,
        history_snapshot_ok=snapshot_ok,
        history_readiness_ok=readiness_ok,
        snapshot_timestamp=snapshot_report.timestamp if snapshot_report else None,
        bar_count=bar_context.bar_count,
        min_bars=selected_request.min_bars,
        bar_count_passed=bar_count_passed,
        first_bar_timestamp=bar_context.first_bar_timestamp,
        latest_bar_timestamp=bar_context.latest_bar_timestamp,
        latest_bar_age_seconds=bar_context.latest_bar_age_seconds,
        latest_bar_age_minutes=bar_context.latest_bar_age_minutes,
        stale_after_minutes=selected_request.stale_after_minutes,
        freshness_passed=freshness_passed,
        market_data_type_requested=market_requested,
        market_data_type_received=market_received,
        market_data_type_hint=market_hint,
        strict_shadow_precheck_passed=strict_shadow_ready,
        next_recommended_action=_next_action(strict_shadow_ready, errors),
        operator_hints=operator_hints,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
        final_status=final_status,
    )


class _BarContext:
    def __init__(
        self,
        *,
        bar_count: int,
        first_bar_timestamp: str | None,
        latest_bar_timestamp: str | None,
        latest_bar_age_seconds: float | None,
    ) -> None:
        self.bar_count = bar_count
        self.first_bar_timestamp = first_bar_timestamp
        self.latest_bar_timestamp = latest_bar_timestamp
        self.latest_bar_age_seconds = latest_bar_age_seconds

    @property
    def latest_bar_age_minutes(self) -> float | None:
        if self.latest_bar_age_seconds is None:
            return None
        return self.latest_bar_age_seconds / 60


def _bar_context(
    request: IBKRDataDiagnosticsRequest,
    snapshot_report: HistoricalSnapshotReport | None,
    now: datetime,
) -> _BarContext:
    if snapshot_report is None:
        return _BarContext(
            bar_count=0,
            first_bar_timestamp=None,
            latest_bar_timestamp=None,
            latest_bar_age_seconds=None,
        )
    result = next(
        (item for item in snapshot_report.results if item.symbol == request.symbol),
        None,
    )
    snapshot_path = result.snapshot_path if result is not None else None
    if snapshot_path is None and snapshot_report.snapshot_paths:
        snapshot_path = snapshot_report.snapshot_paths[0]
    bars = _load_snapshot_rows(snapshot_path)
    if bars:
        first_bar = _optional_str(bars[0].get("timestamp"))
        latest_bar = _optional_str(bars[-1].get("timestamp"))
        return _BarContext(
            bar_count=len(bars),
            first_bar_timestamp=first_bar,
            latest_bar_timestamp=latest_bar,
            latest_bar_age_seconds=_bar_age_seconds(latest_bar, snapshot_report.timestamp),
        )
    manifest = result.manifest if result is not None else None
    latest_bar = manifest.last_bar_time if manifest is not None else None
    first_bar = manifest.first_bar_time if manifest is not None else None
    return _BarContext(
        bar_count=manifest.bar_count if manifest is not None else 0,
        first_bar_timestamp=first_bar,
        latest_bar_timestamp=latest_bar,
        latest_bar_age_seconds=_bar_age_seconds(latest_bar, now),
    )


def _load_snapshot_rows(snapshot_path: str | None) -> list[Mapping[str, Any]]:
    if snapshot_path is None:
        return []
    path = Path(snapshot_path)
    if not path.exists():
        return []
    rows: list[Mapping[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(payload)
    return rows


def _bar_age_seconds(value: str | None, report_timestamp: datetime) -> float | None:
    parsed = _parse_ibkr_bar_timestamp(value, report_timestamp)
    if parsed is None:
        return None
    return max(0.0, (report_timestamp.astimezone() - parsed).total_seconds())


def _parse_ibkr_bar_timestamp(value: str | None, report_timestamp: datetime) -> datetime | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    parsed: datetime | None = None
    for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        return parsed.astimezone()
    return parsed.replace(tzinfo=report_timestamp.astimezone().tzinfo)


def _market_data_context(
    market_report: MarketDataDiagnosticReport | None,
) -> tuple[str | None, str | None]:
    if market_report is None:
        return None, None
    requested = str(market_report.market_data_type_requested)
    received = next(
        (
            str(quote.market_data_type.received)
            for quote in market_report.quote_snapshots
            if quote.market_data_type.received is not None
        ),
        None,
    )
    return requested, received


def _request_setting_errors(
    request: IBKRDataDiagnosticsRequest,
    snapshot_report: HistoricalSnapshotReport,
) -> list[str]:
    errors: list[str] = []
    snapshot_request = snapshot_report.request
    if snapshot_request.duration != request.expected_duration:
        errors.append(
            "history-snapshot duration "
            f"{snapshot_request.duration!r} did not match {request.expected_duration!r}"
        )
    if snapshot_request.bar_size != request.expected_bar_size:
        errors.append(
            "history-snapshot bar size "
            f"{snapshot_request.bar_size!r} did not match {request.expected_bar_size!r}"
        )
    if snapshot_request.what_to_show.upper() != request.expected_what_to_show:
        errors.append(
            "history-snapshot what_to_show "
            f"{snapshot_request.what_to_show!r} did not match "
            f"{request.expected_what_to_show!r}"
        )
    if snapshot_request.use_rth != request.expected_use_rth:
        errors.append(
            "history-snapshot use_rth "
            f"{snapshot_request.use_rth!r} did not match {request.expected_use_rth!r}"
        )
    return errors


def _market_data_hint(
    *,
    latest_bar_age_minutes: float | None,
    stale_after_minutes: int,
    market_data_type_requested: str | None,
    market_data_type_received: str | None,
) -> str:
    if latest_bar_age_minutes is None:
        return "latest_bar_timestamp_missing"
    if latest_bar_age_minutes <= stale_after_minutes:
        return "historical_bars_fresh_for_strict_shadow"
    if latest_bar_age_minutes <= 20:
        return "historical_bars_match_common_delayed_data_lag"
    if market_data_type_requested or market_data_type_received:
        return "check_market_data_permissions_and_requested_type"
    return "historical_bars_lag_strict_shadow_gate"


def _operator_hints(
    *,
    broker_account_verified: bool,
    bar_count_passed: bool,
    freshness_passed: bool,
    latest_bar_age_minutes: float | None,
) -> list[str]:
    hints: list[str] = []
    if not broker_account_verified:
        hints.append(
            "Rerun broker-probe with a fresh client ID or longer timeout before daemon work."
        )
    if not bar_count_passed:
        hints.append("Wait for more regular-session SPY 5-minute bars before retrying.")
    if not freshness_passed:
        hints.append(
            "Do not relax stale_after_minutes for autonomous readiness; diagnose IBKR "
            "data permissions or delayed-data behavior first."
        )
        if latest_bar_age_minutes is not None and latest_bar_age_minutes <= 20:
            hints.append(
                "The latest-bar lag is within the common delayed-market-data range; "
                "confirm live US equities data permissions if strict real-time shadow "
                "readiness is required."
            )
    if not hints:
        hints.append("Strict precheck passed; alpha-shadow-daemon may run read-only.")
    return hints


def _next_action(strict_shadow_ready: bool, errors: list[str]) -> str:
    if strict_shadow_ready:
        return "run_alpha_shadow_daemon"
    if any("latest bar age" in error for error in errors):
        return "keep_shadow_daemon_blocked_and_investigate_ibkr_data_lag"
    if any("broker-probe" in error or "managed-account" in error for error in errors):
        return "rerun_broker_probe_with_fresh_client_id_or_longer_timeout"
    return "keep_shadow_daemon_blocked_until_diagnostics_pass"


def _final_status(
    *,
    errors: list[str],
    warnings: list[str],
) -> IBKRDataDiagnosticsStatus:
    if errors:
        return IBKRDataDiagnosticsStatus.FAILED
    if warnings:
        return IBKRDataDiagnosticsStatus.COMPLETED_WITH_WARNINGS
    return IBKRDataDiagnosticsStatus.COMPLETED


def _load_report(
    path: Path,
    model: type[ModelT],
    *,
    label: str,
) -> tuple[ModelT | None, Mapping[str, Any] | None, list[str]]:
    if not path.exists():
        return None, None, [f"{label} not found at {path.as_posix()}"]
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, [f"{label} could not be read: {exc}"]
    if not isinstance(payload, Mapping):
        return None, None, [f"{label} did not contain a JSON object"]
    try:
        return model.model_validate(payload), payload, []
    except ValueError as exc:
        return None, payload, [f"{label} is invalid: {exc}"]


def _payload_commit_sha(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return _optional_str(payload.get("commit_sha"))


def _shared_commit_errors(
    report_commit: str | None,
    current_commit: str | None,
    label: str,
) -> list[str]:
    if not report_commit:
        return [f"{label} lacks commit_sha; rerun the source command"]
    if current_commit is None:
        return ["current git commit could not be determined"]
    if report_commit != current_commit:
        return [f"{label} was generated from a different commit"]
    return []


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


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
