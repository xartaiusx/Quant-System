from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trader.alpha_shadow_daemon import (
    run_alpha_shadow_daemon,
    run_delayed_alpha_shadow_daemon,
)
from trader.config import BrokerKind, TraderConfig, TradingMode
from trader.models import (
    AlphaShadowDaemonRequest,
    AlphaShadowDaemonStatus,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaShadowRunStatus,
    ShadowDataPolicy,
)
from trader.reporting.journal import Journal
from trader.reporting.reports import markdown_summary

CAMPAIGN_ID = "campaign-daemon-001"


def now() -> datetime:
    return datetime(2026, 7, 6, 14, 5, tzinfo=UTC)


def config(**overrides: object) -> TraderConfig:
    values: dict[str, object] = {
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 4002,
        "ibkr_client_id": 61,
        "broker_kind": BrokerKind.IB_GATEWAY,
        "trading_mode": TradingMode.PAPER,
        "allow_paper_orders": False,
        "allow_live_orders": False,
        "max_trade_notional": Decimal("1000"),
        "max_open_positions": 1,
    }
    values.update(overrides)
    return TraderConfig(**values)


def request(tmp_path: Path, **overrides: object) -> AlphaShadowDaemonRequest:
    values: dict[str, object] = {
        "campaign_id": CAMPAIGN_ID,
        "max_cycles": 2,
        "interval_seconds": 1,
        "stale_after_minutes": 60,
        "graduation_clean_sessions_required": 2,
        "kill_switch_path": (tmp_path / "state" / "kill").as_posix(),
        "heartbeat_path": (tmp_path / "state" / "heartbeat.json").as_posix(),
    }
    values.update(overrides)
    return AlphaShadowDaemonRequest(**values)


def shadow_report(
    shadow_request: AlphaShadowRunRequest,
    *,
    timestamp: datetime | None = None,
    ok: bool = True,
) -> AlphaShadowRunReport:
    return AlphaShadowRunReport(
        ok=ok,
        commit_sha="abc123",
        campaign_id=shadow_request.campaign_id,
        request=shadow_request,
        selected_universe=["SPY"],
        broker_connected=True,
        account_summary_verified=True,
        account_summary_source="broker_read_only_account_summary",
        account_ids_masked=["DUQ2****23"],
        history_snapshot_written=True,
        history_load_completed=True,
        data_quality_completed=True,
        data_quality_status_by_symbol={"SPY": "passed"},
        signal_evaluation_completed=True,
        trade_plan_completed=True,
        risk_completed=True,
        simulation_completed=True,
        source_bar_timestamp_by_symbol={
            "SPY": (timestamp or now()).isoformat(),
        },
        strategy_parameter_fingerprint="sha256:strategy",
        broker_contacted=True,
        simulator_routed=True,
        final_status=AlphaShadowRunStatus.COMPLETED
        if ok
        else AlphaShadowRunStatus.FAILED,
        errors=[] if ok else ["shadow failed"],
        timestamp=now(),
    )


def test_alpha_shadow_daemon_runs_clean_cycles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.alpha_shadow_daemon._current_commit_sha", lambda: "abc123")
    monkeypatch.setattr("trader.alpha_shadow_daemon._git_worktree_clean", lambda: True)
    seen_campaigns: list[str | None] = []
    sleeps: list[float] = []
    selected_request = request(tmp_path)

    def fake_shadow(
        _config: TraderConfig,
        shadow_request: AlphaShadowRunRequest,
    ) -> AlphaShadowRunReport:
        seen_campaigns.append(shadow_request.campaign_id)
        return shadow_report(shadow_request, timestamp=now() - timedelta(minutes=5))

    report = run_alpha_shadow_daemon(
        config(),
        selected_request,
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=fake_shadow,
        sleep_fn=sleeps.append,
        now_fn=now,
    )

    assert report.ok is True
    assert report.final_status == AlphaShadowDaemonStatus.COMPLETED_WITH_WARNINGS
    assert report.cycle_count == 2
    assert report.clean_cycle_count == 2
    assert report.session_evidence_ready is True
    assert report.graduation_ready is False
    assert report.release_fingerprint == "git:abc123"
    assert report.release_worktree_clean is True
    assert report.config_fingerprint is not None
    assert report.strategy_fingerprint is not None
    assert report.data_fingerprint is not None
    assert report.trading_dates == ["2026-07-06"]
    assert report.coverage_windows == ["opening"]
    assert report.submitted_orders is False
    assert report.paper_orders_enabled is False
    assert report.order_api_invoked is False
    assert seen_campaigns == [
        f"{CAMPAIGN_ID}-cycle-001",
        f"{CAMPAIGN_ID}-cycle-002",
    ]
    assert sleeps == [1.0]
    assert Path(report.heartbeat_path).exists()
    assert Path(selected_request.heartbeat_path).exists()
    assert report.heartbeat_path != selected_request.heartbeat_path
    assert json.loads(Path(report.heartbeat_path).read_text())["campaign_id"] == CAMPAIGN_ID


def test_alpha_shadow_daemon_rejects_reused_campaign_heartbeat(tmp_path: Path) -> None:
    selected_request = request(tmp_path, max_cycles=1)
    Path(selected_request.heartbeat_path).parent.mkdir(parents=True, exist_ok=True)
    first = run_alpha_shadow_daemon(
        config(),
        selected_request,
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=lambda _config, item: shadow_report(item),
        now_fn=now,
    )

    second = run_alpha_shadow_daemon(
        config(),
        selected_request,
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=lambda _config, item: shadow_report(item),
        now_fn=now,
    )

    assert first.cycle_count == 1
    assert second.ok is False
    assert second.cycle_count == 0
    assert "campaign-specific heartbeat already exists" in " ".join(second.errors)


def test_alpha_shadow_daemon_halts_on_kill_switch(tmp_path: Path) -> None:
    selected_request = request(tmp_path)
    kill_path = Path(selected_request.kill_switch_path)
    kill_path.parent.mkdir(parents=True)
    kill_path.write_text("stop")

    report = run_alpha_shadow_daemon(
        config(),
        selected_request,
        journal=Journal(tmp_path / "reports"),
        now_fn=now,
    )

    assert report.ok is True
    assert report.final_status == AlphaShadowDaemonStatus.HALTED
    assert report.halted_by_kill_switch is True
    assert report.cycle_count == 0
    assert Path(report.heartbeat_path).exists()


def test_alpha_shadow_daemon_fails_on_stale_source_data(tmp_path: Path) -> None:
    def fake_shadow(
        _config: TraderConfig,
        shadow_request: AlphaShadowRunRequest,
    ) -> AlphaShadowRunReport:
        return shadow_report(shadow_request, timestamp=now() - timedelta(hours=3))

    report = run_alpha_shadow_daemon(
        config(),
        request(tmp_path, max_cycles=1, stale_after_minutes=60),
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=fake_shadow,
        now_fn=now,
    )

    assert report.ok is False
    assert report.final_status == AlphaShadowDaemonStatus.FAILED
    assert report.stale_data_detected is True
    assert report.cycles[0].stale_symbols == ["SPY"]
    assert "stale source data" in " ".join(report.errors)


def test_alpha_shadow_daemon_uses_zoned_bar_interval_end_for_freshness(
    tmp_path: Path,
) -> None:
    def fake_shadow(
        _config: TraderConfig,
        shadow_request: AlphaShadowRunRequest,
    ) -> AlphaShadowRunReport:
        return shadow_report(shadow_request).model_copy(
            update={
                "source_bar_timestamp_by_symbol": {
                    "SPY": "20260706 12:10:00 US/Eastern"
                }
            }
        )

    report = run_alpha_shadow_daemon(
        config(),
        request(tmp_path, max_cycles=1, stale_after_minutes=30),
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=fake_shadow,
        now_fn=lambda: datetime(2026, 7, 6, 16, 42, tzinfo=UTC),
    )

    assert report.ok is True
    assert report.stale_data_detected is False
    assert report.clean_cycle_count == 1


def test_alpha_shadow_daemon_rejects_paper_order_config(tmp_path: Path) -> None:
    report = run_alpha_shadow_daemon(
        config(allow_paper_orders=True),
        request(tmp_path),
        journal=Journal(tmp_path / "reports"),
        now_fn=now,
    )

    assert report.ok is False
    assert report.final_status == AlphaShadowDaemonStatus.FAILED
    assert report.cycle_count == 0
    assert "ALLOW_PAPER_ORDERS=true" in " ".join(report.errors)


def test_alpha_shadow_daemon_markdown_rendering(tmp_path: Path) -> None:
    def fake_shadow(
        _config: TraderConfig,
        shadow_request: AlphaShadowRunRequest,
    ) -> AlphaShadowRunReport:
        return shadow_report(shadow_request, timestamp=now() - timedelta(minutes=1))

    report = run_alpha_shadow_daemon(
        config(),
        request(tmp_path, max_cycles=1, graduation_clean_sessions_required=1),
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=fake_shadow,
        now_fn=now,
    )
    markdown = markdown_summary(report.model_dump(mode="json"))

    assert "# Read-only IBKR Alpha Shadow Daemon" in markdown
    assert "alpha-shadow-daemon" in markdown
    assert "Session evidence ready: `True`" in markdown
    assert "Graduation ready: `False`" in markdown
    assert "Order API invoked: `False`" in markdown


def test_delayed_alpha_shadow_daemon_is_non_graduating(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("trader.alpha_shadow_daemon._current_commit_sha", lambda: "abc123")

    def fake_shadow(
        _config: TraderConfig,
        shadow_request: AlphaShadowRunRequest,
    ) -> AlphaShadowRunReport:
        return shadow_report(shadow_request, timestamp=now() - timedelta(minutes=18))

    report = run_delayed_alpha_shadow_daemon(
        config(),
        request(tmp_path, max_cycles=1, stale_after_minutes=30),
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=fake_shadow,
        now_fn=now,
    )

    assert report.ok is True
    assert report.command == "alpha-shadow-daemon-delayed"
    assert report.report_type == "alpha_shadow_daemon_delayed"
    assert report.market_data_policy == ShadowDataPolicy.DELAYED_ENGINEERING
    assert report.delayed_data_mode is True
    assert report.graduation_eligible is False
    assert report.graduation_ready is False
    assert report.clean_cycle_count == 1
    assert report.submitted_orders is False
    assert report.paper_orders_enabled is False
    assert report.order_api_invoked is False
    assert "non-graduating" in " ".join(report.warnings)


def test_delayed_alpha_shadow_daemon_markdown_blocks_graduation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_shadow_daemon._current_commit_sha", lambda: "abc123")

    def fake_shadow(
        _config: TraderConfig,
        shadow_request: AlphaShadowRunRequest,
    ) -> AlphaShadowRunReport:
        return shadow_report(shadow_request, timestamp=now() - timedelta(minutes=18))

    report = run_delayed_alpha_shadow_daemon(
        config(),
        request(tmp_path, max_cycles=1, stale_after_minutes=30),
        journal=Journal(tmp_path / "reports"),
        alpha_shadow_runner=fake_shadow,
        now_fn=now,
    )
    markdown = markdown_summary(report.model_dump(mode="json"))

    assert "Delayed-data IBKR Alpha Shadow Daemon" in markdown
    assert "Data policy: `delayed_engineering`" in markdown
    assert "Graduation eligible: `False`" in markdown
    assert "Graduation ready: `False`" in markdown
