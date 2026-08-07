<#
.SYNOPSIS
    Stoppt den KAHLE-Vinci-Stack sauber.

.DESCRIPTION
    Gegenstueck zu start-stack.ps1. `docker compose down` interpoliert dieselben
    Variablen wie `up` und schlaegt ohne die Secrets fehl, deshalb werden sie
    hier genauso geladen und danach wieder aus der Sitzung entfernt.

    Volumes bleiben erhalten. Qdrant-Daten, OpenWebUI-Datenbank und Portal-
    Dateien ueberleben den Neustart also.

.PARAMETER RemoveOrphans
    Entfernt zusaetzlich Container, deren Dienst nicht mehr in der
    Compose-Datei steht. Nach dem Entfernen des lokalen Reranker-Dienstes ist
    das der Normalfall.

.EXAMPLE
    .\scripts\stop-stack.ps1
    .\scripts\stop-stack.ps1 -RemoveOrphans
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$Prefix = "KAHLE-Vinci",
    [switch]$RemoveOrphans,
    [switch]$NoEdge,
    [string[]]$ComposeArgs = @()
)

Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$secretsModule = Join-Path $PSScriptRoot "secrets\KvCredentialManager.psm1"
Import-Module $secretsModule -Force

$requiredSecrets = @(
    "IONOS_API_KEY",
    "WEBUI_SECRET_KEY",
    "N8N_BASIC_AUTH_PASSWORD",
    "N8N_ENCRYPTION_KEY",
    "SEARXNG_SECRET_KEY",
    "FILE_LINK_SECRET",
    "OWUI_FILE_PROXY_API_KEY",
    "DOC_WORKER_API_KEY"
)

# Zum Herunterfahren genuegt ein beliebiger Wert: Compose muss die Variablen nur
# aufloesen koennen. Fehlende Secrets sollen das Stoppen nicht blockieren.
foreach ($name in $requiredSecrets) {
    $value = Get-KvCredential -Name $name -Prefix $Prefix
    if ([string]::IsNullOrWhiteSpace($value)) { $value = "unused-for-shutdown" }
    Set-Item -Path "Env:$name" -Value $value
}

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("KAHLE_ROOT"))) {
    $env:KAHLE_ROOT = (Resolve-Path $ProjectRoot).Path.Replace("\", "/")
}

$composeFile = Join-Path $ProjectRoot "stack\docker-compose.yml"
$edgeFile = Join-Path $ProjectRoot "stack\docker-compose.local-edge.yml"

# Dieselben Dateien wie beim Start, sonst bleibt der Reverse Proxy stehen.
$composeFiles = @("compose", "-f", $composeFile)
if (-not $NoEdge) {
    $composeFiles += @("-f", $edgeFile)
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("ACME_EMAIL"))) {
        $env:ACME_EMAIL = "local@kahle.invalid"
    }
}

try {
    $downArgs = $composeFiles + @("down")
    if ($RemoveOrphans) { $downArgs += "--remove-orphans" }
    if ($ComposeArgs.Count -gt 0) { $downArgs += $ComposeArgs }

    & docker @downArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose down failed with exit code $LASTEXITCODE"
    }
    Write-Host "Stack gestoppt. Volumes und Daten sind erhalten." -ForegroundColor Green
}
finally {
    foreach ($name in $requiredSecrets) {
        Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    }
}
