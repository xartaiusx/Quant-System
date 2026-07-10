$ErrorActionPreference = "Stop"

$PythonBin = if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    ".venv\Scripts\python.exe"
} elseif ($env:PYTHON) {
    $env:PYTHON
} else {
    "python"
}

Write-Host "Python: $PythonBin"
& $PythonBin -m trader.broker.ibapi_compatibility
exit $LASTEXITCODE
