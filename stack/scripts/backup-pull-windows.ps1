[CmdletBinding()]
param(
    [string]$Server = "kvbackup@152.53.158.166",
    [string]$PrivateKey = "$env:USERPROFILE\.ssh\kahle-vinci-backup-pull",
    [string]$Destination = "$env:USERPROFILE\KAHLE-Vinci-Backups\automated",
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 21,
    [ValidateRange(1, 1024)]
    [int]$MinimumFreeGiB = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SftpExe = "$env:WINDIR\System32\OpenSSH\sftp.exe"
$LogDirectory = Join-Path $Destination "logs"
$LogFile = Join-Path $LogDirectory "backup-pull.log"
$PartialDirectory = $null
$Mutex = $null
$MutexAcquired = $false
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR")]
        [string]$Level = "INFO"
    )

    $line = "{0} level={1} {2}{3}" -f `
        (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK"), `
        $Level, `
        $Message, `
        [Environment]::NewLine

    [System.IO.File]::AppendAllText($LogFile, $line, $Utf8NoBom)
    Write-Host $line.TrimEnd()
}

function Convert-ToSftpPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $normalized = $Path.Replace("\", "/").Replace('"', '\"')
    return '"' + $normalized + '"'
}

function Invoke-SftpBatch {
    param([Parameter(Mandatory = $true)][string[]]$Commands)

    $batchFile = Join-Path $env:TEMP ("kahle-vinci-sftp-{0}.txt" -f [guid]::NewGuid().ToString("N"))

    try {
        [System.IO.File]::WriteAllLines($batchFile, $Commands, [System.Text.Encoding]::ASCII)

        $output = & $SftpExe `
            -q `
            -b $batchFile `
            -i $PrivateKey `
            -o IdentitiesOnly=yes `
            -o BatchMode=yes `
            -o StrictHostKeyChecking=yes `
            -o ConnectTimeout=20 `
            $Server 2>&1

        $exitCode = $LASTEXITCODE

        foreach ($line in @($output)) {
            if ($null -ne $line -and -not [string]::IsNullOrWhiteSpace($line.ToString())) {
                Write-Log -Message ("sftp: {0}" -f $line.ToString().Trim())
            }
        }

        if ($exitCode -ne 0) {
            throw "SFTP wurde mit Exitcode $exitCode beendet."
        }

        return @($output)
    }
    finally {
        Remove-Item -LiteralPath $batchFile -Force -ErrorAction SilentlyContinue
    }
}

function Remove-ExpiredBackups {
    param([Parameter(Mandatory = $true)][string]$ProtectedBackupName)

    $cutoff = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)

    Get-ChildItem -LiteralPath $Destination -File -Filter "kahle-vinci-*.tar.age" |
        Where-Object {
            $_.Name -ne $ProtectedBackupName -and
            $_.LastWriteTimeUtc -lt $cutoff
        } |
        ForEach-Object {
            $hashPath = "$($_.FullName).sha256"
            Write-Log -Message ("Entferne abgelaufenes lokales Backup: {0}" -f $_.Name)
            Remove-Item -LiteralPath $_.FullName -Force
            Remove-Item -LiteralPath $hashPath -Force -ErrorAction SilentlyContinue
        }

    Get-ChildItem -LiteralPath $Destination -File -Filter "kahle-vinci-*.tar.age.sha256" |
        Where-Object {
            $_.LastWriteTimeUtc -lt $cutoff -and
            -not (Test-Path -LiteralPath $_.FullName.Substring(0, $_.FullName.Length - 7))
        } |
        ForEach-Object {
            Write-Log -Message ("Entferne verwaiste Prüfsumme: {0}" -f $_.Name)
            Remove-Item -LiteralPath $_.FullName -Force
        }
}

New-Item -ItemType Directory -Path $Destination -Force | Out-Null
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

if (Test-Path -LiteralPath $LogFile) {
    $logInfo = Get-Item -LiteralPath $LogFile
    if ($logInfo.Length -gt 5MB) {
        Move-Item -LiteralPath $LogFile -Destination "$LogFile.1" -Force
    }
}

$Mutex = New-Object System.Threading.Mutex($false, "Local\KAHLE-Vinci-Backup-Pull")

try {
    try {
        $MutexAcquired = $Mutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $MutexAcquired = $true
    }

    if (-not $MutexAcquired) {
        Write-Log -Message "Ein anderer Backup-Pull läuft bereits; dieser Lauf wird beendet." -Level WARN
        exit 0
    }

    Write-Log -Message "Backup-Pull gestartet."

    foreach ($requiredFile in @($SftpExe, $PrivateKey)) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "Erforderliche Datei fehlt: $requiredFile"
        }
    }

    $destinationRoot = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $Destination).Path)
    $driveName = $destinationRoot.TrimEnd("\").TrimEnd(":")
    $drive = Get-PSDrive -Name $driveName
    $minimumFreeBytes = [int64]$MinimumFreeGiB * 1GB

    if ($drive.Free -lt $minimumFreeBytes) {
        throw "Zu wenig freier Speicher auf $destinationRoot. Verfügbar: $([math]::Round($drive.Free / 1GB, 2)) GiB."
    }

    Get-ChildItem -LiteralPath $Destination -Directory -Filter ".partial-*" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTimeUtc -lt (Get-Date).ToUniversalTime().AddDays(-2) } |
        Remove-Item -Recurse -Force

    $listing = Invoke-SftpBatch -Commands @(
        "ls -1 kahle-vinci-*.tar.age",
        "quit"
    )

    $namePattern = [regex]'(?:^|/)(kahle-vinci-\d{8}-\d{6}\.tar\.age)$'
    $backupNames = New-Object System.Collections.Generic.List[string]

    foreach ($line in @($listing)) {
        if ($null -eq $line) {
            continue
        }

        $match = $namePattern.Match($line.ToString().Trim())
        if ($match.Success) {
            $backupNames.Add($match.Groups[1].Value)
        }
    }

    $latestBackup = $backupNames |
        Sort-Object -Unique |
        Select-Object -Last 1

    if ([string]::IsNullOrWhiteSpace($latestBackup)) {
        throw "Auf dem Server wurde kein verschlüsseltes Backup gefunden."
    }

    Write-Log -Message "Neuestes Server-Backup: $latestBackup"

    $PartialDirectory = Join-Path $Destination (".partial-{0}" -f [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $PartialDirectory | Out-Null

    $temporaryHash = Join-Path $PartialDirectory "$latestBackup.sha256"
    $finalBackup = Join-Path $Destination $latestBackup
    $finalHash = "$finalBackup.sha256"

    Invoke-SftpBatch -Commands @(
        ("get {0} {1}" -f "$latestBackup.sha256", (Convert-ToSftpPath $temporaryHash)),
        "quit"
    ) | Out-Null

    $hashText = (Get-Content -Raw -LiteralPath $temporaryHash).Trim()
    $hashPattern = [regex]'^(?<hash>[0-9a-fA-F]{64})\s+\*?(?<name>[^\s]+)$'
    $hashMatch = $hashPattern.Match($hashText)

    if (-not $hashMatch.Success) {
        throw "Die heruntergeladene SHA256-Datei hat ein ungültiges Format."
    }

    $expectedHash = $hashMatch.Groups["hash"].Value.ToLowerInvariant()
    $manifestName = [System.IO.Path]::GetFileName($hashMatch.Groups["name"].Value)

    if ($manifestName -ne $latestBackup) {
        throw "Die SHA256-Datei gehört nicht zum erwarteten Backup."
    }

    if (Test-Path -LiteralPath $finalBackup -PathType Leaf) {
        $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $finalBackup).Hash.ToLowerInvariant()

        if ($existingHash -eq $expectedHash) {
            Move-Item -LiteralPath $temporaryHash -Destination $finalHash -Force
            Remove-ExpiredBackups -ProtectedBackupName $latestBackup
            Write-Log -Message "Das neueste Backup liegt bereits vollständig und geprüft vor."
            exit 0
        }

        Write-Log -Message "Vorhandene lokale Datei hat eine abweichende Prüfsumme und wird ersetzt." -Level WARN
    }

    $temporaryBackup = Join-Path $PartialDirectory $latestBackup

    Invoke-SftpBatch -Commands @(
        ("get {0} {1}" -f $latestBackup, (Convert-ToSftpPath $temporaryBackup)),
        "quit"
    ) | Out-Null

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporaryBackup).Hash.ToLowerInvariant()

    if ($actualHash -ne $expectedHash) {
        throw "SHA256-Prüfung fehlgeschlagen. Erwartet: $expectedHash; tatsächlich: $actualHash"
    }

    Move-Item -LiteralPath $temporaryBackup -Destination $finalBackup -Force
    Move-Item -LiteralPath $temporaryHash -Destination $finalHash -Force

    Remove-ExpiredBackups -ProtectedBackupName $latestBackup

    $sizeMiB = [math]::Round((Get-Item -LiteralPath $finalBackup).Length / 1MB, 2)
    Write-Log -Message "Backup erfolgreich übernommen und geprüft: $latestBackup; SHA256=$actualHash; GrößeMiB=$sizeMiB"
}
catch {
    Write-Log -Message $_.Exception.Message -Level ERROR
    throw
}
finally {
    if ($null -ne $PartialDirectory -and (Test-Path -LiteralPath $PartialDirectory)) {
        Remove-Item -LiteralPath $PartialDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($null -ne $Mutex) {
        if ($MutexAcquired) {
            $Mutex.ReleaseMutex()
        }
        $Mutex.Dispose()
    }
}
