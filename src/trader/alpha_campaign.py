"""Sequential SPY-only alpha campaign orchestration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from trader.alpha_paper import ALPHA_PAPER_CONFIRMATION, run_alpha_paper_run
from trader.alpha_shadow import run_alpha_shadow_run
from trader.alpha_summary import run_alpha_test_summary
from trader.config import TraderConfig
from trader.models import (
    AlphaCampaignRunMode,
    AlphaCampaignRunReport,
    AlphaCampaignRunRequest,
    AlphaCampaignRunStatus,
    AlphaPaperRunReport,
    AlphaPaperRunRequest,
    AlphaShadowRunReport,
    AlphaShadowRunRequest,
    AlphaTestSummaryReport,
    AlphaTestSummaryRequest,
    PaperReadinessRunStage,
    PaperReadinessStageStatus,
    PaperReconcileReport,
    PaperReconcileRequest,
    new_campaign_id,
    utc_now,
)
from trader.paper_reconcile import run_paper_reconcile
from trader.reporting.journal import Journal

READ_ONLY_OFF_CONFIRMATION = "READ_ONLY_OFF_FOR_ALPHA_PAPER"
RECONCILE_CLIENT_ID = 11

AlphaShadowRunner = Callable[[TraderConfig, AlphaShadowRunRequest], AlphaShadowRunReport]
AlphaPaperRunner = Callable[[TraderConfig, AlphaPaperRunRequest], AlphaPaperRunReport]
PaperReconcileRunner = Callable[[TraderConfig, PaperReconcileRequest], PaperReconcileReport]
AlphaSummaryRunner = Callable[[AlphaTestSummaryRequest], AlphaTestSummaryReport]


def run_alpha_campaign_run(
    config: TraderConfig,
    request: AlphaCampaignRunRequest | None = None,
    *,
    journal: Journal | None = None,
    alpha_shadow_runner: AlphaShadowRunner = run_alpha_shadow_run,
    alpha_paper_runner: AlphaPaperRunner = run_alpha_paper_run,
    paper_reconcile_runner: PaperReconcileRunner = run_paper_reconcile,
    alpha_summary_runner: AlphaSummaryRunner = run_alpha_test_summary,
) -> AlphaCampaignRunReport:
    """Run one sequential paper-alpha campaign mode using existing safe stages."""

    selected_request = _request_with_campaign_id(request or AlphaCampaignRunRequest())
    selected_journal = journal or Journal()
    if _enum_value(selected_request.mode) == AlphaCampaignRunMode.PAPER.value:
        return _run_paper_campaign(
            config,
            selected_request,
            journal=selected_journal,
            alpha_paper_runner=alpha_paper_runner,
            paper_reconcile_runner=paper_reconcile_runner,
            alpha_summary_runner=alpha_summary_runner,
        )
    return _run_shadow_campaign(
        config,
        selected_request,
        journal=selected_journal,
        alpha_shadow_runner=alpha_shadow_runner,
    )


def _run_shadow_campaign(
    config: TraderConfig,
    request: AlphaCampaignRunRequest,
    *,
    journal: Journal,
    alpha_shadow_runner: AlphaShadowRunner,
) -> AlphaCampaignRunReport:
    warnings = [
        "alpha-campaign-run shadow mode is read-only and must run with IBKR Read-Only API enabled.",
        "ALLOW_PAPER_ORDERS=false is required by the alpha-shadow-run stage.",
    ]
    shadow_request = AlphaShadowRunRequest(
        campaign_id=request.campaign_id,
        broker_timeout_seconds=request.broker_timeout_seconds,
        history_timeout_seconds=request.history_timeout_seconds,
        broker_stage_pause_seconds=request.broker_stage_pause_seconds,
    )
    shadow_report = alpha_shadow_runner(config, shadow_request)
    shadow_paths = _write_report(journal, "alpha_shadow_run", shadow_report)
    stages = [
        _stage_from_report(
            "alpha_shadow_run",
            "alpha-shadow-run",
            shadow_report,
            report_paths=shadow_paths,
        )
    ]
    return _build_report(
        config,
        request,
        stages=stages,
        warnings=warnings,
        errors=[],
        alpha_shadow_report=shadow_report,
        report_paths=_flatten_stage_paths(stages),
    )


def _run_paper_campaign(
    config: TraderConfig,
    request: AlphaCampaignRunRequest,
    *,
    journal: Journal,
    alpha_paper_runner: AlphaPaperRunner,
    paper_reconcile_runner: PaperReconcileRunner,
    alpha_summary_runner: AlphaSummaryRunner,
) -> AlphaCampaignRunReport:
    warnings = [
        "alpha-campaign-run paper mode requires a deliberate Read-Only-off paper window.",
        "Re-enable IBKR Read-Only API immediately after the paper execution window.",
        "The command resets its post-run config view to ALLOW_PAPER_ORDERS=false "
        "before reconciliation.",
    ]
    gate_errors = _paper_window_gate_errors(config, request)
    stages: list[PaperReadinessRunStage] = []
    if gate_errors:
        stages.append(
            _stage(
                "paper_window_gate",
                "alpha-campaign-run --mode paper",
                ok=False,
                status=PaperReadinessStageStatus.FAILED,
                errors=gate_errors,
            )
        )
        return _build_report(
            config,
            request,
            stages=stages,
            warnings=warnings,
            errors=gate_errors,
            report_paths=_flatten_stage_paths(stages),
        )

    alpha_request = AlphaPaperRunRequest(
        campaign_id=request.campaign_id,
        allow_fill=request.allow_fill,
        cancel_after_seconds=request.cancel_after_seconds,
        confirm=ALPHA_PAPER_CONFIRMATION,
        timeout_seconds=request.broker_timeout_seconds,
        max_report_age_hours=request.max_report_age_hours,
        alpha_shadow_report_path=request.alpha_shadow_report_path,
        paper_smoke_report_path=request.paper_smoke_report_path,
        research_experiment_report_path=request.research_experiment_report_path,
        strict_shadow_summary_report_path=request.strict_shadow_summary_report_path,
    )
    alpha_report = alpha_paper_runner(config, alpha_request)
    alpha_paths = _write_report(journal, "alpha_paper_run", alpha_report)
    stages.append(
        _stage_from_report(
            "alpha_paper_run",
            "alpha-paper-run",
            alpha_report,
            report_paths=alpha_paths,
        )
    )

    reconcile_config = config.model_copy(
        update={"allow_paper_orders": False, "ibkr_client_id": RECONCILE_CLIENT_ID}
    )
    reconcile_request = PaperReconcileRequest(
        campaign_id=request.campaign_id,
        timeout_seconds=request.broker_timeout_seconds,
        paper_smoke_report_path=request.paper_smoke_report_path,
        alpha_paper_report_path=alpha_paths["json"],
    )
    reconcile_report = paper_reconcile_runner(reconcile_config, reconcile_request)
    reconcile_paths = _write_report(journal, "paper_reconcile", reconcile_report)
    stages.append(
        _stage_from_report(
            "paper_reconcile",
            "paper-reconcile",
            reconcile_report,
            report_paths=reconcile_paths,
        )
    )

    summary_request = AlphaTestSummaryRequest(
        campaign_id=request.campaign_id,
        alpha_shadow_report_path=request.alpha_shadow_report_path,
        paper_smoke_report_path=request.paper_smoke_report_path,
        alpha_paper_report_path=alpha_paths["json"],
        paper_reconcile_report_path=reconcile_paths["json"],
        max_report_age_hours=request.max_report_age_hours,
    )
    summary_report = alpha_summary_runner(summary_request)
    summary_paths = _write_report(journal, "alpha_test_summary", summary_report)
    stages.append(
        _stage_from_report(
            "alpha_test_summary",
            "alpha-test-summary",
            summary_report,
            report_paths=summary_paths,
        )
    )

    return _build_report(
        reconcile_config,
        request,
        stages=stages,
        warnings=warnings,
        errors=[],
        alpha_paper_report=alpha_report,
        paper_reconcile_report=reconcile_report,
        alpha_test_summary_report=summary_report,
        report_paths=_flatten_stage_paths(stages),
    )


def _paper_window_gate_errors(
    config: TraderConfig,
    request: AlphaCampaignRunRequest,
) -> list[str]:
    errors: list[str] = []
    if request.read_only_off_confirm != READ_ONLY_OFF_CONFIRMATION:
        errors.append(f"--read-only-off-confirm {READ_ONLY_OFF_CONFIRMATION} is required")
    if not config.allow_paper_orders:
        errors.append("ALLOW_PAPER_ORDERS=true is required for campaign paper mode")
    return errors


def _request_with_campaign_id(request: AlphaCampaignRunRequest) -> AlphaCampaignRunRequest:
    if request.campaign_id:
        return request
    return request.model_copy(update={"campaign_id": new_campaign_id()})


def _write_report(
    journal: Journal,
    name: str,
    report: (
        AlphaShadowRunReport
        | AlphaPaperRunReport
        | PaperReconcileReport
        | AlphaTestSummaryReport
    ),
) -> dict[str, str]:
    json_path, md_path = journal.write_cycle(name, report.model_dump(mode="json"))
    return {"json": json_path.as_posix(), "markdown": md_path.as_posix()}


def _stage_from_report(
    name: str,
    command: str,
    report: (
        AlphaShadowRunReport
        | AlphaPaperRunReport
        | PaperReconcileReport
        | AlphaTestSummaryReport
    ),
    *,
    report_paths: dict[str, str],
) -> PaperReadinessRunStage:
    errors = list(report.errors)
    warnings = list(report.warnings)
    status = _stage_status(ok=report.ok, warnings=warnings)
    if not report.ok and not errors:
        errors.append(f"{name} failed")
    return _stage(
        name,
        command,
        ok=report.ok,
        status=status,
        report_paths={f"{name}_{key}": value for key, value in report_paths.items()},
        warnings=warnings,
        errors=errors,
    )


def _stage(
    name: str,
    command: str,
    *,
    ok: bool,
    status: PaperReadinessStageStatus,
    report_paths: dict[str, str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> PaperReadinessRunStage:
    started_at = utc_now()
    return PaperReadinessRunStage(
        name=name,
        command=command,
        ok=ok,
        final_status=status,
        started_at=started_at,
        finished_at=utc_now(),
        report_paths=report_paths or {},
        warnings=warnings or [],
        errors=errors or [],
    )


def _stage_status(
    *,
    ok: bool,
    warnings: list[str],
) -> PaperReadinessStageStatus:
    if not ok:
        return PaperReadinessStageStatus.FAILED
    if warnings:
        return PaperReadinessStageStatus.COMPLETED_WITH_WARNINGS
    return PaperReadinessStageStatus.COMPLETED


def _build_report(
    config: TraderConfig,
    request: AlphaCampaignRunRequest,
    *,
    stages: list[PaperReadinessRunStage],
    warnings: list[str],
    errors: list[str],
    report_paths: dict[str, str],
    alpha_shadow_report: AlphaShadowRunReport | None = None,
    alpha_paper_report: AlphaPaperRunReport | None = None,
    paper_reconcile_report: PaperReconcileReport | None = None,
    alpha_test_summary_report: AlphaTestSummaryReport | None = None,
) -> AlphaCampaignRunReport:
    all_errors = _unique([*errors, *[error for stage in stages for error in stage.errors]])
    all_warnings = _unique(
        [*warnings, *[warning for stage in stages for warning in stage.warnings]]
    )
    final_status = _final_status(stages=stages, errors=all_errors, warnings=all_warnings)
    return AlphaCampaignRunReport(
        ok=final_status != AlphaCampaignRunStatus.FAILED,
        request=request,
        commit_sha=_current_commit_sha(),
        campaign_id=request.campaign_id,
        mode=request.mode,
        stages=stages,
        stage_statuses={stage.name: _enum_value(stage.final_status) for stage in stages},
        report_paths=report_paths,
        alpha_shadow_completed=bool(alpha_shadow_report and alpha_shadow_report.ok),
        alpha_paper_completed=bool(alpha_paper_report and alpha_paper_report.ok),
        paper_reconcile_completed=bool(
            paper_reconcile_report and paper_reconcile_report.ok
        ),
        alpha_test_summary_completed=bool(
            alpha_test_summary_report and alpha_test_summary_report.ok
        ),
        submitted_orders=bool(alpha_paper_report and alpha_paper_report.submitted_orders),
        paper_orders_enabled=False,
        live_orders_enabled=config.allow_live_orders,
        live_route_possible=bool(alpha_paper_report and alpha_paper_report.live_route_possible),
        order_routing_enabled=bool(alpha_paper_report and alpha_paper_report.order_api_invoked),
        order_api_invoked=bool(alpha_paper_report and alpha_paper_report.order_api_invoked),
        read_only_api_expected_initially=(
            _enum_value(request.mode) == AlphaCampaignRunMode.SHADOW.value
        ),
        read_only_restore_required=_enum_value(request.mode) == AlphaCampaignRunMode.PAPER.value,
        paper_execution_window_confirmed=(
            request.read_only_off_confirm == READ_ONLY_OFF_CONFIRMATION
        ),
        warnings=all_warnings,
        errors=all_errors,
        final_status=final_status,
    )


def _final_status(
    *,
    stages: list[PaperReadinessRunStage],
    errors: list[str],
    warnings: list[str],
) -> AlphaCampaignRunStatus:
    if errors or any(not stage.ok for stage in stages):
        return AlphaCampaignRunStatus.FAILED
    if warnings or any(
        stage.final_status == PaperReadinessStageStatus.COMPLETED_WITH_WARNINGS
        for stage in stages
    ):
        return AlphaCampaignRunStatus.COMPLETED_WITH_WARNINGS
    return AlphaCampaignRunStatus.COMPLETED


def _flatten_stage_paths(stages: list[PaperReadinessRunStage]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for stage in stages:
        paths.update(stage.report_paths)
    return paths


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


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))
