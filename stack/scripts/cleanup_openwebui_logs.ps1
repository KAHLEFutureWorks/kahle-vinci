param(
    [Parameter(Mandatory = $false)]
    [string]$ContainerName = "open-webui",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 3650)]
    [int]$Days = 180,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun,

    [Parameter(Mandatory = $false)]
    [string]$ReportPath = "C:\kahle-vinci\stack\retention-reports\openwebui_log_cleanup_report.json",

    [Parameter(Mandatory = $false)]
    [string]$HelperImage = "alpine:3.20"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-JsonReport {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Report,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $reportDir = Split-Path -Parent $Path
    if ([string]::IsNullOrWhiteSpace($reportDir)) {
        throw "Invalid report directory: $Path"
    }
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    $json = $Report | ConvertTo-Json -Depth 8
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

$startedUtc = (Get-Date).ToUniversalTime()
$cutoffUtc = $startedUtc.AddDays(-$Days)

$containerId = $null
$logPath = $null
$helperLogPath = $null
$linesBefore = 0
$linesAfter = 0
$linesDeleted = 0
$parseErrors = 0
$sampleDeletedTimes = New-Object System.Collections.Generic.List[string]
$openWebuiRestarted = $false
$fileRewritten = $false
$tempFilteredPath = $null

try {
    $inspectRaw = docker inspect $ContainerName --format '{{json .}}'
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($inspectRaw)) {
        throw "docker inspect failed for container '$ContainerName'."
    }
    $inspect = $inspectRaw | ConvertFrom-Json
    $containerId = [string]$inspect.Id
    $logPath = [string]$inspect.LogPath
    if ([string]::IsNullOrWhiteSpace($containerId) -or [string]::IsNullOrWhiteSpace($logPath)) {
        throw "Could not resolve container id or LogPath."
    }

    $helperLogPath = "/containers/$containerId/$containerId-json.log"
    docker run --rm -v /var/lib/docker/containers:/containers:ro $HelperImage sh -lc "test -f '$helperLogPath'"
    if ($LASTEXITCODE -ne 0) {
        throw "Log file '$helperLogPath' is not accessible via helper container."
    }

    $reportDir = Split-Path -Parent $ReportPath
    if ([string]::IsNullOrWhiteSpace($reportDir)) {
        throw "Invalid report path: $ReportPath"
    }
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    $tempFilteredPath = Join-Path $reportDir ("openwebui_log_filtered_{0}.tmp" -f [Guid]::NewGuid().ToString("N"))

    $writer = $null
    if (-not $DryRun) {
        $writer = [System.IO.StreamWriter]::new($tempFilteredPath, $false, [System.Text.UTF8Encoding]::new($false))
    }

    try {
        docker run --rm -v /var/lib/docker/containers:/containers:ro $HelperImage sh -lc "cat '$helperLogPath'" | ForEach-Object {
            $line = [string]$_
            $linesBefore++
            $keep = $true

            if (-not [string]::IsNullOrWhiteSpace($line)) {
                try {
                    $entry = $line | ConvertFrom-Json -ErrorAction Stop
                    $rawTime = [string]$entry.time
                    if (-not [string]::IsNullOrWhiteSpace($rawTime)) {
                        $entryTime = [DateTimeOffset]::Parse(
                            $rawTime,
                            [System.Globalization.CultureInfo]::InvariantCulture,
                            [System.Globalization.DateTimeStyles]::AssumeUniversal
                        ).UtcDateTime
                        if ($entryTime -lt $cutoffUtc) {
                            $keep = $false
                            $linesDeleted++
                            if ($sampleDeletedTimes.Count -lt 10) {
                                $sampleDeletedTimes.Add($entryTime.ToString("o"))
                            }
                        }
                    }
                }
                catch {
                    $parseErrors++
                    $keep = $true
                }
            }

            if ($keep) {
                $linesAfter++
                if ($null -ne $writer) {
                    $writer.WriteLine($line)
                }
            }
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to stream the OWUI log file."
        }
    }
    finally {
        if ($null -ne $writer) {
            $writer.Dispose()
        }
    }

    if (-not $DryRun -and $linesDeleted -gt 0) {
        docker stop $ContainerName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to stop container '$ContainerName' before replacing log file."
        }
        try {
            $tempName = Split-Path -Leaf $tempFilteredPath
            docker run --rm `
                -v /var/lib/docker/containers:/containers `
                -v "${reportDir}:/host:ro" `
                $HelperImage sh -lc "cp '/host/$tempName' '$helperLogPath.tmp' && mv '$helperLogPath.tmp' '$helperLogPath'"
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to replace OWUI log file in docker containers directory."
            }
            $fileRewritten = $true
        }
        finally {
            docker start $ContainerName | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $openWebuiRestarted = $true
            }
        }
    }

    $report = @{
        last_run_at            = $startedUtc.ToString("o")
        success                = $true
        dry_run                = [bool]$DryRun
        container_name         = $ContainerName
        container_id           = $containerId
        log_path               = $logPath
        cutoff_days            = $Days
        cutoff_utc             = $cutoffUtc.ToString("o")
        lines_before           = $linesBefore
        lines_after            = $linesAfter
        lines_deleted          = $linesDeleted
        parse_errors           = $parseErrors
        sample_deleted_times   = @($sampleDeletedTimes.ToArray())
        open_webui_restarted   = $openWebuiRestarted
        file_rewritten         = $fileRewritten
        report_generated_at    = (Get-Date).ToUniversalTime().ToString("o")
    }
    Write-JsonReport -Report $report -Path $ReportPath
}
catch {
    $err = $_.Exception.Message
    $failure = @{
        last_run_at            = $startedUtc.ToString("o")
        success                = $false
        dry_run                = [bool]$DryRun
        container_name         = $ContainerName
        container_id           = $containerId
        log_path               = $logPath
        cutoff_days            = $Days
        cutoff_utc             = $cutoffUtc.ToString("o")
        lines_before           = $linesBefore
        lines_after            = $linesAfter
        lines_deleted          = $linesDeleted
        parse_errors           = $parseErrors
        open_webui_restarted   = $openWebuiRestarted
        file_rewritten         = $fileRewritten
        error                  = $err
        report_generated_at    = (Get-Date).ToUniversalTime().ToString("o")
    }
    Write-JsonReport -Report $failure -Path $ReportPath
    throw
}
finally {
    if ($tempFilteredPath -and (Test-Path -LiteralPath $tempFilteredPath)) {
        Remove-Item -LiteralPath $tempFilteredPath -Force -ErrorAction SilentlyContinue
    }
}
