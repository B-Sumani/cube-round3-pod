<#
.SYNOPSIS
  Windows equivalent of the Makefile (no make needed). Works in Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
  .\pod.ps1 setup
  .\pod.ps1 test
  .\pod.ps1 run
  .\pod.ps1 case -Unit UNIT-0014 -Org org_demo_alpha
  .\pod.ps1 serve
  .\pod.ps1 test -- -q tests/integration/test_agent_contracts.py   # args after -- go to pytest
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "test", "e2e", "run", "case", "serve", "health", "cases", "expected", "examples", "help")]
    [string]$Target = "help",
    [string]$Unit,
    [string]$Org,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Assert-Venv {
    if (-not (Test-Path -LiteralPath $Py)) { throw "No .venv found. Run: .\pod.ps1 setup" }
}

function Find-BasePython {
    # Prefer the py launcher (picks the newest installed 3.x); fall back to python on PATH.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.13", "-3.12", "-3.11", "-3")) {
            & py $v -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return @("py", $v) }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return @("python") }
    }
    throw "Python 3.11+ not found. Install it from python.org (tick 'Add to PATH' / install the py launcher)."
}

switch ($Target) {
    "setup" {
        $base = Find-BasePython
        $baseArgs = @()
        if ($base.Length -gt 1) { $baseArgs = $base[1..($base.Length - 1)] }
        Invoke-Checked $base[0] ($baseArgs + @("-m", "venv", ".venv"))
        Invoke-Checked $Py @("-m", "pip", "install", "-r", "requirements.txt")
        if (-not (Test-Path -LiteralPath ".env")) { Copy-Item ".env.example" ".env"; Write-Host "created .env from .env.example" }
    }
    "test"     { Assert-Venv; Invoke-Checked $Py (@("-m", "pytest") + $Rest) }
    "e2e"      { Assert-Venv; Invoke-Checked $Py (@("-m", "pytest", "tests/e2e") + $Rest) }
    "run" {
        Assert-Venv
        $env:LOG_LEVEL = "WARNING"
        try { Invoke-Checked $Py (@("-m", "orchestration.run", "--all") + $Rest) } finally { Remove-Item Env:LOG_LEVEL -ErrorAction SilentlyContinue }
    }
    "case" {
        Assert-Venv
        if (-not $Unit -or -not $Org) { throw "usage: .\pod.ps1 case -Unit UNIT-0014 -Org org_demo_alpha" }
        Invoke-Checked $Py @("-m", "orchestration.run", "--unit", $Unit, "--org", $Org)
    }
    "serve"    { Assert-Venv; Invoke-Checked $Py @("-m", "uvicorn", "orchestration.api:app", "--port", "8100") }
    "health"   { (Invoke-RestMethod -Uri "http://localhost:8100/health") | ConvertTo-Json -Depth 6 }
    "cases"    { Assert-Venv; Invoke-Checked $Py @("scripts/build_sample_cases.py") }
    "expected" { Assert-Venv; Invoke-Checked $Py @("scripts/build_expected.py") }
    "examples" { Assert-Venv; Invoke-Checked $Py @("scripts/make_examples.py") }
    default {
        Write-Host "usage: .\pod.ps1 <setup|test|e2e|run|case|serve|health|cases|expected|examples> [-Unit U -Org O] [-- extra args]"
    }
}
