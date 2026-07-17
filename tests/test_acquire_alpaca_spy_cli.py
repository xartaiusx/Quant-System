from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from trader.data.alpaca_rights_gate import AlpacaRightsGateError


def _load_cli() -> ModuleType:
    script_path = Path("scripts/acquire_alpaca_spy.py").resolve()
    spec = importlib.util.spec_from_file_location("acquire_alpaca_spy_cli", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ForbiddenEnvironment:
    def get(self, _name: str, _default: str = "") -> str:
        pytest.fail("plan or failed rights validation read Alpaca credentials")


@pytest.mark.parametrize(
    "mode_arguments",
    [
        ["--session-date", "2025-01-02"],
        ["--start", "2025-01-02", "--end", "2025-01-03"],
    ],
)
def test_plan_only_skips_rights_credentials_network_and_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode_arguments: list[str],
) -> None:
    cli = _load_cli()
    output_root = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        cli,
        "load_passing_alpaca_rights_decision",
        lambda _path: pytest.fail("plan-only read the rights report"),
    )
    monkeypatch.setattr(
        cli,
        "os",
        SimpleNamespace(environ=_ForbiddenEnvironment()),
    )
    monkeypatch.setattr(
        cli,
        "acquire_spy_session",
        lambda *_args, **_kwargs: pytest.fail("plan-only invoked acquisition"),
    )
    monkeypatch.setattr(
        cli,
        "acquire_historical_spy",
        lambda *_args, **_kwargs: pytest.fail("plan-only invoked acquisition"),
    )

    result = cli.main(
        [
            *mode_arguments,
            "--output-root",
            str(output_root),
            "--vendor-decision-report",
            str(tmp_path / "must-not-be-read.json"),
            "--expected-vendor-decision-sha256",
            "not-read-or-validated-in-plan-mode",
            "--plan-only",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["credentials_read"] is False
    assert payload["network_accessed"] is False
    assert not output_root.exists()


@pytest.mark.parametrize(
    "mode_arguments",
    [
        ["--session-date", "2025-01-02"],
        ["--start", "2025-01-02", "--end", "2025-01-03"],
    ],
)
def test_every_non_plan_mode_requires_rights_before_credentials_or_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode_arguments: list[str],
) -> None:
    cli = _load_cli()
    output_root = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        cli,
        "os",
        SimpleNamespace(environ=_ForbiddenEnvironment()),
    )
    monkeypatch.setattr(
        cli,
        "acquire_spy_session",
        lambda *_args, **_kwargs: pytest.fail("acquisition ran without rights"),
    )
    monkeypatch.setattr(
        cli,
        "acquire_historical_spy",
        lambda *_args, **_kwargs: pytest.fail("acquisition ran without rights"),
    )

    result = cli.main([*mode_arguments, "--output-root", str(output_root)])

    assert result == 1
    assert "--vendor-decision-report is required" in capsys.readouterr().err
    assert not output_root.exists()


@pytest.mark.parametrize(
    "mode_arguments",
    [
        ["--session-date", "2025-01-02"],
        ["--start", "2025-01-02", "--end", "2025-01-03"],
    ],
)
def test_every_non_plan_mode_requires_pinned_sha_before_reading_report_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode_arguments: list[str],
) -> None:
    cli = _load_cli()
    output_root = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        cli,
        "load_passing_alpaca_rights_decision",
        lambda _path: pytest.fail("missing pinned SHA read the rights report"),
    )
    monkeypatch.setattr(
        cli,
        "os",
        SimpleNamespace(environ=_ForbiddenEnvironment()),
    )

    result = cli.main(
        [
            *mode_arguments,
            "--output-root",
            str(output_root),
            "--vendor-decision-report",
            str(tmp_path / "must-not-be-read.json"),
        ]
    )

    assert result == 1
    assert "--expected-vendor-decision-sha256 is required" in capsys.readouterr().err
    assert not output_root.exists()


@pytest.mark.parametrize(
    "mode_arguments",
    [
        ["--session-date", "2025-01-02"],
        ["--start", "2025-01-02", "--end", "2025-01-03"],
    ],
)
def test_rights_report_is_validated_before_credentials_and_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode_arguments: list[str],
) -> None:
    cli = _load_cli()
    output_root = tmp_path / "must-not-exist"
    rights_report = tmp_path / "decision.json"
    rights_sha256 = "a" * 64
    events: list[str] = []

    def validate(path: Path) -> object:
        assert path == rights_report
        assert not output_root.exists()
        events.append("rights")
        return SimpleNamespace(
            report_path=rights_report.resolve(),
            report_sha256=rights_sha256,
        )

    class RecordingEnvironment:
        def get(self, name: str, _default: str = "") -> str:
            events.append(name)
            return "test-only"

    def acquire(*_args: object, **kwargs: object) -> object:
        assert kwargs["vendor_decision_report"] == rights_report.resolve()
        assert kwargs["vendor_decision_sha256"] == rights_sha256
        events.append("acquisition")
        return object()

    monkeypatch.setattr(cli, "load_passing_alpaca_rights_decision", validate)
    monkeypatch.setattr(
        cli,
        "os",
        SimpleNamespace(environ=RecordingEnvironment()),
    )
    monkeypatch.setattr(cli, "acquire_spy_session", acquire)
    monkeypatch.setattr(cli, "acquire_historical_spy", acquire)
    monkeypatch.setattr(cli, "acquisition_result_json", lambda _result: "{}")

    result = cli.main(
        [
            *mode_arguments,
            "--output-root",
            str(output_root),
            "--vendor-decision-report",
            str(rights_report),
            "--expected-vendor-decision-sha256",
            rights_sha256,
        ]
    )

    assert result == 0
    assert events == [
        "rights",
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "acquisition",
    ]
    assert not output_root.exists()


@pytest.mark.parametrize(
    "mode_arguments",
    [
        ["--session-date", "2025-01-02"],
        ["--start", "2025-01-02", "--end", "2025-01-03"],
    ],
)
def test_pinned_sha_mismatch_stops_before_credentials_and_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode_arguments: list[str],
) -> None:
    cli = _load_cli()
    output_root = tmp_path / "must-not-exist"
    rights_report = tmp_path / "decision.json"
    monkeypatch.setattr(
        cli,
        "load_passing_alpaca_rights_decision",
        lambda _path: SimpleNamespace(
            report_path=rights_report.resolve(),
            report_sha256="b" * 64,
        ),
    )
    monkeypatch.setattr(
        cli,
        "os",
        SimpleNamespace(environ=_ForbiddenEnvironment()),
    )
    monkeypatch.setattr(
        cli,
        "acquire_spy_session",
        lambda *_args, **_kwargs: pytest.fail("mismatched pin invoked acquisition"),
    )
    monkeypatch.setattr(
        cli,
        "acquire_historical_spy",
        lambda *_args, **_kwargs: pytest.fail("mismatched pin invoked acquisition"),
    )

    result = cli.main(
        [
            *mode_arguments,
            "--output-root",
            str(output_root),
            "--vendor-decision-report",
            str(rights_report),
            "--expected-vendor-decision-sha256",
            "a" * 64,
        ]
    )

    assert result == 1
    assert "does not match the pinned digest" in capsys.readouterr().err
    assert not output_root.exists()


@pytest.mark.parametrize(
    "mode_arguments",
    [
        ["--session-date", "2025-01-02"],
        ["--start", "2025-01-02", "--end", "2025-01-03"],
    ],
)
def test_failed_rights_validation_stops_before_credentials_network_and_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode_arguments: list[str],
) -> None:
    cli = _load_cli()
    output_root = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        cli,
        "load_passing_alpaca_rights_decision",
        lambda _path: (_ for _ in ()).throw(AlpacaRightsGateError("blocked")),
    )
    monkeypatch.setattr(
        cli,
        "os",
        SimpleNamespace(environ=_ForbiddenEnvironment()),
    )
    monkeypatch.setattr(
        cli,
        "acquire_spy_session",
        lambda *_args, **_kwargs: pytest.fail("failed gate invoked acquisition"),
    )
    monkeypatch.setattr(
        cli,
        "acquire_historical_spy",
        lambda *_args, **_kwargs: pytest.fail("failed gate invoked acquisition"),
    )

    result = cli.main(
        [
            *mode_arguments,
            "--output-root",
            str(output_root),
            "--vendor-decision-report",
            str(tmp_path / "decision.json"),
            "--expected-vendor-decision-sha256",
            "a" * 64,
        ]
    )

    assert result == 1
    assert "blocked" in capsys.readouterr().err
    assert not output_root.exists()


def test_eod_wrapper_passes_validated_rights_report_to_acquisition() -> None:
    runner = Path("scripts/run-alpaca-spy-eod.ps1").read_text(encoding="utf-8")

    validation = runner.index("$rightsEvidence = Get-AlpacaRightsEvidence")
    canonical_path = runner.index("$rightsPath = [string] $pinnedRights.report_path")
    pinned_sha = runner.index("$rightsSha256 = [string] $pinnedRights.report_sha256")
    child_path_argument = runner.index("'--vendor-decision-report', $rightsPath")
    child_sha_argument = runner.index(
        "'--expected-vendor-decision-sha256', $rightsSha256"
    )

    assert validation < canonical_path < pinned_sha < child_path_argument < child_sha_argument
