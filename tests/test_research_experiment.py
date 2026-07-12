from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from trader.backtest import research_experiment as experiment_module
from trader.cli import app
from trader.data.research_store import initialize_research_store
from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    ResearchCatalogLoadReport,
    ResearchCatalogLoadRequest,
    ResearchExperimentCandidateResult,
    ResearchExperimentPhase,
    ResearchExperimentRegistrationRequest,
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


def test_registration_supersedes_unconsumed_v1_and_seals_holdout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        experiment_module.importlib.metadata,
        "version",
        lambda _name: "10.48.1",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "quant-system@example.invalid")
    _git(repo, "config", "user.name", "Quant System Test")
    v1 = _write_spec(repo / "research/v1.json")
    v2 = _write_v2_spec(repo / "research/v2.json")
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n")
    (repo / "requirements.lock").write_text(
        "pytest==8.4.2 --hash=sha256:fixture\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "preregister experiments")
    root = tmp_path / "store"

    report = experiment_module.register_research_experiment(
        ResearchExperimentRegistrationRequest(
            spec_path=v2.as_posix(),
            supersedes_spec_path=v1.as_posix(),
            root_path=root.as_posix(),
        )
    )

    assert report.ok is True
    assert report.worktree_clean is True
    assert report.sealed_period is not None
    assert report.sealed_period.start_date == "2024-01-01"
    assert report.environment_manifest is not None
    assert report.environment_manifest.ibapi_version == "10.48.1"
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        statuses = dict(
            connection.execute(
                "SELECT experiment_id, status FROM experiment_specs"
            ).fetchall()
        )
        seals = connection.execute(
            "SELECT experiment_id, start_date, end_date FROM sealed_periods"
        ).fetchall()
    assert statuses == {
        "spy-sma-2016-2025-v1": "superseded",
        "spy-sma-2016-2025-v2": "active",
    }
    assert seals == [("spy-sma-2016-2025-v2", "2024-01-01", "2025-12-31")]

    replay = experiment_module.register_research_experiment(
        ResearchExperimentRegistrationRequest(
            spec_path=v2.as_posix(),
            supersedes_spec_path=v1.as_posix(),
            root_path=root.as_posix(),
        )
    )
    assert replay.ok is True
    assert replay.idempotent_replay is True


def test_development_phase_never_records_holdout_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = _write_spec(tmp_path / "spec.json")
    root = tmp_path / "store"
    _register(spec, root)
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
    _register(spec, root)
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
    _register(spec, root)
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


def test_full_chronological_development_and_holdout_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = _write_spec(tmp_path / "spec.json")
    root = tmp_path / "store"
    _register(spec, root)
    bundle = _historical_bundle(root)
    monkeypatch.setattr(experiment_module, "_load_bundle", lambda *args, **kwargs: bundle)

    development = experiment_module.run_research_experiment(
        ResearchExperimentRequest(
            spec_path=spec.as_posix(),
            root_path=root.as_posix(),
            phase=ResearchExperimentPhase.DEVELOPMENT,
        ),
        require_spec_tracked=False,
    )

    assert development.ok is True
    assert len(development.validation_folds) == 5
    assert development.selected_candidate is not None

    final = experiment_module.run_research_experiment(
        ResearchExperimentRequest(
            spec_path=spec.as_posix(),
            root_path=root.as_posix(),
            phase=ResearchExperimentPhase.FINAL_HOLDOUT,
            confirmation="ACCESS_FINAL_HOLDOUT_ONCE",
        ),
        require_spec_tracked=False,
    )

    assert final.ok is True
    assert final.holdout_access_recorded is True
    assert final.holdout_access_consumed is True
    assert final.holdout_result is not None
    assert final.holdout_result.closed_trade_count > 0


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
    register_help = CliRunner().invoke(app, ["research-experiment-register", "--help"])
    assert register_help.exit_code == 0


def test_experiment_module_is_broker_network_and_order_api_free() -> None:
    source = Path("src/trader/backtest/research_experiment.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "import ibapi",
        "from ibapi",
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


def _write_v2_spec(path: Path) -> Path:
    payload = json.loads(
        Path("research/experiments/spy_sma_2016_2025_v2.json").read_text(
            encoding="utf-8"
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.resolve()


def _register(spec: Path, root: Path) -> None:
    report = experiment_module.register_research_experiment(
        ResearchExperimentRegistrationRequest(
            spec_path=spec.as_posix(),
            root_path=root.as_posix(),
        ),
        require_release_evidence=False,
    )
    assert report.final_status == "registered"


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


def _historical_bundle(root: Path):
    frames: list[BacktestFeedFrame] = []
    for year in range(2016, 2026):
        start = datetime(year, 1, 2, 14, 30, tzinfo=UTC)
        for index in range(120):
            cycle = index % 40
            close = (
                Decimal("100") + Decimal(cycle)
                if cycle < 20
                else Decimal("140") - Decimal(cycle)
            )
            bar = BacktestBar(
                symbol="SPY",
                timestamp=start + timedelta(days=index),
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("1000000"),
            )
            frames.append(
                BacktestFeedFrame(
                    timestamp=bar.timestamp,
                    bars_by_symbol={"SPY": bar},
                )
            )
    feed = BacktestDataFeed(
        symbols=["SPY"],
        alignment_mode=BacktestAlignmentMode.INTERSECTION,
        frames=frames,
        total_bars=len(frames),
        frame_count=len(frames),
        first_timestamp=frames[0].timestamp,
        last_timestamp=frames[-1].timestamp,
        missing_bars_by_symbol={"SPY": 0},
        duplicate_timestamps_by_symbol={"SPY": 0},
        feed_status=BacktestFeedStatus.READY,
    )
    catalog = initialize_research_store(root)
    request = ResearchCatalogLoadRequest(root_path=root.as_posix())
    report = ResearchCatalogLoadReport(
        ok=True,
        request=request,
        catalog_path=catalog.as_posix(),
        dataset_fingerprint="sha256:historical",
        action_fingerprint="sha256:actions",
        feed=feed,
        final_status="loaded",
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
