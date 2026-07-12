from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trader.alpha_paper import ALPHA_PAPER_CONFIRMATION, run_alpha_paper_run
from trader.config import BrokerKind, TraderConfig, TradingMode
from trader.execution.paper_order_smoke import (
    PaperBrokerAccountSummary,
    PaperBrokerOpenOrder,
    PaperBrokerPlacementResult,
)
from trader.models import (
    AlphaPaperRunRequest,
    AlphaPaperRunStatus,
    AlphaShadowDaemonReportEvidence,
    AlphaShadowDaemonSummaryReport,
    AlphaShadowDaemonSummaryRequest,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaShadowRunStatus,
    PaperOrderCallbackEvent,
    PaperOrderQuote,
    PaperOrderSmokeReport,
    PaperOrderSmokeRequest,
    PaperOrderSmokeRunStatus,
    ResearchEnvironmentManifest,
    ResearchExperimentPhase,
    ResearchExperimentReport,
    ResearchExperimentRequest,
    Signal,
    SignalDirection,
    TradeAction,
)
from trader.reporting.reports import markdown_summary

CAMPAIGN_ID = "campaign-001"


def now() -> datetime:
    return datetime(2026, 7, 4, 14, tzinfo=UTC)


def config(**overrides: object) -> TraderConfig:
    values: dict[str, object] = {
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 4002,
        "ibkr_client_id": 21,
        "broker_kind": BrokerKind.IB_GATEWAY,
        "trading_mode": TradingMode.PAPER,
        "allow_paper_orders": True,
        "allow_live_orders": False,
        "max_trade_notional": Decimal("1000"),
        "max_open_positions": 1,
    }
    values.update(overrides)
    return TraderConfig(**values)


def request(**overrides: object) -> AlphaPaperRunRequest:
    values: dict[str, object] = {
        "confirm": ALPHA_PAPER_CONFIRMATION,
        "cancel_after_seconds": 0,
    }
    values.update(overrides)
    return AlphaPaperRunRequest(**values)


def shadow_report(
    *,
    commit_sha: str = "abc123",
    campaign_id: str | None = CAMPAIGN_ID,
    direction: SignalDirection = SignalDirection.BUY,
) -> AlphaShadowRunReport:
    signal_count = 1 if direction else 0
    trade_count = 1 if direction == SignalDirection.BUY else 0
    risk_count = 1 if direction == SignalDirection.BUY else 0
    return AlphaShadowRunReport(
        ok=True,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=AlphaShadowRunRequest(),
        selected_universe=["SPY"],
        account_summary_verified=True,
        signal_evaluation_completed=True,
        shadow_signals=[
            Signal(
                symbol="SPY",
                direction=direction,
                strategy="alpha_shadow_moving_average",
                reason="test",
            )
        ],
        shadow_signal_count=signal_count,
        trade_plan_count=trade_count,
        risk_decision_count=risk_count,
        risk_approved_count=risk_count,
        final_status=AlphaShadowRunStatus.COMPLETED,
        timestamp=now(),
    )


def smoke_report(
    *,
    commit_sha: str = "abc123",
    campaign_id: str | None = CAMPAIGN_ID,
    ok: bool = True,
    transmitted: bool = True,
    submitted_orders: bool = True,
    canceled: bool = True,
) -> PaperOrderSmokeReport:
    return PaperOrderSmokeReport(
        ok=ok,
        commit_sha=commit_sha,
        campaign_id=campaign_id,
        request=PaperOrderSmokeRequest(
            confirm="PAPER_SMOKE_SPY_1",
            transmit=transmitted,
            cancel_after_seconds=0,
        ),
        mode="paper",
        host="127.0.0.1",
        port=4002,
        client_id=21,
        broker_kind="ib_gateway",
        broker_connected=True,
        account_summary_verified=True,
        submitted_orders=submitted_orders,
        paper_orders_enabled=True,
        configured_allow_paper_orders=True,
        order_api_invoked=True,
        place_order_invoked=True,
        cancel_order_invoked=canceled,
        transmitted=transmitted,
        order_id=2,
        perm_id=1234,
        order_status="Cancelled" if canceled else "Submitted",
        cancel_requested=canceled,
        canceled=canceled,
        final_status=PaperOrderSmokeRunStatus.COMPLETED if ok else PaperOrderSmokeRunStatus.FAILED,
        timestamp=now(),
    )


def write_report(path: Path, report: object) -> Path:
    payload = report.model_dump(mode="json")
    path.write_text(json.dumps(payload))
    return path


def promotion_paths(tmp_path: Path) -> dict[str, str]:
    environment = ResearchEnvironmentManifest(
        commit_sha="abc123",
        worktree_clean=True,
        dependency_lock_path="requirements.lock",
        dependency_lock_fingerprint="sha256:lock",
        pyproject_fingerprint="sha256:pyproject",
        python_version="3.11.9",
        ibapi_version="10.48.1",
        strategy_fingerprint="sha256:strategy",
        config_fingerprint="sha256:config",
        environment_fingerprint="sha256:environment",
    )
    research = ResearchExperimentReport(
        ok=True,
        request=ResearchExperimentRequest(
            spec_path="research/experiments/spy_sma_2016_2025_v2.json",
            root_path="D:/MarketData/Quant-System",
            phase=ResearchExperimentPhase.FINAL_HOLDOUT,
        ),
        experiment_id="spy-sma-2016-2025-v2",
        phase=ResearchExperimentPhase.FINAL_HOLDOUT,
        spec_path="research/experiments/spy_sma_2016_2025_v2.json",
        spec_git_tracked=True,
        worktree_clean=True,
        commit_sha="abc123",
        environment_manifest=environment,
        environment_fingerprint=environment.environment_fingerprint,
        holdout_access_recorded=True,
        holdout_access_consumed=True,
        research_review_ready=True,
        final_status="completed",
        timestamp=now(),
    )
    evidence = [
        AlphaShadowDaemonReportEvidence(source_report_path=f"reports/daemon-{index}.json")
        for index in range(10)
    ]
    strict = AlphaShadowDaemonSummaryReport(
        ok=True,
        request=AlphaShadowDaemonSummaryRequest(),
        commit_sha="abc123",
        source_report_paths=[item.source_report_path for item in evidence],
        source_reports=evidence,
        session_count=10,
        clean_session_count=10,
        distinct_trading_date_count=5,
        trading_dates=[f"2026-07-{day:02d}" for day in range(6, 11)],
        coverage_windows=["opening", "midday", "closing"],
        graduation_ready=True,
        engineering_pilot_ready=True,
        final_status="completed",
        timestamp=now(),
    )
    research_path = write_report(tmp_path / "research.json", research)
    strict_path = write_report(tmp_path / "strict-summary.json", strict)
    return {
        "research_experiment_report_path": research_path.as_posix(),
        "strict_shadow_summary_report_path": strict_path.as_posix(),
    }


class FakePaperOrderBroker:
    def __init__(self, *, fail_order: bool = False) -> None:
        self.fail_order = fail_order
        self.connected = False
        self.place_calls = 0
        self.cancel_calls = 0

    def connect(self, *, timeout: float) -> None:
        del timeout
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def request_account_summary(self, *, timeout: float) -> PaperBrokerAccountSummary:
        del timeout
        return PaperBrokerAccountSummary(
            account_ids_masked=["DUQ2****23"],
            verified=True,
            warnings=[],
            errors=[],
        )

    def request_open_orders(self, *, timeout: float) -> list[PaperBrokerOpenOrder]:
        del timeout
        return []

    def request_quote(
        self,
        symbol: str,
        *,
        timeout: float,
        max_age_seconds: int,
    ) -> PaperOrderQuote:
        del timeout, max_age_seconds
        return PaperOrderQuote(
            symbol=symbol,
            bid=Decimal("730.00"),
            ask=Decimal("730.10"),
            last=Decimal("730.05"),
            stale=False,
        )

    def place_limit_order(
        self,
        *,
        symbol: str,
        action: TradeAction,
        quantity: int,
        limit_price: Decimal,
        time_in_force: str,
        transmit: bool,
        timeout: float,
    ) -> PaperBrokerPlacementResult:
        del symbol, action, quantity, limit_price, time_in_force, transmit, timeout
        self.place_calls += 1
        return PaperBrokerPlacementResult(
            order_id=10,
            perm_id=10010,
            status=None if self.fail_order else "Submitted",
            fill_quantity=Decimal("0"),
            remaining_quantity=Decimal("1"),
            accepted=not self.fail_order,
            submitted_to_broker=not self.fail_order,
            canceled=False,
            terminal=False,
            callback_timeline=[
                PaperOrderCallbackEvent(
                    event_type="openOrder",
                    order_id=10,
                    perm_id=10010,
                    status="Submitted",
                )
            ],
            warnings=[],
            errors=["broker rejected order"] if self.fail_order else [],
        )

    def cancel_order(self, order_id: int | None, *, timeout: float) -> PaperBrokerPlacementResult:
        del timeout
        self.cancel_calls += 1
        return PaperBrokerPlacementResult(
            order_id=order_id,
            perm_id=10010,
            status="Cancelled",
            fill_quantity=Decimal("0"),
            remaining_quantity=Decimal("1"),
            accepted=True,
            submitted_to_broker=True,
            canceled=True,
            terminal=True,
            callback_timeline=[
                PaperOrderCallbackEvent(
                    event_type="orderStatus",
                    order_id=order_id,
                    perm_id=10010,
                    status="Cancelled",
                    filled_quantity=Decimal("0"),
                    remaining_quantity=Decimal("1"),
                )
            ],
            warnings=[],
            errors=[],
        )


def test_alpha_paper_run_submits_one_paper_order_after_verified_reports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report())
    smoke_path = write_report(tmp_path / "smoke.json", smoke_report())
    fake = FakePaperOrderBroker()

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **promotion_paths(tmp_path),
        ),
        broker_factory=lambda _config: fake,
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.COMPLETED
    assert report.ok is True
    assert report.campaign_id == CAMPAIGN_ID
    assert set(report.source_report_campaign_ids.values()) == {CAMPAIGN_ID}
    assert report.paper_order_report is not None
    assert report.paper_order_report.campaign_id == CAMPAIGN_ID
    assert report.alpha_shadow_report_verified is True
    assert report.paper_smoke_report_verified is True
    assert report.research_experiment_report_verified is True
    assert report.strict_shadow_summary_report_verified is True
    assert report.research_review_ready is True
    assert report.strict_shadow_engineering_pilot_ready is True
    assert report.submitted_orders is True
    assert report.order_id == 10
    assert report.order_status == "Cancelled"
    assert report.fill_quantity == Decimal("0")
    assert fake.place_calls == 1
    assert fake.cancel_calls == 1


def test_alpha_paper_run_no_trade_when_shadow_signal_is_hold(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(
        tmp_path / "shadow.json",
        shadow_report(direction=SignalDirection.HOLD),
    )
    smoke_path = write_report(tmp_path / "smoke.json", smoke_report())
    fake = FakePaperOrderBroker()

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **promotion_paths(tmp_path),
        ),
        broker_factory=lambda _config: fake,
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.NO_TRADE
    assert report.ok is True
    assert report.submitted_orders is False
    assert report.no_trade_reason == "shadow_signal_not_buy"
    assert fake.place_calls == 0


def test_alpha_paper_run_requires_confirmation_before_reports(tmp_path: Path) -> None:
    report = run_alpha_paper_run(
        config(),
        request(confirm="", alpha_shadow_report_path=(tmp_path / "missing.json").as_posix()),
        broker_factory=lambda _config: FakePaperOrderBroker(),
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.FAILED
    assert any("ALPHA_PAPER_SPY_1" in error for error in report.errors)
    assert report.order_api_invoked is False


def test_alpha_paper_run_rejects_different_commit_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report(commit_sha="other"))
    smoke_path = write_report(tmp_path / "smoke.json", smoke_report())

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **promotion_paths(tmp_path),
        ),
        broker_factory=lambda _config: FakePaperOrderBroker(),
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.FAILED
    assert any("different commit" in error for error in report.errors)
    assert report.order_api_invoked is False


def test_alpha_paper_run_rejects_mismatched_campaign(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report())
    smoke_path = write_report(
        tmp_path / "smoke.json",
        smoke_report(campaign_id="campaign-002"),
    )

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **promotion_paths(tmp_path),
        ),
        broker_factory=lambda _config: FakePaperOrderBroker(),
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.FAILED
    assert "campaign_id" in " ".join(report.errors)
    assert report.order_api_invoked is False


def test_alpha_paper_run_requires_transmitted_smoke_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report())
    smoke_path = write_report(
        tmp_path / "smoke.json",
        smoke_report(transmitted=False, submitted_orders=False),
    )

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **promotion_paths(tmp_path),
        ),
        broker_factory=lambda _config: FakePaperOrderBroker(),
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.FAILED
    assert any("must be transmitted" in error for error in report.errors)
    assert report.order_api_invoked is False


def test_alpha_paper_run_rejects_unapproved_research_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report())
    smoke_path = write_report(tmp_path / "smoke.json", smoke_report())
    paths = promotion_paths(tmp_path)
    research_path = Path(paths["research_experiment_report_path"])
    payload = json.loads(research_path.read_text(encoding="utf-8"))
    payload["research_review_ready"] = False
    research_path.write_text(json.dumps(payload), encoding="utf-8")
    fake = FakePaperOrderBroker()

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **paths,
        ),
        broker_factory=lambda _config: fake,
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.FAILED
    assert "research_review_ready" in " ".join(report.errors)
    assert report.order_api_invoked is False
    assert fake.place_calls == 0


def test_alpha_paper_run_rejects_non_pilot_strict_shadow_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report())
    smoke_path = write_report(tmp_path / "smoke.json", smoke_report())
    paths = promotion_paths(tmp_path)
    summary_path = Path(paths["strict_shadow_summary_report_path"])
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["engineering_pilot_ready"] = False
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    fake = FakePaperOrderBroker()

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **paths,
        ),
        broker_factory=lambda _config: fake,
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.FAILED
    assert "engineering_pilot_ready" in " ".join(report.errors)
    assert report.order_api_invoked is False
    assert fake.place_calls == 0


def test_alpha_paper_run_reports_order_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report())
    smoke_path = write_report(tmp_path / "smoke.json", smoke_report())

    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **promotion_paths(tmp_path),
        ),
        broker_factory=lambda _config: FakePaperOrderBroker(fail_order=True),
        now=now(),
    )

    assert report.final_status == AlphaPaperRunStatus.FAILED
    assert report.alpha_shadow_report_verified is True
    assert report.paper_smoke_report_verified is True
    assert report.order_api_invoked is True
    assert any("broker rejected order" in error for error in report.errors)


def test_alpha_paper_markdown_renders_source_and_order_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("trader.alpha_paper._current_commit_sha", lambda: "abc123")
    shadow_path = write_report(tmp_path / "shadow.json", shadow_report())
    smoke_path = write_report(tmp_path / "smoke.json", smoke_report())
    report = run_alpha_paper_run(
        config(),
        request(
            alpha_shadow_report_path=shadow_path.as_posix(),
            paper_smoke_report_path=smoke_path.as_posix(),
            **promotion_paths(tmp_path),
        ),
        broker_factory=lambda _config: FakePaperOrderBroker(),
        now=now(),
    )

    markdown = markdown_summary(report.model_dump(mode="json"))

    assert "# IBKR Alpha Paper Run" in markdown
    assert CAMPAIGN_ID in markdown
    assert "alpha_shadow_report" in markdown
    assert "Paper Order Evidence" in markdown
    assert "DUQ2****23" in markdown
