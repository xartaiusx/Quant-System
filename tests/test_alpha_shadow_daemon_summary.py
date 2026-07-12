from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from trader.alpha_shadow_daemon_summary import run_alpha_shadow_daemon_summary
from trader.models import (
    AlphaShadowDaemonCycle,
    AlphaShadowDaemonReport,
    AlphaShadowDaemonRequest,
    AlphaShadowDaemonStatus,
    AlphaShadowDaemonSummaryRequest,
    AlphaShadowDaemonSummaryStatus,
    ShadowDataPolicy,
)
from trader.reporting.reports import markdown_summary

COMMIT_SHA = "abc123"


def now() -> datetime:
    return datetime(2026, 7, 13, 20, tzinfo=UTC)


def patch_current_commit(monkeypatch) -> None:
    monkeypatch.setattr(
        "trader.alpha_shadow_daemon_summary._current_commit_sha",
        lambda: COMMIT_SHA,
    )


def summary_request(tmp_path: Path, **overrides: object) -> AlphaShadowDaemonSummaryRequest:
    values: dict[str, object] = {
        "report_glob": (tmp_path / "reports" / "alpha_shadow_daemon_*.json").as_posix(),
        "min_clean_sessions": 5,
        "max_report_age_hours": 168,
        "require_same_commit": True,
    }
    values.update(overrides)
    return AlphaShadowDaemonSummaryRequest(**values)


def daemon_report(
    tmp_path: Path,
    *,
    campaign_id: str,
    commit_sha: str | None = COMMIT_SHA,
    timestamp: datetime | None = None,
    stale: bool = False,
    broker_connected: bool = True,
    account_verified: bool = True,
    write_heartbeat: bool = True,
    delayed: bool = False,
    release_clean: bool = True,
    trading_date: str = "2026-07-13",
    coverage_window: str = "opening",
) -> AlphaShadowDaemonReport:
    source_hour = {"opening": 14, "midday": 17, "closing": 19}[coverage_window]
    source_timestamp = datetime.fromisoformat(trading_date).replace(
        hour=source_hour,
        tzinfo=UTC,
    )
    heartbeat_path = tmp_path / "state" / f"{campaign_id}_heartbeat.json"
    if write_heartbeat:
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text(json.dumps({"campaign_id": campaign_id}))
    cycle = AlphaShadowDaemonCycle(
        cycle_index=1,
        cycle_campaign_id=f"{campaign_id}-cycle-001",
        ok=not stale,
        final_status=AlphaShadowDaemonStatus.FAILED
        if stale
        else AlphaShadowDaemonStatus.COMPLETED,
        started_at=timestamp or now(),
        finished_at=timestamp or now(),
        broker_connected=broker_connected,
        account_summary_verified=account_verified,
        source_bar_timestamp_by_symbol={
            "SPY": source_timestamp.isoformat()
        },
        stale_data_detected=stale,
        stale_symbols=["SPY"] if stale else [],
        heartbeat_written=write_heartbeat,
        errors=["stale source data detected for SPY"] if stale else [],
    )
    return AlphaShadowDaemonReport(
        ok=not stale,
        request=AlphaShadowDaemonRequest(
            campaign_id=campaign_id,
            max_cycles=1,
            heartbeat_path=heartbeat_path.as_posix(),
            kill_switch_path=(tmp_path / "state" / "kill").as_posix(),
        ),
        commit_sha=commit_sha,
        release_fingerprint=f"git:{commit_sha}" if commit_sha else None,
        release_worktree_clean=release_clean,
        config_fingerprint="sha256:config-v1",
        strategy_fingerprint="sha256:strategy-v1",
        data_fingerprint=f"sha256:data-{campaign_id}",
        trading_dates=[trading_date],
        coverage_windows=[coverage_window],
        campaign_id=campaign_id,
        cycles=[cycle],
        cycle_count=1,
        clean_cycle_count=0 if stale else 1,
        market_data_policy=(
            ShadowDataPolicy.DELAYED_ENGINEERING
            if delayed
            else ShadowDataPolicy.STRICT_LIVE
        ),
        delayed_data_mode=delayed,
        graduation_eligible=not delayed,
        non_graduating_reason=(
            "delayed_data_engineering_mode_cannot_graduate_to_paper_execution"
            if delayed
            else None
        ),
        graduation_ready=False,
        heartbeat_path=heartbeat_path.as_posix(),
        kill_switch_path=(tmp_path / "state" / "kill").as_posix(),
        stale_data_detected=stale,
        broker_connected_cycles=1 if broker_connected else 0,
        account_summary_verified_cycles=1 if account_verified else 0,
        errors=["stale source data detected for SPY"] if stale else [],
        final_status=AlphaShadowDaemonStatus.FAILED
        if stale
        else AlphaShadowDaemonStatus.COMPLETED_WITH_WARNINGS,
        timestamp=timestamp or now(),
    )


def write_daemon_report(
    tmp_path: Path,
    index: int,
    report: AlphaShadowDaemonReport,
) -> Path:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"alpha_shadow_daemon_20260706T150{index:02d}00Z.json"
    path.write_text(report.model_dump_json())
    return path


def write_clean_reports(tmp_path: Path, count: int = 5) -> None:
    trading_dates = [
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
    ]
    coverage_windows = [
        "opening",
        "opening",
        "midday",
        "midday",
        "closing",
        "opening",
        "midday",
        "closing",
        "opening",
        "closing",
    ]
    for index in range(count):
        write_daemon_report(
            tmp_path,
            index,
            daemon_report(
                tmp_path,
                campaign_id=f"campaign-clean-{index:03d}",
                trading_date=trading_dates[index],
                coverage_window=coverage_windows[index],
            ),
        )


def test_alpha_shadow_daemon_summary_marks_clean_sessions_graduation_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_clean_reports(tmp_path)

    report = run_alpha_shadow_daemon_summary(summary_request(tmp_path), now=now())

    assert report.ok is True
    assert report.graduation_ready is True
    assert report.clean_session_count == 5
    assert report.distinct_trading_date_count == 5
    assert report.engineering_pilot_ready is False
    assert report.total_cycles == 5
    assert report.broker_connected_cycles == 5
    assert report.account_summary_verified_cycles == 5
    assert report.missing_heartbeat_count == 0
    assert report.safety_violation_count == 0
    assert report.order_api_invoked is False


def test_alpha_shadow_daemon_summary_unlocks_pilot_only_after_ten_windowed_sessions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_clean_reports(tmp_path, count=10)

    report = run_alpha_shadow_daemon_summary(summary_request(tmp_path), now=now())

    assert report.graduation_ready is True
    assert report.engineering_pilot_ready is True
    assert report.clean_session_count == 10
    assert report.distinct_trading_date_count == 5
    assert report.coverage_windows == ["opening", "midday", "closing"]


def test_alpha_shadow_daemon_summary_fails_on_config_fingerprint_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_clean_reports(tmp_path)
    source = sorted((tmp_path / "reports").glob("alpha_shadow_daemon_*.json"))[-1]
    payload = json.loads(source.read_text())
    payload["config_fingerprint"] = "sha256:changed"
    source.write_text(json.dumps(payload))

    report = run_alpha_shadow_daemon_summary(summary_request(tmp_path), now=now())

    assert report.ok is False
    assert any("config fingerprint drift" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_fails_on_stale_data(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_daemon_report(
        tmp_path,
        0,
        daemon_report(tmp_path, campaign_id="campaign-stale", stale=True),
    )

    report = run_alpha_shadow_daemon_summary(
        summary_request(tmp_path, min_clean_sessions=1),
        now=now(),
    )

    assert report.ok is False
    assert report.final_status == AlphaShadowDaemonSummaryStatus.FAILED
    assert report.stale_session_count == 1
    assert any("stale source data" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_fails_on_missing_heartbeat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_daemon_report(
        tmp_path,
        0,
        daemon_report(
            tmp_path,
            campaign_id="campaign-missing-heartbeat",
            write_heartbeat=False,
        ),
    )

    report = run_alpha_shadow_daemon_summary(
        summary_request(tmp_path, min_clean_sessions=1),
        now=now(),
    )

    assert report.ok is False
    assert report.missing_heartbeat_count == 1
    assert any("missing heartbeat" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_fails_on_heartbeat_campaign_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    source = daemon_report(tmp_path, campaign_id="campaign-heartbeat-mismatch")
    Path(source.heartbeat_path).write_text(
        json.dumps({"campaign_id": "different-campaign"})
    )
    write_daemon_report(tmp_path, 0, source)

    report = run_alpha_shadow_daemon_summary(summary_request(tmp_path), now=now())

    assert report.ok is False
    assert report.heartbeat_mismatch_count == 1
    assert any("heartbeat campaign_id does not match" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_fails_on_unclean_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_daemon_report(
        tmp_path,
        0,
        daemon_report(
            tmp_path,
            campaign_id="campaign-dirty-release",
            release_clean=False,
        ),
    )

    report = run_alpha_shadow_daemon_summary(summary_request(tmp_path), now=now())

    assert report.ok is False
    assert report.unclean_release_count == 1
    assert any("clean committed worktree" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_fails_on_mismatched_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_daemon_report(
        tmp_path,
        0,
        daemon_report(tmp_path, campaign_id="campaign-old", commit_sha="def456"),
    )

    report = run_alpha_shadow_daemon_summary(
        summary_request(tmp_path, min_clean_sessions=1),
        now=now(),
    )

    assert report.ok is False
    assert any("different commit" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_fails_on_order_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    source_path = write_daemon_report(
        tmp_path,
        0,
        daemon_report(tmp_path, campaign_id="campaign-order-flag"),
    )
    payload = json.loads(source_path.read_text())
    payload["submitted_orders"] = True
    source_path.write_text(json.dumps(payload))

    report = run_alpha_shadow_daemon_summary(
        summary_request(tmp_path, min_clean_sessions=1),
        now=now(),
    )

    assert report.ok is False
    assert report.safety_violation_count == 1
    assert any("safety flag" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_rejects_delayed_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_daemon_report(
        tmp_path,
        0,
        daemon_report(tmp_path, campaign_id="campaign-delayed", delayed=True),
    )

    report = run_alpha_shadow_daemon_summary(
        summary_request(tmp_path, min_clean_sessions=1),
        now=now(),
    )

    assert report.ok is False
    assert report.graduation_ready is False
    assert report.clean_session_count == 0
    assert report.source_reports[0].delayed_data_mode is True
    assert report.source_reports[0].graduation_eligible is False
    assert any("non-graduating shadow evidence" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_fails_on_broker_account_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_daemon_report(
        tmp_path,
        0,
        daemon_report(
            tmp_path,
            campaign_id="campaign-account-gap",
            account_verified=False,
        ),
    )

    report = run_alpha_shadow_daemon_summary(
        summary_request(tmp_path, min_clean_sessions=1),
        now=now(),
    )

    assert report.ok is False
    assert report.account_summary_verified_cycles == 0
    assert any("account-summary evidence" in error for error in report.errors)


def test_alpha_shadow_daemon_summary_ignores_summary_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_clean_reports(tmp_path)
    summary_output = tmp_path / "reports" / "alpha_shadow_daemon_summary_20260706.json"
    summary_output.write_text(json.dumps({"report_type": "alpha_shadow_daemon_summary"}))

    report = run_alpha_shadow_daemon_summary(summary_request(tmp_path), now=now())

    assert report.ok is True
    assert report.session_count == 5
    assert summary_output.as_posix() not in report.source_report_paths


def test_alpha_shadow_daemon_summary_serializes_and_renders_markdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_current_commit(monkeypatch)
    write_clean_reports(tmp_path)

    report = run_alpha_shadow_daemon_summary(summary_request(tmp_path), now=now())
    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert payload["report_type"] == "alpha_shadow_daemon_summary"
    assert "IBKR Alpha Shadow Daemon Session Summary" in markdown
    assert "Graduation ready: `True`" in markdown
    assert "Order API invoked: `False`" in markdown
