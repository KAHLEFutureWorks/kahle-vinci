[CmdletBinding()]
param(
  [string]$EmployeeName = "Max Mustermann",
  [string]$EmployeeEmail = "mitarbeiter.schulung@kahle.de",
  [string]$EmployeePassword = "Vinci-Mitarbeiter-2026!",
  [string]$ManagerName = "Marta Musterfrau",
  [string]$ManagerEmail = "fuehrungskraft.schulung@kahle.de",
  [string]$ManagerPassword = "Vinci-Fuehrung-2026!"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$userHelper = Join-Path $projectRoot "scripts\openwebui\provision-local-training-users.py"
$portalHelper = Join-Path $projectRoot "scripts\openwebui\provision-local-training-portal.py"

foreach ($container in @("open-webui", "kb-admin-api")) {
  $running = & docker inspect -f "{{.State.Running}}" $container 2>$null
  if ($LASTEXITCODE -ne 0 -or $running -ne "true") {
    throw "Container '$container' is not running. Start the local stack first with scripts/start-stack.ps1."
  }
}

$portBinding = & docker port open-webui 8080/tcp 2>$null
if ($LASTEXITCODE -ne 0 -or $portBinding -notmatch "127\.0\.0\.1:3001") {
  throw "Safety stop: open-webui is not the expected local instance on 127.0.0.1:3001."
}

$userDockerArgs = @(
  "exec", "-i", "open-webui", "python", "-",
  $EmployeeName, $EmployeeEmail, $EmployeePassword,
  $ManagerName, $ManagerEmail, $ManagerPassword
)
$accountOutput = @(Get-Content -Raw -LiteralPath $userHelper | & docker @userDockerArgs)
if ($LASTEXITCODE -ne 0) {
  throw "The OpenWebUI training accounts could not be provisioned."
}
$accountJson = $accountOutput | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
if ([string]::IsNullOrWhiteSpace($accountJson)) {
  throw "OpenWebUI did not return the expected account data."
}
$accounts = $accountJson | ConvertFrom-Json

$portalDockerArgs = @(
  "exec", "-i", "kb-admin-api", "python", "-",
  $accounts.employee.id, $accounts.employee.email, $accounts.employee.name,
  $accounts.manager.id, $accounts.manager.email, $accounts.manager.name
)
Get-Content -Raw -LiteralPath $portalHelper | & docker @portalDockerArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "The Wissensportal roles could not be provisioned."
}

Write-Host "Local training accounts are ready:" -ForegroundColor Green
Write-Host "  Benutzer:      $EmployeeEmail / $EmployeePassword"
Write-Host "  Führungskraft: $ManagerEmail / $ManagerPassword"
Write-Host "  Login:         http://localhost:3001/auth"
Write-Host "Running the script again resets names, passwords, roles and portal permissions."
