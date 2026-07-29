[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$OutputPath,
  [string]$Prefix = "KAHLE-Vinci"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$modulePath = Join-Path $PSScriptRoot "KvCredentialManager.psm1"
Import-Module $modulePath -Force

if (Test-Path -LiteralPath $OutputPath) {
  throw "Refusing to overwrite existing secret file: $OutputPath"
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

function ConvertTo-DotEnvValue {
  param([Parameter(Mandatory = $true)][string]$Value)

  if ($Value.Contains("`r") -or $Value.Contains("`n")) {
    throw "Multiline secrets are not supported."
  }

  $escaped = $Value.Replace("\", "\\").Replace("'", "\'")
  return "'$escaped'"
}

function New-RandomSecret {
  param([int]$Bytes = 48)

  $buffer = New-Object byte[] $Bytes
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($buffer)
  } finally {
    $rng.Dispose()
  }
  return [Convert]::ToBase64String($buffer)
}

$values = [ordered]@{
  KAHLE_ROOT = "/opt/kahle-vinci"
  PUBLIC_HOSTNAME = "vinci.kahle.de"
  WEBUI_URL = "https://vinci.kahle.de"
  ACME_EMAIL = "<pending-it-contact>"
  IONOS_OPENAI_BASE_URL = "https://openai.inference.de-txl.ionos.com/v1"
  IONOS_CHAT_MODEL_DEFAULT = "mistralai/Mistral-Small-24B-Instruct"
  IONOS_CHAT_MODEL_REASONING = "openai/gpt-oss-120b"
  IONOS_EMBEDDING_MODEL = "BAAI/bge-m3"
  OAUTH_ALLOWED_DOMAINS = "kahle.de"
  OPENID_PROVIDER_URL = "<pending-tenant-id>"
  MICROSOFT_CLIENT_ID = "<pending-client-id>"
  MICROSOFT_CLIENT_SECRET = "<pending-client-secret>"
  MICROSOFT_CLIENT_TENANT_ID = "<pending-tenant-id>"
  MICROSOFT_REDIRECT_URI = "https://vinci.kahle.de/oauth/microsoft/callback"
  MICROSOFT_OAUTH_SCOPE = "openid email profile"
  DEFAULT_USER_ROLE = "pending"
  ENABLE_LOGIN_FORM = "False"
  ENABLE_PASSWORD_AUTH = "False"
}

foreach ($name in $requiredSecrets) {
  $secret = Get-KvCredential -Name $name -Prefix $Prefix
  if ([string]::IsNullOrWhiteSpace($secret)) {
    throw "Secret '$Prefix/$name' is missing or empty."
  }
  $values[$name] = $secret
}

$values["OAUTH_SESSION_TOKEN_ENCRYPTION_KEY"] = New-RandomSecret
$values["OAUTH_CLIENT_INFO_ENCRYPTION_KEY"] = New-RandomSecret

$outputDirectory = Split-Path -Parent $OutputPath
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
  New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

$lines = foreach ($entry in $values.GetEnumerator()) {
  if ($entry.Key -in @("KAHLE_ROOT", "PUBLIC_HOSTNAME", "WEBUI_URL", "IONOS_OPENAI_BASE_URL", "IONOS_CHAT_MODEL_DEFAULT", "IONOS_CHAT_MODEL_REASONING", "IONOS_EMBEDDING_MODEL", "OAUTH_ALLOWED_DOMAINS", "MICROSOFT_REDIRECT_URI", "MICROSOFT_OAUTH_SCOPE", "DEFAULT_USER_ROLE", "ENABLE_LOGIN_FORM", "ENABLE_PASSWORD_AUTH")) {
    "$($entry.Key)=$($entry.Value)"
  } else {
    "$($entry.Key)=$(ConvertTo-DotEnvValue -Value ([string]$entry.Value))"
  }
}

[IO.File]::WriteAllLines($OutputPath, $lines, [Text.UTF8Encoding]::new($false))

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $OutputPath /inheritance:r /grant:r "${identity}:(R,W)" | Out-Null
if ($LASTEXITCODE -ne 0) {
  Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
  throw "Could not restrict access to the generated secret file."
}

Write-Host "Created protected server environment file: $OutputPath"
Write-Host "Microsoft Entra values are intentionally marked as pending."
