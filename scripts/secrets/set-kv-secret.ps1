[CmdletBinding()]
param(
  [string[]]$Name,
  [switch]$All,
  [string]$Prefix = "KAHLE-Vinci"
)

Set-StrictMode -Version Latest

$modulePath = Join-Path $PSScriptRoot "KvCredentialManager.psm1"
Import-Module $modulePath -Force

$requiredNames = @(
  "IONOS_API_KEY",
  "WEBUI_SECRET_KEY",
  "N8N_BASIC_AUTH_PASSWORD",
  "N8N_ENCRYPTION_KEY",
  "SEARXNG_SECRET_KEY",
  "FILE_LINK_SECRET",
  "OWUI_FILE_PROXY_API_KEY",
  "DOC_WORKER_API_KEY"
)

if ($All -or -not $Name -or $Name.Count -eq 0) {
  $Name = $requiredNames
}

foreach ($entry in $Name) {
  if ($requiredNames -notcontains $entry) {
    throw "Unknown secret '$entry'. Allowed: $($requiredNames -join ', ')"
  }

  $secure = Read-Host "Enter value for $entry" -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($plain)) {
      throw "Secret '$entry' must not be empty."
    }
    Set-KvCredential -Name $entry -Secret $plain -Prefix $Prefix
    Write-Host "Stored $Prefix/$entry"
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}
