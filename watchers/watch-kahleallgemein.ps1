# watch-kahleallgemein.ps1
# Watcht NUR C:\kahle-vinci\knowledgebases\kahleallgemein rekursiv und sendet Webhook Events an n8n.

$RootPath   = "C:\kahle-vinci\knowledgebases\kahleallgemein"
$Webhook    = "http://localhost:5678/webhook/kb/kahleallgemein/sync"
$DebounceMs = 1200

$allowedExt = @(".pdf",".docx",".csv",".txt",".json")

$lastEvent = @{}  # key -> last timestamp

function Should-Send($event, $path) {
  $ext = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
  if ($allowedExt -notcontains $ext) { return $false }

  $now = [DateTimeOffset]::Now
  $key = "$event|$path"

  if ($lastEvent.ContainsKey($key)) {
    $delta = ($now - $lastEvent[$key]).TotalMilliseconds
    if ($delta -lt $DebounceMs) { return $false }
  }
  $lastEvent[$key] = $now
  return $true
}

function Send-Event {
  param(
    [string]$event,
    [string]$fullPath,
    [string]$oldFullPath = ""
  )

  if ($event -ne "deleted" -and -not (Test-Path -LiteralPath $fullPath)) {
    # Datei noch gelockt/noch nicht da -> kurzer Retry (2x)
    Start-Sleep -Milliseconds 300
    if (-not (Test-Path -LiteralPath $fullPath)) {
      Start-Sleep -Milliseconds 700
      if (-not (Test-Path -LiteralPath $fullPath)) { return }
    }
  }

  if (-not (Should-Send $event $fullPath)) { return }

  $payload = @{
    event       = $event
    fullPath    = $fullPath
    oldFullPath = $oldFullPath
    ts          = ([DateTimeOffset]::Now).ToString("o")
  } | ConvertTo-Json -Depth 5

  try {
    Invoke-RestMethod -Method Post -Uri $Webhook -ContentType "application/json" -Body $payload | Out-Null
  } catch {
    Write-Host "Webhook failed: $event $fullPath => $($_.Exception.Message)"
  }
}

$fsw = New-Object System.IO.FileSystemWatcher
$fsw.Path = $RootPath
$fsw.IncludeSubdirectories = $true
$fsw.EnableRaisingEvents = $true
$fsw.NotifyFilter = [System.IO.NotifyFilters]'FileName, LastWrite, Size, DirectoryName'

Register-ObjectEvent $fsw Created -Action {
  Send-Event -event "created" -fullPath $Event.SourceEventArgs.FullPath
} | Out-Null

Register-ObjectEvent $fsw Changed -Action {
  Send-Event -event "changed" -fullPath $Event.SourceEventArgs.FullPath
} | Out-Null

Register-ObjectEvent $fsw Deleted -Action {
  # Deleted: Pfad existiert nicht mehr, trotzdem senden (Filter ext ist noch ok)
  Send-Event -event "deleted" -fullPath $Event.SourceEventArgs.FullPath
} | Out-Null

Register-ObjectEvent $fsw Renamed -Action {
  Send-Event -event "renamed" -fullPath $Event.SourceEventArgs.FullPath -oldFullPath $Event.SourceEventArgs.OldFullPath
} | Out-Null

Write-Host "Watching: $RootPath -> $Webhook"
while ($true) { Start-Sleep -Seconds 5 }
