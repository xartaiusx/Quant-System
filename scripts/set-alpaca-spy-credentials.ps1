[CmdletBinding()]
param(
    [string] $CredentialPath,
    [switch] $TestMode
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw 'Alpaca DPAPI credential storage is supported only on Windows.'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$credentialPathWasProvided = $PSBoundParameters.ContainsKey('CredentialPath')
if (-not $CredentialPath) {
    $CredentialPath = Join-Path $repoRoot 'Quant Creds\Alpaca\credentials.clixml'
}
$CredentialPath = [System.IO.Path]::GetFullPath($CredentialPath)
$credentialDirectory = Split-Path -Parent $CredentialPath
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
if ($null -eq $currentSid) {
    throw 'The current Windows user SID could not be resolved.'
}

function Set-UserOnlyDirectoryAcl {
    param([Parameter(Mandatory)][string] $Path)

    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($currentSid)
    $acl.SetAccessRuleProtection($true, $false)
    $rights = [System.Security.AccessControl.FileSystemRights]::FullControl
    $inheritance = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $currentSid,
        $rights,
        $inheritance,
        $propagation,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    [void] $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Set-UserOnlyFileAcl {
    param([Parameter(Mandatory)][string] $Path)

    $acl = [System.Security.AccessControl.FileSecurity]::new()
    $acl.SetOwner($currentSid)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $currentSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    [void] $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

New-Item -ItemType Directory -Path $credentialDirectory -Force | Out-Null
Set-UserOnlyDirectoryAcl -Path $credentialDirectory

if ($TestMode) {
    if (-not $credentialPathWasProvided) {
        throw 'TestMode requires an explicit temporary CredentialPath.'
    }
    $apiKeyId = ConvertTo-SecureString 'quant-system-dpapi-test-key' -AsPlainText -Force
    $apiSecretKey = ConvertTo-SecureString 'quant-system-dpapi-test-secret' -AsPlainText -Force
}
else {
    $apiKeyId = Read-Host 'Alpaca API key ID' -AsSecureString
    $apiSecretKey = Read-Host 'Alpaca API secret key' -AsSecureString
}
if ($apiKeyId.Length -eq 0 -or $apiSecretKey.Length -eq 0) {
    throw 'Both Alpaca credential fields are required.'
}

$temporaryPath = Join-Path $credentialDirectory ('.credentials.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
try {
    [pscustomobject]@{
        SchemaVersion = 1
        ApiKeyId = $apiKeyId
        ApiSecretKey = $apiSecretKey
    } | Export-Clixml -LiteralPath $temporaryPath -Depth 3
    Set-UserOnlyFileAcl -Path $temporaryPath
    $roundTrip = Import-Clixml -LiteralPath $temporaryPath
    if (
        $roundTrip.SchemaVersion -ne 1 -or
        $roundTrip.ApiKeyId -isnot [securestring] -or
        $roundTrip.ApiSecretKey -isnot [securestring]
    ) {
        throw 'DPAPI credential round-trip validation failed.'
    }
    [System.IO.File]::Move($temporaryPath, $CredentialPath, $true)
    Set-UserOnlyFileAcl -Path $CredentialPath
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
    $apiKeyId = $null
    $apiSecretKey = $null
}

[pscustomobject]@{
    stored = $true
    credential_path = $CredentialPath
    secure_string_fields = 2
    test_mode = [bool] $TestMode
} | ConvertTo-Json
