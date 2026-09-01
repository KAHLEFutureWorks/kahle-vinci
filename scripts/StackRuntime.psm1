Set-StrictMode -Version Latest


function ConvertFrom-JsonDocument {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Lines
  )

  ($Lines -join [Environment]::NewLine) | ConvertFrom-Json
}


function Find-ForeignContainerNames {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [object[]]$Containers,
    [Parameter(Mandatory = $true)]
    [string]$ComposeProject
  )

  @(
    $Containers |
      Where-Object {
        -not [string]::IsNullOrWhiteSpace([string]$_.Name) -and
        [string]$_.Project -ne $ComposeProject
      } |
      ForEach-Object { [string]$_.Name } |
      Sort-Object -Unique
  )
}


function Get-ContainerComposeProject {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [object]$Container
  )

  $configProperty = $Container.PSObject.Properties["Config"]
  if ($null -eq $configProperty -or $null -eq $configProperty.Value) {
    return ""
  }
  $labelsProperty = $configProperty.Value.PSObject.Properties["Labels"]
  if ($null -eq $labelsProperty -or $null -eq $labelsProperty.Value) {
    return ""
  }
  $projectProperty = $labelsProperty.Value.PSObject.Properties["com.docker.compose.project"]
  if ($null -eq $projectProperty) {
    return ""
  }
  [string]$projectProperty.Value
}


function Select-RequiredRuntimeServices {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$AvailableServices
  )

  $requiredPortalPath = @(
    "open-webui",
    "kb-admin-api",
    "kb-sync",
    "qdrant",
    "personio-directory",
    "kb-admin-dashboard",
    "owui-file-proxy",
    "document-worker",
    "caddy-local"
  )
  @($requiredPortalPath | Where-Object { $_ -in $AvailableServices })
}


function Get-UnreadyRequiredServices {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [object[]]$Services,
    [Parameter(Mandatory = $true)]
    [string[]]$RequiredServices
  )

  $byName = @{}
  foreach ($service in $Services) {
    $name = [string]$service.Service
    if (-not [string]::IsNullOrWhiteSpace($name)) {
      $byName[$name] = $service
    }
  }

  @(
    foreach ($required in $RequiredServices) {
      if (-not $byName.ContainsKey($required)) {
        "$required (missing)"
        continue
      }
      $service = $byName[$required]
      $state = [string]$service.State
      if ($state -ne "running") {
        "$required (state=$state)"
        continue
      }
      $healthProperty = $service.PSObject.Properties["Health"]
      $health = if ($null -eq $healthProperty) { "" } else { [string]$healthProperty.Value }
      if (-not [string]::IsNullOrWhiteSpace($health) -and $health -ne "healthy") {
        "$required (health=$health)"
      }
    }
  )
}


Export-ModuleMember -Function `
  ConvertFrom-JsonDocument, `
  Find-ForeignContainerNames, `
  Get-ContainerComposeProject, `
  Select-RequiredRuntimeServices, `
  Get-UnreadyRequiredServices
