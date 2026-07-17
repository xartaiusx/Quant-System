from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI and Task Scheduler only")


def _pwsh(
    *arguments: str,
    input_text: str | None = None,
    non_interactive: bool = True,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["pwsh", "-NoLogo", "-NoProfile"]
    if non_interactive:
        command.append("-NonInteractive")
    command.extend(arguments)
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={**os.environ, **(environment or {})},
    )


def _invoke_extracted_functions(
    script_path: Path,
    function_names: list[str],
    body: str,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = (
        "$tokens=$null;$parseErrors=$null;"
        "$ast=[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:FUNCTION_SCRIPT,[ref]$tokens,[ref]$parseErrors);"
        "if(@($parseErrors).Count -ne 0){throw 'Function source did not parse'};"
        "foreach($name in ($env:FUNCTION_NAMES -split ',')){"
        "$matches=@($ast.FindAll({param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true)|"
        "Where-Object{$_.Name -eq $name});"
        "if($matches.Count -ne 1){throw \"Expected one function named $name\"};"
        "Invoke-Expression $matches[0].Extent.Text};"
        + body
    )
    return _pwsh(
        "-Command",
        command,
        environment={
            "FUNCTION_SCRIPT": str(script_path.resolve()),
            "FUNCTION_NAMES": ",".join(function_names),
            **(environment or {}),
        },
    )


def test_task_plan_has_local_dst_boundary_and_exact_failover_settings(tmp_path: Path) -> None:
    script_path = Path("scripts/manage-alpaca-spy-eod-task.ps1").resolve()
    result = _pwsh(
        "-Command",
        (
            "function Get-TimeZone { [pscustomobject]@{ Id = 'Pacific Standard Time' } }; "
            ". $env:TASK_SCRIPT -Mode Plan -OutputRoot $env:OUTPUT_ROOT "
            "-CaptureStartDate 2026-07-16 -PythonPath $env:PYTHON_PATH"
        ),
        environment={
            "TASK_SCRIPT": str(script_path),
            "OUTPUT_ROOT": str(tmp_path / "market-data"),
            "PYTHON_PATH": sys.executable,
        },
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schedule"].startswith("13:30 Pacific Monday-Friday")
    assert payload["start_boundary_has_offset"] is False
    assert payload["start_when_available"] is True
    assert payload["network_required"] is True
    assert payload["restart_count"] == 3
    assert payload["restart_interval"] == "PT15M"
    assert payload["multiple_instances"] == "IgnoreNew"
    assert payload["execution_time_limit"] == "PT2H"
    assert payload["wake_to_run"] is False
    assert payload["logon_type"] == "Interactive"
    assert payload["run_level"] == "Limited"
    assert "APCA_API_KEY_ID" not in payload["arguments"]
    assert "APCA_API_SECRET_KEY" not in payload["arguments"]
    assert payload["credentials_read"] is False
    assert payload["network_accessed"] is False
    assert payload["scheduler_changed"] is False
    assert not (tmp_path / "market-data").exists()


def test_task_install_refuses_duplicate_before_credentials_or_rights(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "market-data"
    credential_path = tmp_path / "must-not-be-read.clixml"
    rights_path = tmp_path / "must-not-be-read.json"
    script_path = Path("scripts/manage-alpaca-spy-eod-task.ps1").resolve()
    result = _pwsh(
        "-Command",
        (
            "Import-Module ScheduledTasks; "
            "function Get-TimeZone { [pscustomobject]@{ Id = 'Pacific Standard Time' } }; "
            "function Get-ScheduledTask { param($TaskName, $ErrorAction) "
            "[pscustomobject]@{ TaskName = $TaskName } }; "
            ". $env:TASK_SCRIPT -Mode Install -OutputRoot $env:OUTPUT_ROOT "
            "-CaptureStartDate 2026-07-16 -CredentialPath $env:CREDENTIAL_PATH "
            "-RightsDecisionReport $env:RIGHTS_PATH -PythonPath $env:PYTHON_PATH"
        ),
        environment={
            "TASK_SCRIPT": str(script_path),
            "OUTPUT_ROOT": str(output_root),
            "CREDENTIAL_PATH": str(credential_path),
            "RIGHTS_PATH": str(rights_path),
            "PYTHON_PATH": sys.executable,
        },
    )

    assert result.returncode != 0
    assert "already exists; installation refuses to overwrite it" in result.stderr
    assert not output_root.exists()
    assert not credential_path.exists()
    assert not rights_path.exists()


def test_eod_runner_plan_only_reads_no_credentials_and_writes_nothing(tmp_path: Path) -> None:
    output_root = tmp_path / "market-data"
    missing_credentials = tmp_path / "must-not-be-read.clixml"
    result = _pwsh(
        "-File",
        "scripts/run-alpaca-spy-eod.ps1",
        "-OutputRoot",
        str(output_root),
        "-CaptureStartDate",
        "2026-07-16",
        "-CredentialPath",
        str(missing_credentials),
        "-RightsDecisionReport",
        str(tmp_path / "must-not-be-read.json"),
        "-PythonPath",
        sys.executable,
        "-PlanOnly",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "plan_only"
    assert payload["rights_read"] is False
    assert payload["credentials_read"] is False
    assert payload["network_accessed"] is False
    assert payload["files_written"] is False
    assert payload["broker_contacted"] is False
    assert payload["order_api_invoked"] is False
    assert not output_root.exists()


def test_eod_runner_rejects_mixed_case_path_inside_worktree() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    mixed_case_output = str(repo_root).lower() + "\\case-probe"
    result = _pwsh(
        "-File",
        "scripts/run-alpaca-spy-eod.ps1",
        "-OutputRoot",
        mixed_case_output,
        "-CaptureStartDate",
        "2026-07-16",
        "-PlanOnly",
    )

    assert result.returncode != 0
    assert "outside the Git worktree" in result.stderr
    assert not (repo_root / "case-probe").exists()


def test_eod_runner_rejects_junction_into_worktree(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    junction = tmp_path / "repo-link"
    created = _pwsh(
        "-Command",
        "New-Item -ItemType Junction -Path $env:LINK_PATH -Target $env:LINK_TARGET | Out-Null",
        environment={"LINK_PATH": str(junction), "LINK_TARGET": str(repo_root)},
    )
    if created.returncode != 0:
        pytest.skip(f"Directory junction unavailable: {created.stderr}")
    try:
        result = _pwsh(
            "-File",
            "scripts/run-alpaca-spy-eod.ps1",
            "-OutputRoot",
            str(junction / "junction-probe"),
            "-CaptureStartDate",
            "2026-07-16",
            "-PlanOnly",
        )
        assert result.returncode != 0
        assert "outside the Git worktree" in result.stderr
        assert not (repo_root / "junction-probe").exists()
    finally:
        removed = _pwsh(
            "-Command",
            "Remove-Item -LiteralPath $env:LINK_PATH -Force",
            environment={"LINK_PATH": str(junction)},
        )
        assert removed.returncode == 0, removed.stderr


def test_dpapi_setup_stores_two_securestrings_without_plaintext(tmp_path: Path) -> None:
    credential_path = tmp_path / "Quant Creds" / "Alpaca" / "credentials.clixml"
    result = _pwsh(
        "-File",
        "scripts/set-alpaca-spy-credentials.ps1",
        "-CredentialPath",
        str(credential_path),
        "-TestMode",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["test_mode"] is True
    content = credential_path.read_text(encoding="utf-8")
    assert "quant-system-dpapi-test-key" not in content
    assert "quant-system-dpapi-test-secret" not in content
    inspect = _pwsh(
        "-Command",
        (
            "$o=Import-Clixml -LiteralPath $env:DPAPI_TEST_PATH;"
            "$a=Get-Acl -LiteralPath $env:DPAPI_TEST_PATH;"
            "$d=Get-Acl -LiteralPath (Split-Path -Parent $env:DPAPI_TEST_PATH);"
            "$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
            "$ar=@($a.GetAccessRules($true,$false,[System.Security.Principal.SecurityIdentifier]));"
            "$dr=@($d.GetAccessRules($true,$false,[System.Security.Principal.SecurityIdentifier]));"
            "[pscustomobject]@{KeyType=$o.ApiKeyId.GetType().FullName;"
            "SecretType=$o.ApiSecretKey.GetType().FullName;"
            "Sid=$sid;FileOwner=$a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value;"
            "DirectoryOwner=$d.GetOwner([System.Security.Principal.SecurityIdentifier]).Value;"
            "FileRules=@($ar|ForEach-Object{[pscustomobject]@{Sid=$_.IdentityReference.Value;"
            "Rights=[string]$_.FileSystemRights;Type=[string]$_.AccessControlType;Inherited=$_.IsInherited}});"
            "DirectoryRules=@($dr|ForEach-Object{[pscustomobject]@{Sid=$_.IdentityReference.Value;"
            "Rights=[string]$_.FileSystemRights;Type=[string]$_.AccessControlType;Inherited=$_.IsInherited}})}|"
            "ConvertTo-Json -Compress"
        ),
        environment={"DPAPI_TEST_PATH": str(credential_path)},
    )
    assert inspect.returncode == 0, inspect.stderr
    payload = json.loads(inspect.stdout)
    assert payload["KeyType"] == "System.Security.SecureString"
    assert payload["SecretType"] == "System.Security.SecureString"
    assert payload["FileOwner"] == payload["Sid"]
    assert payload["DirectoryOwner"] == payload["Sid"]
    assert len(payload["FileRules"]) == 1
    assert len(payload["DirectoryRules"]) == 1
    for rule in payload["FileRules"] + payload["DirectoryRules"]:
        assert rule == {
            "Sid": payload["Sid"],
            "Rights": "FullControl",
            "Type": "Allow",
            "Inherited": False,
        }


def test_runner_capture_and_terminal_plan_evidence_fail_closed() -> None:
    result = _invoke_extracted_functions(
        Path("scripts/run-alpaca-spy-eod.ps1"),
        ["Assert-SessionCaptureResult", "Get-FinalPlanErrors"],
        (
            "$expected=[pscustomobject]@{session_date='2026-07-16';expected_bar_count=390};"
            "$capture=[pscustomobject]@{ok=$true;source='alpaca_sip';symbol='SPY';feed='sip';"
            "timeframe='1Min';partition_count=1;total_bars=390;"
            "manifest_paths=@('manifest.json');research_eligible=$false};"
            "Assert-SessionCaptureResult -Capture $capture -ExpectedPlan $expected "
            "-SessionDate '2026-07-16';"
            "$capture.total_bars=389;$captureError=$null;"
            "try{Assert-SessionCaptureResult -Capture $capture -ExpectedPlan $expected "
            "-SessionDate '2026-07-16'}catch{$captureError=$_.Exception.Message};"
            "$pending=[pscustomobject]@{missing_sessions=@();"
            "correction_sessions_due=@('2026-07-15');capture_sessions=@('2026-07-15');"
            "compare_pairs=@([pscustomobject]@{session_date='2026-07-14'})};"
            "[pscustomobject]@{CaptureError=$captureError;"
            "PlanErrors=@(Get-FinalPlanErrors -Plan $pending)}|ConvertTo-Json -Compress"
        ),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "invalid or incomplete success evidence" in payload["CaptureError"]
    assert payload["PlanErrors"] == [
        "Required correction recapture remains due: 2026-07-15",
        "Required capture remains pending: 2026-07-15",
        "Required correction comparison remains incomplete: 2026-07-14",
    ]


@pytest.mark.parametrize(
    "script_name",
    ["run-alpaca-spy-eod.ps1", "manage-alpaca-spy-eod-task.ps1"],
)
def test_credential_reparse_is_rejected_before_deserialization(
    tmp_path: Path,
    script_name: str,
) -> None:
    real_directory = tmp_path / "real-creds"
    real_directory.mkdir()
    (real_directory / "credentials.clixml").write_text("not deserialized", encoding="utf-8")
    junction = tmp_path / "credential-link"
    created = _pwsh(
        "-Command",
        "New-Item -ItemType Junction -Path $env:LINK_PATH -Target $env:LINK_TARGET | Out-Null",
        environment={"LINK_PATH": str(junction), "LINK_TARGET": str(real_directory)},
    )
    if created.returncode != 0:
        pytest.skip(f"Directory junction unavailable: {created.stderr}")
    try:
        result = _invoke_extracted_functions(
            Path("scripts") / script_name,
            ["Resolve-NonReparseCredentialPath", "Assert-CurrentUserOnlyCredentialAcl"],
            (
                "$script:imported=$false;function Import-Clixml{$script:imported=$true};"
                "$message=$null;try{"
                "$resolved=Resolve-NonReparseCredentialPath -Value $env:CREDENTIAL_PATH;"
                "Assert-CurrentUserOnlyCredentialAcl -ResolvedPath $resolved;"
                "$null=Import-Clixml -LiteralPath $resolved}catch{$message=$_.Exception.Message};"
                "[pscustomobject]@{Imported=$script:imported;Message=$message}|"
                "ConvertTo-Json -Compress"
            ),
            environment={"CREDENTIAL_PATH": str(junction / "credentials.clixml")},
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["Imported"] is False
        assert "must not contain reparse points" in payload["Message"]
    finally:
        removed = _pwsh(
            "-Command",
            "Remove-Item -LiteralPath $env:LINK_PATH -Force",
            environment={"LINK_PATH": str(junction)},
        )
        assert removed.returncode == 0, removed.stderr


def test_task_install_rolls_back_owned_registration_on_post_register_failure(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "market-data"
    evidence_root.mkdir()
    market_data = evidence_root / "existing-data.txt"
    market_data.write_text("preserve", encoding="utf-8")
    credential_file = tmp_path / "credentials.clixml"
    credential_file.write_text("preserve", encoding="utf-8")
    result = _invoke_extracted_functions(
        Path("scripts/manage-alpaca-spy-eod-task.ps1"),
        ["Install-OwnedScheduledTask"],
        (
            "$script:registered=$false;$script:unregisterCount=0;"
            "function Register-ScheduledTask{param($TaskName,$InputObject)"
            "$script:registered=$true};"
            "function Export-ScheduledTask{param($TaskName)throw 'injected export failure'};"
            "function Get-OwnedTask{param($Name)"
            "if($script:registered){return [pscustomobject]@{Name=$Name}}};"
            "function Unregister-ScheduledTask{param($TaskName,[switch]$Confirm)"
            "$script:registered=$false;$script:unregisterCount++};"
            "$message=$null;try{Install-OwnedScheduledTask -Name 'TestTask' "
            "-TaskDefinition ([pscustomobject]@{}) -EvidenceOutputRoot $env:EVIDENCE_ROOT "
            "-PlanPayload ([ordered]@{mode='install';scheduler_changed=$false})}"
            "catch{$message=$_.Exception.Message};"
            "[pscustomobject]@{Registered=$script:registered;"
            "UnregisterCount=$script:unregisterCount;Message=$message}|ConvertTo-Json -Compress"
        ),
        environment={"EVIDENCE_ROOT": str(evidence_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "Registered": False,
        "UnregisterCount": 1,
        "Message": "injected export failure",
    }
    assert market_data.read_text(encoding="utf-8") == "preserve"
    assert credential_file.read_text(encoding="utf-8") == "preserve"


def test_credential_acl_checks_precede_import_in_both_scripts() -> None:
    runner = Path("scripts/run-alpaca-spy-eod.ps1").read_text(encoding="utf-8")
    manager = Path("scripts/manage-alpaca-spy-eod-task.ps1").read_text(encoding="utf-8")

    runner_resolve = runner.index(
        "$CredentialPath = Resolve-NonReparseCredentialPath -Value $CredentialPath"
    )
    runner_acl = runner.index(
        "Assert-CurrentUserOnlyCredentialAcl -ResolvedPath $CredentialPath",
        runner_resolve,
    )
    runner_import = runner.index(
        "$credentials = Import-Clixml -LiteralPath $CredentialPath",
        runner_acl,
    )
    assert runner_resolve < runner_acl < runner_import

    manager_resolve = manager.index("$resolved = Resolve-NonReparseCredentialPath -Value $Path")
    manager_acl = manager.index(
        "Assert-CurrentUserOnlyCredentialAcl -ResolvedPath $resolved",
        manager_resolve,
    )
    manager_import = manager.index(
        "$credentials = Import-Clixml -LiteralPath $resolved",
        manager_acl,
    )
    assert manager_resolve < manager_acl < manager_import
