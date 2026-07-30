[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $OutputRoot,
    [Parameter(Mandatory)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string] $CaptureStartDate,
    [string] $CredentialPath,
    [string] $RightsDecisionReport,
    [string] $ExpectedRightsDecisionSha256,
    [string] $PythonPath,
    [switch] $PlanOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

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

if (-not $PythonPath) {
    $PythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not $CredentialPath) {
    $CredentialPath = Join-Path $repoRoot 'Quant Creds\Alpaca\credentials.clixml'
}
$outputPath = [System.IO.Path]::GetFullPath($OutputRoot)
$repoBoundary = (Resolve-CanonicalBoundaryPath $repoRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
$outputBoundary = (Resolve-CanonicalBoundaryPath $outputPath).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
$repoPrefix = $repoBoundary + [System.IO.Path]::DirectorySeparatorChar
$pathComparison = [System.StringComparison]::OrdinalIgnoreCase
if (
    [string]::Equals($outputBoundary, $repoBoundary, $pathComparison) -or
    $outputBoundary.StartsWith($repoPrefix, $pathComparison)
) {
    throw 'Alpaca EOD output must be outside the Git worktree.'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found: $PythonPath"
}

function Invoke-PythonChild {
    param(
        [Parameter(Mandatory)][string[]] $Arguments,
        [string] $ApiKeyId,
        [string] $ApiSecretKey
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $PythonPath
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    foreach ($argument in $Arguments) {
        [void] $startInfo.ArgumentList.Add($argument)
    }
    [void] $startInfo.Environment.Remove('APCA_API_KEY_ID')
    [void] $startInfo.Environment.Remove('APCA_API_SECRET_KEY')
    $startInfo.Environment['TRADING_MODE'] = 'paper'
    $startInfo.Environment['ALLOW_PAPER_ORDERS'] = 'false'
    $startInfo.Environment['ALLOW_LIVE_ORDERS'] = 'false'
    if ($PSBoundParameters.ContainsKey('ApiKeyId')) {
        $startInfo.Environment['APCA_API_KEY_ID'] = $ApiKeyId
        $startInfo.Environment['APCA_API_SECRET_KEY'] = $ApiSecretKey
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw 'Python child process did not start.'
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdoutTask.GetAwaiter().GetResult().Trim()
            Stderr = $stderrTask.GetAwaiter().GetResult().Trim()
        }
    }
    finally {
        [void] $startInfo.Environment.Remove('APCA_API_KEY_ID')
        [void] $startInfo.Environment.Remove('APCA_API_SECRET_KEY')
        $process.Dispose()
    }
}

function Get-EodPlan {
    $result = Invoke-PythonChild -Arguments @(
        'scripts/plan_alpaca_spy_eod.py',
        '--output-root', $outputPath,
        '--capture-start-date', $CaptureStartDate
    )
    if ($result.ExitCode -ne 0) {
        throw "EOD planning failed: $($result.Stderr)"
    }
    return $result.Stdout | ConvertFrom-Json -Depth 20
}

function Get-SessionCapturePlan {
    param([Parameter(Mandatory)][string] $SessionDate)

    $result = Invoke-PythonChild -Arguments @(
        'scripts/acquire_alpaca_spy.py',
        '--symbol', 'SPY',
        '--feed', 'sip',
        '--timeframe', '1Min',
        '--session-date', $SessionDate,
        '--output-root', $outputPath,
        '--plan-only'
    )
    if ($result.ExitCode -ne 0) {
        throw "$SessionDate capture planning failed: $($result.Stderr)"
    }
    return $result.Stdout | ConvertFrom-Json -Depth 10
}

function Assert-SessionCaptureResult {
    param(
        [Parameter(Mandatory)][psobject] $Capture,
        [Parameter(Mandatory)][psobject] $ExpectedPlan,
        [Parameter(Mandatory)][string] $SessionDate,
        [Parameter(Mandatory)][string] $RightsPath,
        [Parameter(Mandatory)][string] $RightsSha256
    )

    $manifestPaths = @($Capture.manifest_paths)
    $expectedCount = [long] $ExpectedPlan.expected_bar_count
    if (
        $ExpectedPlan.session_date -ne $SessionDate -or
        $expectedCount -notin @(210, 390) -or
        $Capture.ok -ne $true -or
        $Capture.source -ne 'alpaca_sip' -or
        $Capture.symbol -ne 'SPY' -or
        $Capture.feed -ne 'sip' -or
        $Capture.timeframe -ne '1Min' -or
        [long] $Capture.partition_count -ne 1 -or
        [long] $Capture.total_bars -ne $expectedCount -or
        $manifestPaths.Count -ne 1 -or
        $Capture.research_eligible -ne $false -or
        $Capture.acquisition_rights_validated -ne $true -or
        $Capture.vendor_decision_report -ne $RightsPath -or
        $Capture.vendor_decision_sha256 -ne $RightsSha256
    ) {
        throw "$SessionDate capture returned invalid or incomplete success evidence."
    }
}

function Get-FinalPlanErrors {
    param([Parameter(Mandatory)][psobject] $Plan)

    $planErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($sessionDate in @($Plan.missing_sessions)) {
        $planErrors.Add("Required session remains incomplete: $sessionDate")
    }
    foreach ($sessionDate in @($Plan.correction_sessions_due)) {
        $planErrors.Add("Required correction recapture remains due: $sessionDate")
    }
    foreach ($sessionDate in @($Plan.capture_sessions)) {
        $planErrors.Add("Required capture remains pending: $sessionDate")
    }
    foreach ($pair in @($Plan.compare_pairs)) {
        $planErrors.Add("Required correction comparison remains incomplete: $($pair.session_date)")
    }
    return @($planErrors)
}

function Get-AlpacaRightsEvidence {
    if (-not $RightsDecisionReport) {
        throw 'A passing Alpaca vendor-decision report is required before network capture.'
    }
    $result = Invoke-PythonChild -Arguments @(
        'scripts/validate_alpaca_rights.py',
        '--report', $RightsDecisionReport
    )
    if ($result.ExitCode -ne 0) {
        throw "Alpaca rights validation failed: $($result.Stderr)"
    }
    $evidence = $result.Stdout | ConvertFrom-Json -Depth 10
    if (
        $evidence.ok -ne $true -or
        $evidence.selected_vendor -ne 'alpaca_sip' -or
        -not $evidence.report_path -or
        -not $evidence.report_sha256
    ) {
        throw 'Alpaca rights validator returned incomplete evidence.'
    }
    return $evidence
}

function Assert-PinnedRightsEvidence {
    param(
        [Parameter(Mandatory)][psobject] $Evidence,
        [Parameter(Mandatory)][string] $ExpectedSha256
    )

    $expected = $ExpectedSha256.Trim().ToLowerInvariant()
    $actual = ([string] $Evidence.report_sha256).Trim().ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$') {
        throw 'The pinned Alpaca vendor-decision SHA-256 is invalid.'
    }
    if ($actual -ne $expected) {
        throw 'The Alpaca vendor-decision report does not match the pinned SHA-256.'
    }
    return [pscustomobject]@{
        report_path = [string] $Evidence.report_path
        report_sha256 = $actual
    }
}

function Convert-SecureStringForChild {
    param([Parameter(Mandatory)][securestring] $Value)

    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

function Get-ReleaseEvidence {
    $commitSha = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commitSha) {
        throw 'Unable to resolve the acquisition release commit.'
    }
    $status = @(& git -C $repoRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to inspect the acquisition worktree.'
    }
    $relativeFiles = @(
        'pyproject.toml',
        'scripts/acquire_alpaca_spy.py',
        'scripts/plan_alpaca_spy_eod.py',
        'scripts/run-alpaca-spy-eod.ps1',
        'scripts/validate_alpaca_rights.py',
        'src/trader/alpaca_session_compare_cli.py',
        'src/trader/data/alpaca_acquisition.py',
        'src/trader/data/alpaca_rights_gate.py',
        'src/trader/data/alpaca_session_artifacts.py',
        'src/trader/data/alpaca_session_compare.py'
    )
    $fileHashes = [ordered]@{}
    foreach ($relativePath in $relativeFiles) {
        $fullPath = Join-Path $repoRoot $relativePath
        $fileHashes[$relativePath] = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $fingerprintMaterial = @($commitSha) + @(
        $fileHashes.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
    )
    $fingerprintBytes = [System.Text.Encoding]::UTF8.GetBytes(($fingerprintMaterial -join "`n") + "`n")
    $fingerprint = [Convert]::ToHexString(
        [System.Security.Cryptography.SHA256]::HashData($fingerprintBytes)
    ).ToLowerInvariant()
    return [pscustomobject]@{
        commit_sha = $commitSha
        worktree_clean = @($status).Count -eq 0
        configuration_fingerprint = $fingerprint
        file_sha256 = $fileHashes
    }
}

$releaseEvidence = Get-ReleaseEvidence
$initialPlan = Get-EodPlan
if ($PlanOnly) {
    [pscustomobject]@{
        mode = 'plan_only'
        runner = 'run-alpaca-spy-eod.ps1'
        plan = $initialPlan
        release = $releaseEvidence
        rights_read = $false
        credentials_read = $false
        network_accessed = $false
        files_written = $false
        broker_contacted = $false
        submitted_orders = $false
        paper_orders_enabled = $false
        order_api_invoked = $false
        catalog_activated = $false
        research_eligible = $false
        promotion_eligible = $false
        graduation_eligible = $false
    } | ConvertTo-Json -Depth 30
    exit 0
}

if ($releaseEvidence.worktree_clean -ne $true) {
    throw 'Unattended Alpaca acquisition requires a clean committed release.'
}
if (-not $ExpectedRightsDecisionSha256) {
    throw 'A pinned Alpaca vendor-decision SHA-256 is required before network capture.'
}

$rightsEvidence = Get-AlpacaRightsEvidence
$pinnedRights = Assert-PinnedRightsEvidence `
    -Evidence $rightsEvidence `
    -ExpectedSha256 $ExpectedRightsDecisionSha256
$rightsPath = [string] $pinnedRights.report_path
$rightsSha256 = [string] $pinnedRights.report_sha256
$CredentialPath = Resolve-NonReparseCredentialPath -Value $CredentialPath
Assert-CurrentUserOnlyCredentialAcl -ResolvedPath $CredentialPath
$credentials = Import-Clixml -LiteralPath $CredentialPath
if (
    $credentials.SchemaVersion -ne 1 -or
    $credentials.ApiKeyId -isnot [securestring] -or
    $credentials.ApiSecretKey -isnot [securestring]
) {
    throw 'The Alpaca DPAPI credential file is invalid.'
}

$apiKeyIdPlain = $null
$apiSecretPlain = $null
$captureResults = [System.Collections.Generic.List[object]]::new()
$comparisonResults = [System.Collections.Generic.List[object]]::new()
$errors = [System.Collections.Generic.List[string]]::new()
$orchestrationRoot = Join-Path $outputPath 'orchestration'
$reportsDirectory = Join-Path $orchestrationRoot 'reports'
$comparisonDirectory = Join-Path $orchestrationRoot 'comparisons'
$healthDirectory = Join-Path $orchestrationRoot 'health'
New-Item -ItemType Directory -Path $reportsDirectory, $comparisonDirectory, $healthDirectory -Force | Out-Null
$startedAt = [datetime]::UtcNow

try {
    $apiKeyIdPlain = Convert-SecureStringForChild -Value $credentials.ApiKeyId
    $apiSecretPlain = Convert-SecureStringForChild -Value $credentials.ApiSecretKey
    foreach ($sessionDate in @($initialPlan.capture_sessions)) {
        try {
            $expectedCapture = Get-SessionCapturePlan -SessionDate ([string] $sessionDate)
        }
        catch {
            $errors.Add($_.Exception.Message)
            continue
        }
        $result = Invoke-PythonChild -Arguments @(
            'scripts/acquire_alpaca_spy.py',
            '--symbol', 'SPY',
            '--feed', 'sip',
            '--timeframe', '1Min',
            '--session-date', [string] $sessionDate,
            '--output-root', $outputPath,
            '--vendor-decision-report', $rightsPath,
            '--expected-vendor-decision-sha256', $rightsSha256
        ) -ApiKeyId $apiKeyIdPlain -ApiSecretKey $apiSecretPlain
        if ($result.ExitCode -ne 0) {
            $errors.Add("$sessionDate capture failed: $($result.Stderr)")
            continue
        }
        try {
            $capture = $result.Stdout | ConvertFrom-Json -Depth 20
            Assert-SessionCaptureResult `
                -Capture $capture `
                -ExpectedPlan $expectedCapture `
                -SessionDate ([string] $sessionDate) `
                -RightsPath $rightsPath `
                -RightsSha256 $rightsSha256
            $captureResults.Add([pscustomobject]@{
                session_date = [string] $sessionDate
                ok = $capture.ok
                total_bars = $capture.total_bars
                manifest_paths = @($capture.manifest_paths)
                vendor_decision_report = $capture.vendor_decision_report
                vendor_decision_sha256 = $capture.vendor_decision_sha256
            })
        }
        catch {
            $errors.Add($_.Exception.Message)
        }
    }

    $comparisonPlan = Get-EodPlan
    foreach ($pair in @($comparisonPlan.compare_pairs)) {
        $sessionComparisonDirectory = Join-Path $comparisonDirectory ([string] $pair.session_date)
        New-Item -ItemType Directory -Path $sessionComparisonDirectory -Force | Out-Null
        $compare = Invoke-PythonChild -Arguments @(
            '-m', 'trader.alpaca_session_compare_cli',
            '--baseline-manifest', [string] $pair.baseline_manifest,
            '--candidate-manifest', [string] $pair.candidate_manifest,
            '--reports-dir', $sessionComparisonDirectory
        )
        if ($compare.ExitCode -ne 0) {
            $errors.Add("$($pair.session_date) correction comparison failed: $($compare.Stderr)")
            continue
        }
        try {
            $compareEvidence = $compare.Stdout | ConvertFrom-Json -Depth 10
            $reportPath = [string] $compareEvidence.json_report_path
            $reportSha256 = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        catch {
            $errors.Add("$($pair.session_date) comparison evidence was invalid")
            continue
        }
        $comparisonResults.Add([pscustomobject]@{
            session_date = [string] $pair.session_date
            baseline_manifest = [string] $pair.baseline_manifest
            candidate_manifest = [string] $pair.candidate_manifest
            report_path = $reportPath
            report_sha256 = $reportSha256
            ok = $true
        })
    }
    $finalPlan = Get-EodPlan
    foreach ($planError in @(Get-FinalPlanErrors -Plan $finalPlan)) {
        $errors.Add($planError)
    }
}
catch {
    $errors.Add($_.Exception.Message)
    $finalPlan = $null
}
finally {
    $apiKeyIdPlain = $null
    $apiSecretPlain = $null
    $credentials = $null
}

$ok = $errors.Count -eq 0 -and $null -ne $finalPlan
$completedAt = [datetime]::UtcNow
$report = [ordered]@{
    report_version = 1
    report_type = 'alpaca_eod_orchestration'
    source = 'alpaca_sip'
    symbol = 'SPY'
    started_at = $startedAt.ToString('o')
    completed_at = $completedAt.ToString('o')
    final_status = $(if ($ok) { 'passed' } else { 'failed' })
    capture_start_date = $CaptureStartDate
    rights_decision_report = $rightsPath
    rights_decision_sha256 = $rightsSha256
    commit_sha = [string] $releaseEvidence.commit_sha
    configuration_fingerprint = [string] $releaseEvidence.configuration_fingerprint
    configuration_file_sha256 = $releaseEvidence.file_sha256
    initial_plan = $initialPlan
    final_plan = $finalPlan
    captures = @($captureResults)
    comparisons = @($comparisonResults)
    errors = @($errors)
    credentials_read = $true
    network_accessed = @($initialPlan.capture_sessions).Count -gt 0
    broker_contacted = $false
    submitted_orders = $false
    paper_orders_enabled = $false
    order_api_invoked = $false
    catalog_activated = $false
    automatically_derived = $false
    automatically_backtested = $false
    research_eligible = $false
    promotion_eligible = $false
    graduation_eligible = $false
    success_state_advanced = $ok
}
$reportJson = $report | ConvertTo-Json -Depth 40
$reportName = 'alpaca_eod_orchestration_{0}_{1}.json' -f $completedAt.ToString('yyyyMMddTHHmmssZ'), [guid]::NewGuid().ToString('N').Substring(0, 8)
$reportPath = Join-Path $reportsDirectory $reportName
$stream = [System.IO.File]::Open($reportPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
$writer = $null
try {
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
    $writer.WriteLine($reportJson)
    $writer.Flush()
}
finally {
    if ($null -ne $writer) { $writer.Dispose() } else { $stream.Dispose() }
}

if ($ok) {
    $healthPath = Join-Path $healthDirectory 'latest.json'
    $temporaryHealth = Join-Path $healthDirectory ('.latest.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
    [System.IO.File]::WriteAllText($temporaryHealth, $reportJson + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Move($temporaryHealth, $healthPath, $true)
}

Write-Output $reportJson
if (-not $ok) {
    exit 1
}
