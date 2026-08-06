<#
.SYNOPSIS
    Faehrt die drei Testsuiten der lokalen Wissensportal-Abnahme.

.DESCRIPTION
    Die Suiten laufen bewusst in getrennten pytest-Prozessen: kb-admin-api und
    kb-sync besitzen jeweils ein eigenes Paket `app`, das nicht gemeinsam in
    einen Python-Prozess geladen werden kann.

    Die Modul-Suchpfade setzen die conftest.py der jeweiligen Testverzeichnisse,
    ein PYTHONPATH muss nicht von aussen gesetzt werden.

.PARAMETER Python
    Interpreter, der die Abhaengigkeiten aus stack/requirements-dev.txt besitzt.
    Standard ist "python".

.EXAMPLE
    .\scripts\run-local-tests.ps1
    .\scripts\run-local-tests.ps1 -Python C:\venvs\vinci\Scripts\python.exe
#>
[CmdletBinding()]
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

$suites = @(
    @{ Name = "Portal-Backend";  Path = "stack/kb-admin-api"; Tests = "tests" }
    @{ Name = "Stack und Sicherheit"; Path = "stack";         Tests = "tests" }
    @{ Name = "Hybridindex";     Path = "stack/kb-sync";      Tests = "tests" }
)

$results = @()
$failed = $false

foreach ($suite in $suites) {
    $workingDir = Join-Path $repoRoot $suite.Path
    Write-Host ""
    Write-Host "=== $($suite.Name) ($($suite.Path)) ===" -ForegroundColor Cyan

    Push-Location $workingDir
    try {
        & $Python -m pytest $suite.Tests -q -p no:cacheprovider
        $code = $LASTEXITCODE
    }
    finally {
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
Write-Host "=== Gesamtergebnis ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize

if ($failed) {
    Write-Host "Mindestens eine Suite ist fehlgeschlagen." -ForegroundColor Red
    exit 1
}

Write-Host "Alle Suiten bestanden." -ForegroundColor Green
exit 0
