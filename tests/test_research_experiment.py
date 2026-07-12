from __future__ import annotations

import json
import sqlite3
import subprocess
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from trader.backtest import research_experiment as experiment_module
from trader.cli import app
from trader.data.research_store import initialize_research_store
from trader.models import (
    ResearchCatalogLoadReport,
    ResearchCatalogLoadRequest,
    ResearchExperimentCandidateResult,
    ResearchExperimentPhase,
    ResearchExperimentRequest,
    ResearchWindowCandidate,
)
from trader.reporting.reports import markdown_summary


def test_untracked_spec_fails_before_catalog_data_access(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path / "spec.json")

    report = experiment_module.run_research_experiment(
        ResearchExperimentRequest(
            spec_path=spec.as_posix(),
            root_path=(tmp_path / "store").as_posix(),
        )
    )

    assert report.ok is False
    assert report.spec_git_tracked is False
    assert "must be committed to Git and match HEAD" in report.errors[0]
    assert report.holdout_access_consumed is False


def test_git_evidence_requires_committed_unchanged_spec(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "quant-system@example.invalid")
    _git(repo, "config", "user.name", "Quant System Test")
    spec = _write_spec(repo / "research/spec.json")
    _git(repo, "add", "research/spec.json")
    _git(repo, "commit", "-m", "preregister experiment")

    commit_sha, committed = experiment_module._git_evidence(spec)

    assert commit_sha is not None
    assert committed is True
    spec.write_text(spec.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert experiment_module._git_evidence(spec)[1] is False
    _git(repo, "add", "research/spec.json")
    assert experiment_module._git_evidence(spec)[1] is False


def test_development_phase_never_records_holdout_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = _write_spec(tmp_path / "spec.json")
    root = tmp_path / "store"
    bundle = _bundle(root, ok=True)
    development = _development()
    monkeypatch.setattr(experiment_module, "_load_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        experiment_module,
        "_run_development",
        lambda *args, **kwargs: development,
    )

    report = experiment_module.run_research_experiment(
        ResearchExperimentRequest(
            spec_path=spec.as_posix(),
            root_path=root.as_posix(),
            phase=ResearchExperimentPhase.DEVELOPMENT,
        ),
        require_spec_tracked=False,
    )

    assert report.ok is True
    assert report.holdout_access_recorded is False
    assert report.holdout_access_consumed is False
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM holdout_access").fetchone()[0] == 0


def test_final_holdout_requires_exact_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = _write_spec(tmp_path / "spec.json")
    root = tmp_path / "store"
    bundle = _bundle(root, ok=True)
    monkeypatch.setattr(experiment_module, "_load_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        experiment_module,
        "_run_development",
        lambda *args, **kwargs: _development(),
    )

    report = experiment_module.run_research_experiment(
        ResearchExperimentRequest(
            spec_path=spec.as_posix(),
            root_path=root.as_posix(),
            phase=ResearchExperimentPhase.FINAL_HOLDOUT,
            confirmation="WRONG",
        ),
        require_spec_tracked=False,
    )

    assert report.ok is False
    assert "exact preregistered confirmation" in report.errors[0]
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM holdout_access").fetchone()[0] == 0


def test_final_holdout_access_is_append_only_and_consumed_on_failed_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = _write_spec(tmp_path / "spec.json")
    root = tmp_path / "store"
    ready = _bundle(root, ok=True)
    failed = _bundle(root, ok=False)
    calls = iter((ready, failed))
    monkeypatch.setattr(
        experiment_module,
        "_load_bundle",
        lambda *args, **kwargs: next(calls),
    )
    monkeypatch.setattr(
        experiment_module,
        "_run_development",
        lambda *args, **kwargs: _development(),
    )
    request = ResearchExperimentRequest(
        spec_path=spec.as_posix(),
        root_path=root.as_posix(),
        phase=ResearchExperimentPhase.FINAL_HOLDOUT,
        confirmation="ACCESS_FINAL_HOLDOUT_ONCE",
    )

    first = experiment_module.run_research_experiment(
        request,
        require_spec_tracked=False,
    )

    assert first.ok is False
    assert first.holdout_access_recorded is True
    assert first.holdout_access_consumed is True
    monkeypatch.setattr(experiment_module, "_load_bundle", lambda *args, **kwargs: ready)
    second = experiment_module.run_research_experiment(
        request,
        require_spec_tracked=False,
    )
    assert second.ok is False
    assert "already consumed" in second.errors[0]
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM holdout_access").fetchone()[0] == 1


def test_deflated_sharpe_reports_only_with_supported_sample() -> None:
    candidate = ResearchWindowCandidate(short_window=5, long_window=20)
    trials = [
        _candidate(candidate, [Decimal("0.10"), Decimal("-0.09")] * 30),
        _candidate(candidate, [Decimal("0.20"), Decimal("-0.05")] * 30),
        _candidate(candidate, [Decimal("0.05"), Decimal("-0.02")] * 30),
    ]
    holdout = _candidate(
        candidate,
        [Decimal("0.15"), Decimal("-0.03")] * 30,
    )

    diagnostics = experiment_module._deflated_sharpe_diagnostics(trials, holdout)

    assert diagnostics.deflated_sharpe_available is True
    assert diagnostics.deflated_sharpe_probability is not None
    assert diagnostics.pbo_available is False
    assert any("CSCV" in reason for reason in diagnostics.unavailable_reasons)


def test_experiment_report_renders_and_cli_is_registered(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path / "spec.json")
    report = experiment_module.run_research_experiment(
        ResearchExperimentRequest(
            spec_path=spec.as_posix(),
            root_path=(tmp_path / "store").as_posix(),
        )
    )

    rendered = markdown_summary(report.model_dump(mode="json"))
    assert "Preregistered Research Experiment" in rendered
    assert "Holdout consumed" in rendered
    result = CliRunner().invoke(app, ["research-experiment-run", "--help"])
    assert result.exit_code == 0


def test_experiment_module_is_broker_network_and_order_api_free() -> None:
    source = Path("src/trader/backtest/research_experiment.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "ibapi",
        "requests",
        "httpx",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
    ):
        assert forbidden not in source


def _write_spec(path: Path) -> Path:
    payload = json.loads(
        Path("research/experiments/spy_sma_2016_2025_v1.json").read_text(
            encoding="utf-8"
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.resolve()


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _bundle(root: Path, *, ok: bool):
    catalog = initialize_research_store(root)
    request = ResearchCatalogLoadRequest(root_path=root.as_posix())
    report = ResearchCatalogLoadReport(
        ok=ok,
        request=request,
        catalog_path=catalog.as_posix(),
        dataset_fingerprint="sha256:fixture" if ok else None,
        action_fingerprint="sha256:actions" if ok else None,
        errors=[] if ok else ["fixture holdout catalog unavailable"],
        final_status="loaded" if ok else "failed",
    )
    return experiment_module._CatalogBundle(
        signal=report,
        execution=report,
        benchmark=report,
    )


def _development():
    candidate = ResearchWindowCandidate(short_window=5, long_window=20)
    result = _candidate(candidate, [Decimal("0.1"), Decimal("-0.05")] * 30)
    return experiment_module._DevelopmentResult(
        folds=[],
        candidates=[result],
        selected=candidate,
        positive_years=5,
        aggregate_base_return=Decimal("10"),
        aggregate_two_x_return=Decimal("5"),
        errors=[],
    )


def _candidate(
    candidate: ResearchWindowCandidate,
    daily_returns: list[Decimal],
) -> ResearchExperimentCandidateResult:
    return ResearchExperimentCandidateResult(
        candidate=candidate,
        period_start="2016-01-01",
        period_end="2023-12-31",
        eligible=True,
        selection_score=Decimal("1"),
        base_return_pct=Decimal("1"),
        two_x_cost_return_pct=Decimal("0.5"),
        max_drawdown_pct=Decimal("1"),
        benchmark_return_pct=Decimal("1"),
        closed_trade_count=1,
        daily_returns_pct=daily_returns,
    )
