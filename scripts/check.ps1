$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$systemPython = Get-Command python -ErrorAction SilentlyContinue
$python = if (Test-Path -LiteralPath $venvPython) {
    (Resolve-Path -LiteralPath $venvPython).Path
}
elseif ($systemPython) {
    $systemPython.Source
}
else {
    $null
}
$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue

if (-not $python) {
    throw "Python 3.12 is required on PATH."
}
if (-not $pnpm) {
    throw "pnpm 11 is required on PATH."
}

Push-Location "apps/api"
try {
    Invoke-Checked $python @("-m", "ruff", "check", "--no-cache", "app", "tests", "alembic")
    Invoke-Checked $python @("-m", "ruff", "format", "--check", "--no-cache", "app", "tests", "alembic")
    $mypyCache = Join-Path $PSScriptRoot "..\.mypy_cache"
    Invoke-Checked $python @("-m", "mypy", "--cache-dir", $mypyCache, "app")
    Invoke-Checked $python @("-m", "pytest")
}
finally {
    Pop-Location
}

Invoke-Checked $python @("-m", "ruff", "check", "--config", "apps/api/pyproject.toml", "--no-cache", "scripts", "tests")
Invoke-Checked $python @("-m", "unittest", "discover", "-s", "tests", "-v")
Invoke-Checked $python @("scripts/validate_compose.py", "docker-compose.yml")
Invoke-Checked $pnpm.Source @("typecheck")
Invoke-Checked $pnpm.Source @("lint")
Invoke-Checked $pnpm.Source @("test")
Invoke-Checked $pnpm.Source @("format:check")
