$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/../handset/install_update.ps1"
$root = Join-Path ([IO.Path]::GetTempPath()) ('Pane-tests-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root) | Out-Null
$source = Join-Path $root 'source.exe'
$target = Join-Path $root 'Pane.exe'
[IO.File]::WriteAllText($source, 'new executable fixture')
[IO.File]::WriteAllText($target, 'old executable fixture')
$hash = (Get-FileHash $source).Hash
function Assert-Old { if ([IO.File]::ReadAllText($target) -ne 'old executable fixture') { throw 'Original executable was damaged.' } }
try {
    $failed = $false
    try { Install-PaneExecutable $source $target ('0' * 64) } catch { $failed = $true }
    if (-not $failed) { throw 'Bad checksum was accepted.' }
    Assert-Old
    $failed = $false
    try { Install-PaneExecutable $source $target $hash -WaitProcessId $PID -TimeoutSeconds 0 } catch { $failed = $true }
    if (-not $failed) { throw 'Live process wait did not time out.' }
    Assert-Old
    $fileLock = [IO.File]::Open($target, 'Open', 'Read', 'None')
    try {
        $failed = $false
        try { Install-PaneExecutable $source $target $hash } catch { $failed = $true }
        if (-not $failed) { throw 'Locked executable was replaced.' }
    } finally { $fileLock.Dispose() }
    Assert-Old
    $child = Start-Process powershell.exe -ArgumentList '-NoProfile -Command Start-Sleep -Seconds 2' -WindowStyle Hidden -PassThru
    $backup = Install-PaneExecutable $source $target $hash -WaitProcessId $child.Id -TimeoutSeconds 15
    if (-not $child.HasExited) { throw 'Replacement did not wait for process exit.' }
    if ([IO.File]::ReadAllText($backup) -ne 'old executable fixture') { throw 'Backup was not preserved.' }
    if ((Get-FileHash $target).Hash -ne $hash) { throw 'Replacement mismatch.' }
    $fresh = Join-Path $root 'fresh.exe'
    Install-PaneExecutable $source $fresh $hash | Out-Null
    if ((Get-FileHash $fresh).Hash -ne $hash) { throw 'Fresh install failed.' }
    Write-Host 'PASS: checksum rejection, timeout, locked-file failure, process exit wait, backup, replacement, fresh install.'
} finally {
    # All files are disposable direct children of this invocation's unique test directory.
    Get-ChildItem -LiteralPath $root -File | Remove-Item -Force
    [IO.Directory]::Delete($root)
}
