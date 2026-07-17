[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Plan', 'Install', 'Uninstall')][string] $Mode,
    [string] $OutputRoot,
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string] $CaptureStartDate,
    [string] $CredentialPath,
    [string] $RightsDecisionReport,
    [string] $PythonPath,
    [string] $TaskName = 'QuantSystem-AlpacaSpyEod'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw 'Windows Task Scheduler management is supported only on Windows.'
}
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
function Resolve-CanonicalBoundaryPath {
    param([Parameter(Mandatory)][string] $Value)

    $fullPath = [System.IO.Path]::GetFullPath($Value)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    if (-not $root) {
        throw "Path has no filesystem root: $Value"
    }
    $current = $root
    $separators = [char[]] @([char]'\', [char]'/')
    $segments = $fullPath.Substring($root.Length).Split(
        $separators,
        [System.StringSplitOptions]::RemoveEmptyEntries
    )
    foreach ($segment in $segments) {
        $candidate = Join-Path $current $segment
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -Force -LiteralPath $candidate
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                $target = $item.ResolveLinkTarget($true)
                if ($null -eq $target) {
                    throw "Unable to resolve reparse point: $candidate"
                }
                $current = $target.FullName
            }
            else {
                $current = $item.FullName
            }
        }
        else {
            $current = $candidate
        }
    }
    return [System.IO.Path]::GetFullPath($current)
}

function Resolve-NonReparseCredentialPath {
    param([Parameter(Mandatory)][string] $Value)

    $fullPath = [System.IO.Path]::GetFullPath($Value)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    if (-not $root) {
        throw "Credential path has no filesystem root: $Value"
    }
    $current = $root
    $item = $null
    $separators = [char[]] @([char]'\', [char]'/')
    $segments = $fullPath.Substring($root.Length).Split(
        $separators,
        [System.StringSplitOptions]::RemoveEmptyEntries
    )
    foreach ($segment in $segments) {
        $candidate = Join-Path $current $segment
        if (-not (Test-Path -LiteralPath $candidate)) {
            throw "DPAPI credential path not found: $candidate"
        }
        $item = Get-Item -Force -LiteralPath $candidate
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "The Alpaca DPAPI credential path must not contain reparse points: $candidate"
        }
        $current = $item.FullName
    }
    if ($null -eq $item -or $item.PSIsContainer) {
        throw "DPAPI credential file not found: $Value"
    }
    return [System.IO.Path]::GetFullPath($current)
}

function Assert-CurrentUserOnlyCredentialAcl {
    param([Parameter(Mandatory)][string] $ResolvedPath)

    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    foreach ($target in @($ResolvedPath, (Split-Path -Parent $ResolvedPath))) {
        $acl = Get-Acl -LiteralPath $target
        $owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier])
        $rules = @(
            $acl.GetAccessRules(
                $true,
                $false,
                [System.Security.Principal.SecurityIdentifier]
            )
        )
        if (
            $owner.Value -ne $currentSid.Value -or
            $rules.Count -ne 1 -or
            $rules[0].IdentityReference.Value -ne $currentSid.Value -or
            $rules[0].AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rules[0].IsInherited -or
            (($rules[0].FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne [System.Security.AccessControl.FileSystemRights]::FullControl)
        ) {
            throw 'The Alpaca DPAPI credential path is not restricted to the current user.'
        }
    }
}

$runnerPath = Join-Path $PSScriptRoot 'run-alpaca-spy-eod.ps1'
$rightsValidatorPath = Join-Path $PSScriptRoot 'validate_alpaca_rights.py'
if (-not $PythonPath) {
    $PythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not $CredentialPath) {
    $CredentialPath = Join-Path $repoRoot 'Quant Creds\Alpaca\credentials.clixml'
}
$CredentialPath = [System.IO.Path]::GetFullPath($CredentialPath)
$ownerMarker = 'Quant-System managed Alpaca SIP EOD capture'

function Assert-SafeTaskValue {
    param([Parameter(Mandatory)][string] $Value, [Parameter(Mandatory)][string] $Label)

    if ($Value.IndexOfAny(@([char]'"', [char]"`r", [char]"`n")) -ge 0) {
        throw "$Label contains a character that is unsafe for Task Scheduler arguments."
    }
}

function Quote-TaskValue {
    param([Parameter(Mandatory)][string] $Value)
    Assert-SafeTaskValue -Value $Value -Label 'Task argument'
    return '"' + $Value + '"'
}

function Invoke-RightsValidation {
    param([Parameter(Mandatory)][string] $Path)

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $PythonPath
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    [void] $startInfo.ArgumentList.Add($rightsValidatorPath)
    [void] $startInfo.ArgumentList.Add('--report')
    [void] $startInfo.ArgumentList.Add($Path)
    [void] $startInfo.Environment.Remove('APCA_API_KEY_ID')
    [void] $startInfo.Environment.Remove('APCA_API_SECRET_KEY')
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw 'Alpaca rights validator did not start.'
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult().Trim()
        $stderr = $stderrTask.GetAwaiter().GetResult().Trim()
        if ($process.ExitCode -ne 0) {
            throw "Alpaca rights validation failed: $stderr"
        }
        $evidence = $stdout | ConvertFrom-Json -Depth 10
        $digest = ([string] $evidence.report_sha256).Trim().ToLowerInvariant()
        if (
            $evidence.ok -ne $true -or
            $evidence.selected_vendor -ne 'alpaca_sip' -or
            -not $evidence.report_path -or
            $digest -notmatch '^[0-9a-f]{64}$'
        ) {
            throw 'Alpaca rights validator returned incomplete evidence.'
        }
        return [pscustomobject]@{
            ok = $true
            report_path = [string] $evidence.report_path
            report_sha256 = $digest
            selected_vendor = 'alpaca_sip'
        }
    }
    finally {
        [void] $startInfo.Environment.Remove('APCA_API_KEY_ID')
        [void] $startInfo.Environment.Remove('APCA_API_SECRET_KEY')
        $process.Dispose()
    }
}

function Assert-DpapiCredentialFile {
    param([Parameter(Mandatory)][string] $Path)

    $resolved = Resolve-NonReparseCredentialPath -Value $Path
    Assert-CurrentUserOnlyCredentialAcl -ResolvedPath $resolved
    $credentials = Import-Clixml -LiteralPath $resolved
    if (
        $credentials.SchemaVersion -ne 1 -or
        $credentials.ApiKeyId -isnot [securestring] -or
        $credentials.ApiSecretKey -isnot [securestring]
    ) {
        throw 'The Alpaca DPAPI credential file is invalid.'
    }
    return $resolved
}

function Get-NextWeekdayBoundary {
    $candidate = (Get-Date).Date.AddHours(13).AddMinutes(30)
    if ($candidate -le (Get-Date)) {
        $candidate = $candidate.AddDays(1)
    }
    while ($candidate.DayOfWeek -in @('Saturday', 'Sunday')) {
        $candidate = $candidate.AddDays(1)
    }
    return $candidate.ToString('yyyy-MM-ddTHH:mm:ss')
}

function Get-OwnedTask {
    param([string] $Name = $TaskName)

    $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return $null
    }
    $actionMatches = @($task.Actions) | Where-Object {
        $_.Arguments -like "*$runnerPath*"
    }
    if ($task.Description -notlike "$ownerMarker*" -or @($actionMatches).Count -ne 1) {
        throw "Task '$Name' exists but is not owned by this repository."
    }
    return $task
}

function Install-OwnedScheduledTask {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][object] $TaskDefinition,
        [Parameter(Mandatory)][string] $EvidenceOutputRoot,
        [Parameter(Mandatory)][System.Collections.IDictionary] $PlanPayload
    )

    $registeredHere = $false
    try {
        Register-ScheduledTask -TaskName $Name -InputObject $TaskDefinition | Out-Null
        $registeredHere = $true
        $installedXml = Export-ScheduledTask -TaskName $Name
        if (
            $installedXml -match '<Password>' -or
            $installedXml -match 'APCA_API_KEY_ID' -or
            $installedXml -match 'APCA_API_SECRET_KEY'
        ) {
            throw 'Installed task XML unexpectedly contains credential material.'
        }
        [xml] $parsedXml = $installedXml
        $installedBoundary = [string] $parsedXml.Task.Triggers.CalendarTrigger.StartBoundary
        if ($installedBoundary -match '(Z|[+-]\d\d:\d\d)$') {
            throw 'Installed task boundary is fixed to UTC instead of Pacific local time.'
        }
        $taskEvidenceDirectory = Join-Path $EvidenceOutputRoot 'orchestration\task'
        New-Item -ItemType Directory -Path $taskEvidenceDirectory -Force | Out-Null
        $xmlPath = Join-Path $taskEvidenceDirectory "$Name.xml"
        [System.IO.File]::WriteAllText(
            $xmlPath,
            $installedXml,
            [System.Text.UTF8Encoding]::new($false)
        )
        $PlanPayload.mode = 'install'
        $PlanPayload.scheduler_changed = $true
        $PlanPayload.task_xml_path = $xmlPath
        $PlanPayload.installed_start_boundary = $installedBoundary
        return $PlanPayload | ConvertTo-Json -Depth 10
    }
    catch {
        $installException = $_.Exception
        if ($registeredHere) {
            try {
                $ownedTask = Get-OwnedTask -Name $Name
                if ($null -ne $ownedTask) {
                    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
                }
            }
            catch {
                $rollbackException = $_.Exception
                throw [System.InvalidOperationException]::new(
                    "Task installation failed and owned-task rollback also failed: $($rollbackException.Message)",
                    $installException
                )
            }
        }
        throw $installException
    }
}

if ($Mode -eq 'Uninstall') {
    $ownedTask = Get-OwnedTask
    if ($null -eq $ownedTask) {
        [pscustomobject]@{
            mode = 'uninstall'
            task_name = $TaskName
            removed = $false
            reason = 'owned task not present'
        } | ConvertTo-Json
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    [pscustomobject]@{
        mode = 'uninstall'
        task_name = $TaskName
        removed = $true
        credentials_deleted = $false
        market_data_deleted = $false
    } | ConvertTo-Json
    exit 0
}

if (-not $OutputRoot -or -not $CaptureStartDate) {
    throw 'Plan and Install modes require OutputRoot and CaptureStartDate.'
}
if (
    $Mode -eq 'Install' -and
    $null -ne (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
) {
    throw "Task '$TaskName' already exists; installation refuses to overwrite it."
}
if ((Get-TimeZone).Id -ne 'Pacific Standard Time') {
    throw 'The scheduled task requires the Windows Pacific Standard Time zone.'
}
if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
    throw "EOD runner not found: $runnerPath"
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found: $PythonPath"
}
$pwshPath = (Get-Command pwsh -ErrorAction Stop).Source
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputRoot)
$repoBoundary = (Resolve-CanonicalBoundaryPath $repoRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
$outputBoundary = (Resolve-CanonicalBoundaryPath $resolvedOutput).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
$repoPrefix = $repoBoundary + [System.IO.Path]::DirectorySeparatorChar
$pathComparison = [System.StringComparison]::OrdinalIgnoreCase
if (
    [string]::Equals($outputBoundary, $repoBoundary, $pathComparison) -or
    $outputBoundary.StartsWith($repoPrefix, $pathComparison)
) {
    throw 'Alpaca EOD output must be outside the Git worktree.'
}
$rightsArgument = if ($RightsDecisionReport) {
    [System.IO.Path]::GetFullPath($RightsDecisionReport)
} else {
    '<required-passing-vendor-decision-report>'
}
$expectedRightsArgument = '<required-validated-vendor-decision-sha256>'
foreach ($item in @(
    @{ Value = $runnerPath; Label = 'RunnerPath' },
    @{ Value = $PythonPath; Label = 'PythonPath' },
    @{ Value = $resolvedOutput; Label = 'OutputRoot' },
    @{ Value = $CaptureStartDate; Label = 'CaptureStartDate' },
    @{ Value = $CredentialPath; Label = 'CredentialPath' },
    @{ Value = $rightsArgument; Label = 'RightsDecisionReport' },
    @{ Value = $expectedRightsArgument; Label = 'ExpectedRightsDecisionSha256' }
)) {
    Assert-SafeTaskValue -Value $item.Value -Label $item.Label
}
$actionArguments = @(
    '-NoLogo',
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy', 'Bypass',
    '-File', (Quote-TaskValue $runnerPath),
    '-PythonPath', (Quote-TaskValue $PythonPath),
    '-OutputRoot', (Quote-TaskValue $resolvedOutput),
    '-CaptureStartDate', $CaptureStartDate,
    '-CredentialPath', (Quote-TaskValue $CredentialPath),
    '-RightsDecisionReport', (Quote-TaskValue $rightsArgument),
    '-ExpectedRightsDecisionSha256', (Quote-TaskValue $expectedRightsArgument)
) -join ' '
$action = New-ScheduledTaskAction -Execute $pwshPath -Argument $actionArguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At '1:30 PM'
$trigger.StartBoundary = Get-NextWeekdayBoundary
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$settings.WakeToRun = $false
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$currentSid = $currentIdentity.User.Value
$principal = New-ScheduledTaskPrincipal -UserId $currentSid -LogonType Interactive -RunLevel Limited
$description = "$ownerMarker; owner=$currentSid; repo=$repoRoot"
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $description

$plan = [ordered]@{
    mode = $Mode.ToLowerInvariant()
    task_name = $TaskName
    timezone = (Get-TimeZone).Id
    schedule = '13:30 Pacific Monday-Friday; XNYS calendar enforced by runner'
    start_boundary = $trigger.StartBoundary
    start_boundary_has_offset = $trigger.StartBoundary -match '(Z|[+-]\d\d:\d\d)$'
    execute = $pwshPath
    arguments = $actionArguments
    principal_sid = $currentSid
    logon_type = 'Interactive'
    run_level = 'Limited'
    start_when_available = $settings.StartWhenAvailable
    network_required = $settings.RunOnlyIfNetworkAvailable
    restart_count = $settings.RestartCount
    restart_interval = [string] $settings.RestartInterval
    multiple_instances = [string] $settings.MultipleInstances
    execution_time_limit = [string] $settings.ExecutionTimeLimit
    wake_to_run = $settings.WakeToRun
    rights_required = $true
    credential_values_in_arguments = $false
    credentials_read = $false
    network_accessed = $false
    scheduler_changed = $false
}

if ($Mode -eq 'Plan') {
    $plan | ConvertTo-Json -Depth 10
    exit 0
}

$planCheck = & $pwshPath -NoLogo -NoProfile -NonInteractive -File $runnerPath `
    -OutputRoot $resolvedOutput `
    -CaptureStartDate $CaptureStartDate `
    -CredentialPath $CredentialPath `
    -RightsDecisionReport $rightsArgument `
    -PythonPath $PythonPath `
    -PlanOnly
if ($LASTEXITCODE -ne 0) {
    throw 'EOD runner plan-only validation failed.'
}
$runnerPlan = $planCheck | ConvertFrom-Json -Depth 40
if ($runnerPlan.release.worktree_clean -ne $true) {
    throw 'Task installation requires a clean committed acquisition release.'
}

$rightsEvidence = Invoke-RightsValidation -Path $RightsDecisionReport
$rightsPath = [string] $rightsEvidence.report_path
$rightsSha256 = [string] $rightsEvidence.report_sha256
if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) {
    throw "DPAPI credential file not found: $CredentialPath"
}
$CredentialPath = Assert-DpapiCredentialFile -Path $CredentialPath
foreach ($item in @(
    @{ Value = $rightsPath; Label = 'CanonicalRightsDecisionReport' },
    @{ Value = $rightsSha256; Label = 'ExpectedRightsDecisionSha256' },
    @{ Value = $CredentialPath; Label = 'CanonicalCredentialPath' }
)) {
    Assert-SafeTaskValue -Value $item.Value -Label $item.Label
}
$actionArguments = @(
    '-NoLogo',
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy', 'Bypass',
    '-File', (Quote-TaskValue $runnerPath),
    '-PythonPath', (Quote-TaskValue $PythonPath),
    '-OutputRoot', (Quote-TaskValue $resolvedOutput),
    '-CaptureStartDate', $CaptureStartDate,
    '-CredentialPath', (Quote-TaskValue $CredentialPath),
    '-RightsDecisionReport', (Quote-TaskValue $rightsPath),
    '-ExpectedRightsDecisionSha256', (Quote-TaskValue $rightsSha256)
) -join ' '
$action = New-ScheduledTaskAction `
    -Execute $pwshPath `
    -Argument $actionArguments `
    -WorkingDirectory $repoRoot
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $description
$plan.arguments = $actionArguments
$plan.rights_decision_report = $rightsPath
$plan.rights_decision_sha256 = $rightsSha256

Install-OwnedScheduledTask `
    -Name $TaskName `
    -TaskDefinition $task `
    -EvidenceOutputRoot $resolvedOutput `
    -PlanPayload $plan
