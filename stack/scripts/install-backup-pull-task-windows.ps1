[CmdletBinding()]
param(
    [string]$SourceScript = "C:\kahle-vinci\stack\scripts\backup-pull-windows.ps1",
    [string]$TaskName = "KAHLE-Vinci Encrypted Backup Pull",
    [string]$DailyAt = "09:00"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SourceScript -PathType Leaf)) {
    throw "Das Backup-Pull-Skript wurde nicht gefunden: $SourceScript"
}

$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $SourceScript).Path,
    [ref]$null,
    [ref]$parseErrors
)

if ($parseErrors.Count -gt 0) {
    throw "Das Backup-Pull-Skript enthält PowerShell-Syntaxfehler."
}

$installDirectory = Join-Path $env:LOCALAPPDATA "KAHLE-Vinci\Scripts"
$installedScript = Join-Path $installDirectory "Pull-KahleVinciBackup.ps1"
$windowsPowerShell = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Copy-Item -LiteralPath $SourceScript -Destination $installedScript -Force

$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceScript).Hash
$installedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installedScript).Hash

if ($sourceHash -ne $installedHash) {
    throw "Die Prüfsumme des installierten Skripts stimmt nicht mit der Quelle überein."
}

$arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $installedScript
$action = New-ScheduledTaskAction -Execute $windowsPowerShell -Argument $arguments

$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId

$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($dailyTrigger, $logonTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Description "Pulls the latest encrypted KAHLE-Vinci server backup over restricted read-only SFTP and verifies SHA256." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host "Windows-Aufgabe erfolgreich eingerichtet." -ForegroundColor Green
Write-Host "Task:       $TaskName"
Write-Host "Benutzer:   $userId"
Write-Host "Skript:     $installedScript"
Write-Host "SHA256:     $installedHash"
Write-Host "Status:     $($task.State)"
Write-Host "Nächster:   $($taskInfo.NextRunTime)"
