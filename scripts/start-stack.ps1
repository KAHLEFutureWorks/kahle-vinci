[CmdletBinding()]
param(
  [string]$ProjectRoot = "",
  [string]$Prefix = "KAHLE-Vinci",
  [switch]$Pull,
  [switch]$NoBuild,
  [switch]$NoEdge,
  [string[]]$ComposeArgs = @()
)

Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
  $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$secretsModule = Join-Path $PSScriptRoot "secrets\KvCredentialManager.psm1"
Import-Module $secretsModule -Force
$runtimeModule = Join-Path $PSScriptRoot "StackRuntime.psm1"
Import-Module $runtimeModule -Force

# A user-scoped token added after Codex/PowerShell was started is not present in
# the inherited process environment. Import it explicitly so Compose can prefer
# the current token over the legacy IONOS_API_KEY credential.
$importedIonosApiToken = $false
if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("IONOS_API_TOKEN"))) {
  $userIonosApiToken = [Environment]::GetEnvironmentVariable("IONOS_API_TOKEN", "User")
  if (-not [string]::IsNullOrWhiteSpace($userIonosApiToken)) {
    Set-Item -Path "Env:IONOS_API_TOKEN" -Value $userIonosApiToken
    $importedIonosApiToken = $true
  }
}

# Personio credentials are intentionally stored as user-scoped environment
# variables instead of in repository files or the generic credential store.
# A long-running Codex/PowerShell process may not have inherited them yet.
$importedPersonioVariables = @()
foreach ($name in @("PERSONIO_CLIENT_ID", "PERSONIO_API")) {
  if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
    $userValue = [Environment]::GetEnvironmentVariable($name, "User")
    if (-not [string]::IsNullOrWhiteSpace($userValue)) {
      Set-Item -Path "Env:$name" -Value $userValue
      $importedPersonioVariables += $name
    }
  }
}

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

foreach ($name in $requiredSecrets) {
  $value = Get-KvCredential -Name $name -Prefix $Prefix
  if ([string]::IsNullOrWhiteSpace($value)) {
    throw "Secret '$Prefix/$name' is empty. Run scripts/secrets/set-kv-secret.ps1 -Name $name first."
  }
  Set-Item -Path "Env:$name" -Value $value
}

$defaults = @{
  KAHLE_ROOT = (Resolve-Path $ProjectRoot).Path.Replace("\", "/")
  KAHLE_LOCAL_CODE_ROOT = (Resolve-Path $ProjectRoot).Path.Replace("\", "/")
  IONOS_OPENAI_BASE_URL = "https://openai.inference.de-txl.ionos.com/v1"
  IONOS_CHAT_MODEL_DEFAULT = "mistralai/Mistral-Small-24B-Instruct"
  IONOS_CHAT_MODEL_REASONING = "openai/gpt-oss-120b"
  IONOS_EMBEDDING_MODEL = "BAAI/bge-m3"
  PUBLIC_BASE_URL = "http://localhost:8091"
  N8N_SAFE_WEBSEARCH_WEBHOOK_URL = "http://n8n:5678/webhook/safe-websearch/h576htdr-5b9t-89r8-61wx-8a50bh988m6a"
  N8N_SAFE_WEBSEARCH_TIMEOUT = "50"
  # Compose interpoliert auch Dienste, die lokal ueber ein Profil deaktiviert
  # sind. Diese Werte verhindern lokale Produktionszugriffe und werden vom
  # Academy-Provisioner nicht verwendet.
  LEARNINGSUITE_API_KEY = "local-disabled"
  LEARNINGSUITE_ALLOWED_EMAILS = "local-disabled"
  MICROSOFT_CLIENT_TENANT_ID = "local-disabled"
  MICROSOFT_CLIENT_ID = "local-disabled"
  MICROSOFT_CLIENT_SECRET = "local-disabled"
}

foreach ($item in $defaults.GetEnumerator()) {
  if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($item.Key))) {
    Set-Item -Path "Env:$($item.Key)" -Value $item.Value
  }
}

$composeFile = Join-Path $ProjectRoot "stack\docker-compose.yml"
$uiFile = Join-Path $ProjectRoot "stack\docker-compose.kahle-ui.yml"
if (-not (Test-Path -LiteralPath $uiFile)) {
  throw "KAHLE OpenWebUI UI overlay is missing: $uiFile"
}

# Caddy ist nur fuer die Produktion definiert. Ohne dieses Overlay gibt es
# lokal keinen Reverse Proxy und /wissen/ ist nicht erreichbar.
$edgeFile = Join-Path $ProjectRoot "stack\docker-compose.local-edge.yml"
$composeProject = Get-LocalComposeProjectName -ComposeFile $composeFile
$composeFiles = @(
  "compose", "--project-name", $composeProject,
  "-f", $composeFile,
  "-f", $uiFile
)
if (-not $NoEdge) {
  $composeFiles += @("-f", $edgeFile)
  if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("ACME_EMAIL"))) {
    $env:ACME_EMAIL = "local@kahle.invalid"
  }
}

try {
  $composeConfigJson = & docker @composeFiles config --format json
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose config failed with exit code $LASTEXITCODE"
  }
  $composeConfig = ConvertFrom-JsonDocument -Lines $composeConfigJson
  $expectedContainerNames = @(
    $composeConfig.services.PSObject.Properties |
      ForEach-Object { [string]$_.Value.container_name } |
      Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  )
  $existingContainers = @(
    foreach ($containerName in $expectedContainerNames) {
      $inspectJson = & docker inspect $containerName 2>$null
      if ($LASTEXITCODE -ne 0) {
        continue
      }
      $container = @(ConvertFrom-JsonDocument -Lines $inspectJson)[0]
      [PSCustomObject]@{
        Name = $containerName
        Project = Get-ContainerComposeProject -Container $container
      }
    }
  )
  $foreignContainers = @()
  if ($existingContainers.Count -gt 0) {
    $foreignContainers = @(
      Find-ForeignContainerNames `
        -Containers $existingContainers `
        -ComposeProject $composeProject
    )
  }
  if ($foreignContainers.Count -gt 0) {
    throw (
      "Container name conflict before Compose start: " +
      ($foreignContainers -join ", ") +
      ". Remove or rename these foreign containers explicitly, then rerun. " +
      "No containers were changed."
    )
  }

  if ($Pull) {
    & docker @composeFiles pull --ignore-buildable
    if ($LASTEXITCODE -ne 0) {
      throw "docker compose pull failed with exit code $LASTEXITCODE"
    }
  }

  $upArgs = $composeFiles + @("up", "-d")
  if (-not $NoBuild) {
    $upArgs += "--build"
  }
  if ($ComposeArgs.Count -gt 0) {
    $upArgs += $ComposeArgs
  }

  & docker @upArgs
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed with exit code $LASTEXITCODE"
  }

  $availableRuntimeServices = @(
    $composeConfig.services.PSObject.Properties | ForEach-Object { $_.Name }
  )
  $requiredRuntimeServices = @(
    Select-RequiredRuntimeServices -AvailableServices $availableRuntimeServices
  )
  $unreadyServices = @("runtime status not checked")
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $serviceStatusJson = & docker @composeFiles ps --format json
    if ($LASTEXITCODE -ne 0) {
      throw "docker compose ps failed with exit code $LASTEXITCODE"
    }
    $serviceStatus = @(
      $serviceStatusJson |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_ | ConvertFrom-Json }
    )
    $unreadyServices = @(
      Get-UnreadyRequiredServices `
        -Services $serviceStatus `
        -RequiredServices $requiredRuntimeServices
    )
    if ($unreadyServices.Count -eq 0) {
      break
    }
    Start-Sleep -Seconds 2
  }
  if ($unreadyServices.Count -gt 0) {
    throw (
      "Local stack started incompletely. Required services not ready: " +
      ($unreadyServices -join ", ")
    )
  }
} finally {
  foreach ($name in $requiredSecrets) {
    Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
  }
  foreach ($name in @(
    "LEARNINGSUITE_API_KEY",
    "LEARNINGSUITE_ALLOWED_EMAILS",
    "MICROSOFT_CLIENT_TENANT_ID",
    "MICROSOFT_CLIENT_ID",
    "MICROSOFT_CLIENT_SECRET"
  )) {
    if ([Environment]::GetEnvironmentVariable($name) -eq "local-disabled") {
      Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    }
  }
  if ($importedIonosApiToken) {
    Remove-Item -Path "Env:IONOS_API_TOKEN" -ErrorAction SilentlyContinue
  }
  foreach ($name in $importedPersonioVariables) {
    Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
  }
}
