[CmdletBinding()]
param(
  [string]$ProjectRoot = "",
  [string]$Prefix = "KAHLE-Vinci",
  [switch]$Pull,
  [switch]$NoBuild,
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

foreach ($name in $requiredSecrets) {
  $value = Get-KvCredential -Name $name -Prefix $Prefix
  if ([string]::IsNullOrWhiteSpace($value)) {
    throw "Secret '$Prefix/$name' is empty. Run scripts/secrets/set-kv-secret.ps1 -Name $name first."
  }
  Set-Item -Path "Env:$name" -Value $value
}

$defaults = @{
  KAHLE_ROOT = (Resolve-Path $ProjectRoot).Path.Replace("\", "/")
  IONOS_OPENAI_BASE_URL = "https://openai.inference.de-txl.ionos.com/v1"
  IONOS_CHAT_MODEL_DEFAULT = "mistralai/Mistral-Small-24B-Instruct"
  IONOS_CHAT_MODEL_REASONING = "openai/gpt-oss-120b"
  IONOS_EMBEDDING_MODEL = "BAAI/bge-m3"
  PUBLIC_BASE_URL = "http://localhost:8091"
  N8N_SAFE_WEBSEARCH_WEBHOOK_URL = "http://n8n:5678/webhook/safe-websearch/h576htdr-5b9t-89r8-61wx-8a50bh988m6a"
  N8N_SAFE_WEBSEARCH_TIMEOUT = "50"
}

foreach ($item in $defaults.GetEnumerator()) {
  if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($item.Key))) {
    Set-Item -Path "Env:$($item.Key)" -Value $item.Value
  }
}

$composeFile = Join-Path $ProjectRoot "stack\docker-compose.yml"

try {
  if ($Pull) {
    & docker compose -f $composeFile pull
    if ($LASTEXITCODE -ne 0) {
      throw "docker compose pull failed with exit code $LASTEXITCODE"
    }
  }

  $upArgs = @("compose", "-f", $composeFile, "up", "-d")
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
} finally {
  foreach ($name in $requiredSecrets) {
    Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
  }
}
