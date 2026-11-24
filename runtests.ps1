<#
.SYNOPSIS
    Lint, then the test suite; fails when the tests against the real API did not run.

.DESCRIPTION
    1. Lint: ruff check . (ruff.toml).
    2. The suite. Most tests start the ArchiMate API from the folder next to
       this one (..\ArchiMateAPI, or ARCHIMATE_API_DIR). Without it pytest
       skips them; this script then fails, since an item counts as done only
       when they pass (see PLAN.md).

    The API's runtests.ps1 -WithClients runs this script too, so that a change
    of the API is tested against this server.

.PARAMETER PytestArgs
    Passed on to pytest, for example  -PytestArgs '-k','http'

.EXAMPLE
    .\runtests.ps1
#>
[CmdletBinding()]
param(
    [string[]]$PytestArgs = @('-q')
)

Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "=== Lint (ruff) ===" -ForegroundColor Cyan
& $python -m ruff check .
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: ruff found problems (or is not installed: pip install -r requirements-dev.txt)." -ForegroundColor Red
    exit 1
}

Write-Host "=== Suite ===" -ForegroundColor Cyan
$output = & $python -m pytest -p no:cacheprovider -rs @PytestArgs
$code = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }

if ($code -ne 0) {
    Write-Host "FAILED: pytest exit code $code." -ForegroundColor Red
    exit 1
}
if ($output -match 'SKIPPED') {
    Write-Host "FAILED: tests were skipped (is the ArchiMate API next to this folder?)." -ForegroundColor Red
    exit 1
}
Write-Host "All tests passed." -ForegroundColor Green
exit 0
