function Install-PaneExecutable {
    param(
        [Parameter(Mandatory)][string]$SourcePath,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$Sha256,
        [int]$WaitProcessId = 0,
        [int]$TimeoutSeconds = 120
    )
    $ErrorActionPreference = 'Stop'
    if ($Sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid SHA-256.' }
    $source = [IO.Path]::GetFullPath($SourcePath)
    $target = [IO.Path]::GetFullPath($Destination)
    if ($source -eq $target) { throw 'Source and destination must differ.' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $Sha256) { throw 'Checksum mismatch; installation unchanged.' }
    $directory = Split-Path -Parent $target
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $stage = Join-Path $directory ('Pane-stage-' + [guid]::NewGuid().ToString('N') + '.exe')
    $backup = $target + '.backup-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
    $lockPath = Join-Path $directory '.install.lock'
    $lock = $null
    try {
        # FileShare.None also prevents two installers from replacing each other.
        $lock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
        Copy-Item -LiteralPath $source -Destination $stage
        if ((Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash -ne $Sha256) { throw 'Staged checksum mismatch.' }
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        do {
            $waiting = $WaitProcessId -gt 0 -and $null -ne (Get-Process -Id $WaitProcessId -ErrorAction SilentlyContinue)
            $running = @(Get-Process -Name Pane -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $target }).Count -gt 0
            if (-not ($waiting -or $running)) { break }
            if ([DateTime]::UtcNow -ge $deadline) { throw 'Pane did not exit before timeout; installation unchanged.' }
            Start-Sleep -Milliseconds 200
        } while ($true)
        if (Test-Path -LiteralPath $target) {
            [IO.File]::Replace($stage, $target, $backup)
        } else {
            [IO.File]::Move($stage, $target)
        }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $Sha256) {
            if (Test-Path -LiteralPath $backup) { [IO.File]::Copy($backup, $target, $true) }
            else { [IO.File]::Delete($target) }
            throw 'Installed checksum mismatch; previous installation restored.'
        }
        return $backup
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Force }
        if ($null -ne $lock) { $lock.Dispose() }
    }
}
