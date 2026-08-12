<#
.SYNOPSIS
    Faehrt alle Testsuiten der lokalen Wissensportal-Abnahme.

.DESCRIPTION
    Die Python-Suiten laufen bewusst in getrennten pytest-Prozessen: kb-admin-api und
    kb-sync besitzen jeweils ein eigenes Paket `app`, das nicht gemeinsam in
    einen Python-Prozess geladen werden kann.

    Die Modul-Suchpfade setzen die conftest.py der jeweiligen Testverzeichnisse,
    ein PYTHONPATH muss nicht von aussen gesetzt werden.

.PARAMETER Python
    Interpreter, der die Abhaengigkeiten aus stack/requirements-dev.txt besitzt.
    Standard ist "python".

.PARAMETER Npm
    NPM-Kommando fuer Produktionsbuild, Renderingtests und Lint des Portals.
    Standard ist "npm".

.EXAMPLE
    .\scripts\run-local-tests.ps1
    .\scripts\run-local-tests.ps1 -Python C:\venvs\vinci\Scripts\python.exe -Npm npm.cmd
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Npm = "npm"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

$suites = @(
    @{ Name = "Portal-Backend";  Path = "stack/kb-admin-api"; Tests = "tests"; PythonPath = "" }
    @{ Name = "Stack und Sicherheit"; Path = "stack";         Tests = "tests"; PythonPath = "" }
    @{ Name = "Hybridindex";     Path = "stack/kb-sync";      Tests = "tests"; PythonPath = "" }
    @{ Name = "RAG-Evaluation";  Path = "eval/rag"; Tests = "tests"; PythonPath = "eval/rag;stack/kb-sync" }
)

$results = @()
$failed = $false

foreach ($suite in $suites) {
    $workingDir = Join-Path $repoRoot $suite.Path
    Write-Host ""
    Write-Host "=== $($suite.Name) ($($suite.Path)) ===" -ForegroundColor Cyan

    Push-Location $workingDir
    $previousPythonPath = $env:PYTHONPATH
    try {
        if ($suite.PythonPath) {
            $paths = @($suite.PythonPath -split ';' | ForEach-Object { Join-Path $repoRoot $_ })
            $env:PYTHONPATH = $paths -join [IO.Path]::PathSeparator
        }
        & $Python -m pytest $suite.Tests -q -p no:cacheprovider
        $code = $LASTEXITCODE
    }
    finally {
        $env:PYTHONPATH = $previousPythonPath
        Pop-Location
    }

    if ($code -ne 0) { $failed = $true }
    $results += [pscustomobject]@{
        Suite    = $suite.Name
        Pfad     = $suite.Path
        Ergebnis = if ($code -eq 0) { "bestanden" } else { "FEHLGESCHLAGEN (Exitcode $code)" }
    }
}

Write-Host ""
Write-Host "=== Portal-UI (admin-dashboard) ===" -ForegroundColor Cyan
Push-Location (Join-Path $repoRoot "admin-dashboard")
try {
    & $Npm test
    $uiCode = $LASTEXITCODE
    if ($uiCode -eq 0) {
        & $Npm run lint
        $uiCode = $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
if ($uiCode -ne 0) { $failed = $true }
$results += [pscustomobject]@{
    Suite    = "Portal-UI"
    Pfad     = "admin-dashboard"
    Ergebnis = if ($uiCode -eq 0) { "bestanden" } else { "FEHLGESCHLAGEN (Exitcode $uiCode)" }
}

Write-Host ""
Write-Host "=== Gesamtergebnis ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize

if ($failed) {
    Write-Host "Mindestens eine Suite ist fehlgeschlagen." -ForegroundColor Red
    exit 1
}

Write-Host "Alle Suiten bestanden." -ForegroundColor Green
exit 0
