<#
.SYNOPSIS
    Fuehrt die kanonische lokale Verification fuer KAHLE-Vinci aus.

.DESCRIPTION
    Fast prueft die breiten, lokal und offline ausfuehrbaren Vertraege ohne die
    langsamere Portal-Backend-Suite und ohne Portal-Produktionsbuild.

    Full ergaenzt alle vorhandenen Python-Suiten sowie Portal-Build und
    Renderingtests. Die Python-Suiten laufen bewusst in getrennten Prozessen,
    weil mehrere Dienste ein eigenes Paket `app` besitzen.

    Alle Checks werden soweit technisch moeglich unabhaengig ausgefuehrt.
    Die Zusammenfassung unterscheidet fachliche Testfehler von Setupfehlern,
    beispielsweise fehlenden Befehlen, Abhaengigkeiten oder `spawn EPERM`.

.PARAMETER Tier
    Fast oder Full. Standard ist Full.

.PARAMETER Python
    Interpreter mit den Abhaengigkeiten aus stack/requirements-dev.txt.
    Standard ist "python".

.PARAMETER Npm
    NPM-Kommando fuer Lint und Produktionsbuild.
    Standard ist "npm".

.PARAMETER Node
    Node-Kommando fuer die Renderingtests. Standard ist "node".

.EXAMPLE
    .\scripts\run-local-tests.ps1 -Tier Fast -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
    .\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd -Node node.exe
#>
[CmdletBinding()]
param(
    [ValidateSet("Fast", "Full")]
    [string]$Tier = "Full",
    [string]$Python = "python",
    [string]$Npm = "npm",
    [string]$Node = "node"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$script:results = @()

function Resolve-VerificationCommand {
    param([string]$Command)

    if (Test-Path -LiteralPath $Command -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Command).Path
    }
    return $Command
}

# Relative executable paths are supplied from the caller's current directory.
# Resolve them before individual checks switch into service directories.
$Python = Resolve-VerificationCommand $Python
$Npm = Resolve-VerificationCommand $Npm
$Node = Resolve-VerificationCommand $Node

function Add-CheckResult {
    param(
        [string]$Name,
        [string]$Path,
        [string]$Status,
        [object]$ExitCode,
        [string]$Detail
    )

    $script:results += [pscustomobject]@{
        Check    = $Name
        Pfad     = $Path
        Status   = $Status
        Exitcode = $ExitCode
        Detail   = $Detail
    }
}

function Test-IsSetupFailure {
    param(
        [string]$Kind,
        [string]$Output
    )

    $setupPatterns = @("spawn EPERM")
    if ($Kind -eq "Static") {
        $setupPatterns += "PyYAML is required for structured Compose verification"
    }
    if ($Kind -eq "Pytest") {
        $setupPatterns += @(
            "No module named pytest",
            "No module named 'pytest'",
            "No module named 'fastapi'",
            "No module named 'requests'",
            "No module named 'multipart'",
            "No module named 'docx'",
            "No module named 'pypdf'",
            "No module named 'httpx'",
            "No module named 'jwt'",
            "No module named 'cryptography'",
            "No module named 'reportlab'",
            "No module named 'watchdog'",
            "No module named 'yaml'",
            "No module named 'tzdata'"
        )
    }
    if ($Kind -in @("Npm", "Node")) {
        $setupPatterns += @(
            "not recognized as the name of a cmdlet",
            "is not recognized as an internal or external command",
            "command not found",
            "spawn ENOENT"
        )
    }
    foreach ($pattern in $setupPatterns) {
        if ($Output.IndexOf($pattern, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }
    return $false
}

function Invoke-VerificationCheck {
    param(
        [string]$Name,
        [string]$Path,
        [string]$WorkingDirectory,
        [string]$Command,
        [string[]]$Arguments,
        [ValidateSet("Pytest", "Static", "Npm", "Node")]
        [string]$Kind,
        [string[]]$PythonPath = @()
    )

    Write-Host ""
    Write-Host "=== $Name ($Path) ===" -ForegroundColor Cyan

    if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
        $detail = "Arbeitsverzeichnis fehlt: $WorkingDirectory"
        Write-Host "SETUPFEHLER: $detail" -ForegroundColor Yellow
        Add-CheckResult $Name $Path "SETUPFEHLER" "-" $detail
        return
    }

    $previousPythonPath = $env:PYTHONPATH
    $pushed = $false
    try {
        if ($PythonPath.Count -gt 0) {
            $resolvedPaths = @($PythonPath | ForEach-Object { Join-Path $repoRoot $_ })
            $env:PYTHONPATH = $resolvedPaths -join [IO.Path]::PathSeparator
        }
        else {
            $env:PYTHONPATH = $null
        }

        Push-Location $WorkingDirectory
        $pushed = $true

        try {
            Get-Command -Name $Command -ErrorAction Stop | Out-Null
        }
        catch {
            $detail = "Nicht ausfuehrbar: $($_.Exception.Message)"
            Write-Host "SETUPFEHLER: $detail" -ForegroundColor Yellow
            Add-CheckResult $Name $Path "SETUPFEHLER" "-" $detail
            return
        }

        $outputLines = New-Object System.Collections.Generic.List[string]
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            # Windows PowerShell 5.1 wandelt natives stderr bei "Stop" in eine
            # terminierende Ausnahme um. Der Exitcode bleibt die fuehrende
            # Evidenz; stderr wird trotzdem vollstaendig erfasst und angezeigt.
            $ErrorActionPreference = "Continue"
            & $Command @Arguments 2>&1 | ForEach-Object {
                $line = $_.ToString()
                [void]$outputLines.Add($line)
                Write-Host $line
            }
            $code = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        if ($code -eq 0) {
            Add-CheckResult $Name $Path "BESTANDEN" 0 ""
            return
        }

        $output = $outputLines -join [Environment]::NewLine
        if (Test-IsSetupFailure $Kind $output) {
            $status = "SETUPFEHLER"
            $detail = "Check konnte nicht regulaer ausgefuehrt werden."
            $color = "Yellow"
        }
        else {
            $status = "TESTFEHLER"
            $detail = "Check hat einen fachlichen oder technischen Fehler gemeldet."
            $color = "Red"
        }
        Write-Host "$status (Exitcode $code): $detail" -ForegroundColor $color
        Add-CheckResult $Name $Path $status $code $detail
    }
    catch {
        $detail = "Harness-Setupfehler: $($_.Exception.Message)"
        Write-Host "SETUPFEHLER: $detail" -ForegroundColor Yellow
        Add-CheckResult $Name $Path "SETUPFEHLER" "-" $detail
    }
    finally {
        if ($pushed) {
            Pop-Location
        }
        $env:PYTHONPATH = $previousPythonPath
    }
}

$staticChecks = @(
    @{
        Name = "Compose-Static"; Path = "stack/tests/compose_static_check.py"
        Arguments = @("stack/tests/compose_static_check.py"); Kind = "Static"
    },
    @{
        Name = "n8n-Workflow-Static"; Path = "stack/tests/n8n_workflow_static_check.py"
        Arguments = @("stack/tests/n8n_workflow_static_check.py"); Kind = "Static"
    },
    @{
        Name = "Open-WebUI-Tool-Bundle-Sync"; Path = "stack/open-webui-tools"
        Arguments = @("stack/open-webui-tools/build_tools.py", "--check"); Kind = "Static"
    }
)

foreach ($check in $staticChecks) {
    Invoke-VerificationCheck `
        -Name $check.Name `
        -Path $check.Path `
        -WorkingDirectory $repoRoot `
        -Command $Python `
        -Arguments $check.Arguments `
        -Kind $check.Kind
}

$pythonSuites = @(
    @{
        Name = "Portal-Backend"; Path = "stack/kb-admin-api/tests"; MinimumTier = "Full"
        WorkingDirectory = "stack/kb-admin-api"; Tests = "tests"; PythonPath = @()
    },
    @{
        Name = "Stack und Sicherheit"; Path = "stack/tests"; MinimumTier = "Fast"
        WorkingDirectory = "stack"; Tests = "tests"; PythonPath = @()
    },
    @{
        Name = "Hybridindex"; Path = "stack/kb-sync/tests"; MinimumTier = "Fast"
        WorkingDirectory = "stack/kb-sync"; Tests = "tests"; PythonPath = @()
    },
    @{
        Name = "RAG-Evaluation"; Path = "eval/rag/tests"; MinimumTier = "Fast"
        WorkingDirectory = "eval/rag"; Tests = "tests"; PythonPath = @("eval/rag", "stack/kb-sync")
    },
    @{
        Name = "Academy-Provisioner"; Path = "stack/academy-provisioner/tests"; MinimumTier = "Fast"
        WorkingDirectory = "stack/academy-provisioner"; Tests = "tests"; PythonPath = @()
    },
    @{
        Name = "Personio-Directory"; Path = "stack/personio-directory/tests"; MinimumTier = "Fast"
        WorkingDirectory = "."; Tests = "stack/personio-directory/tests"; PythonPath = @()
    }
)

foreach ($suite in $pythonSuites) {
    if ($suite.MinimumTier -eq "Full" -and $Tier -ne "Full") {
        continue
    }
    Invoke-VerificationCheck `
        -Name $suite.Name `
        -Path $suite.Path `
        -WorkingDirectory (Join-Path $repoRoot $suite.WorkingDirectory) `
        -Command $Python `
        -Arguments @("-m", "pytest", $suite.Tests, "-q", "-p", "no:cacheprovider") `
        -Kind "Pytest" `
        -PythonPath $suite.PythonPath
}

$dashboard = Join-Path $repoRoot "admin-dashboard"
Invoke-VerificationCheck `
    -Name "Portal-UI-Lint" `
    -Path "admin-dashboard" `
    -WorkingDirectory $dashboard `
    -Command $Npm `
    -Arguments @("run", "lint") `
    -Kind "Npm"

if ($Tier -eq "Full") {
    Invoke-VerificationCheck `
        -Name "Portal-UI-Build" `
        -Path "admin-dashboard" `
        -WorkingDirectory $dashboard `
        -Command $Npm `
        -Arguments @("run", "build") `
        -Kind "Npm"

    Invoke-VerificationCheck `
        -Name "Portal-UI-Renderingtests" `
        -Path "admin-dashboard/tests/rendered-html.test.mjs" `
        -WorkingDirectory $dashboard `
        -Command $Node `
        -Arguments @("tests/rendered-html.test.mjs") `
        -Kind "Node"
}

Write-Host ""
Write-Host "=== Gesamtergebnis: $Tier ===" -ForegroundColor Cyan
$script:results | Select-Object Check, Pfad, Status, Exitcode | Format-Table -AutoSize

$failedChecks = @($script:results | Where-Object { $_.Status -ne "BESTANDEN" })
if ($failedChecks.Count -gt 0) {
    Write-Host "Fehlerdetails:" -ForegroundColor Red
    foreach ($result in $failedChecks) {
        Write-Host "- $($result.Check) [$($result.Status)]: $($result.Detail)"
    }
    $testFailures = @($failedChecks | Where-Object { $_.Status -eq "TESTFEHLER" }).Count
    $setupFailures = @($failedChecks | Where-Object { $_.Status -eq "SETUPFEHLER" }).Count
    Write-Host "Verification fehlgeschlagen: $testFailures Testfehler, $setupFailures Setupfehler." -ForegroundColor Red
    exit 1
}

Write-Host "Alle fuer $Tier erforderlichen Checks bestanden." -ForegroundColor Green
exit 0
