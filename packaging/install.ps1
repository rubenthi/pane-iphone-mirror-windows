param(
    [string]$Version = 'latest',
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\Pane'),
    [switch]$NoLaunch,
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
. "$PSScriptRoot/../handset/install_update.ps1"
$releaseRoot = 'https://github.com/rubenthi/pane-iphone-mirror-windows/releases'
if ($Version -eq 'latest') { $manifestUrl = "$releaseRoot/latest/download/update.json" }
elseif ($Version -match '^\d+\.\d+\.\d+$') { $manifestUrl = "$releaseRoot/download/v$Version/update.json" }
else { throw 'Version must be latest or major.minor.patch.' }
$manifest = Invoke-RestMethod -Uri $manifestUrl
if ($manifest.version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid manifest version.' }
if ($Version -ne 'latest' -and $manifest.version -ne $Version) { throw 'Manifest version mismatch.' }
$expectedUrl = "$releaseRoot/download/v$($manifest.version)/Pane.exe"
if ($manifest.url -cne $expectedUrl -or $manifest.sha256 -notmatch '^[a-f0-9]{64}$' -or $manifest.size -le 0) { throw 'Invalid release manifest.' }
$tempDirectory = Join-Path ([IO.Path]::GetTempPath()) ('Pane-install-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($tempDirectory) | Out-Null
try {
    $download = Join-Path $tempDirectory 'Pane.exe'
    Invoke-WebRequest -UseBasicParsing -Uri $expectedUrl -OutFile $download
    if ((Get-Item -LiteralPath $download).Length -ne $manifest.size) { throw 'Download size mismatch.' }
    if ((Get-Item -LiteralPath $download).VersionInfo.ProductVersion -ne $manifest.version) { throw 'Executable version mismatch.' }
    $target = Join-Path $InstallDirectory 'Pane.exe'
    $backup = Install-PaneExecutable -SourcePath $download -Destination $target -Sha256 $manifest.sha256
    if (-not $NoShortcut) {
        $shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Pane.lnk'
        if (Test-Path -LiteralPath $shortcutPath) { Copy-Item -LiteralPath $shortcutPath -Destination ($shortcutPath + '.backup-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')) }
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $target
        $shortcut.WorkingDirectory = $InstallDirectory
        $shortcut.IconLocation = "$target,0"
        $shortcut.Save()
    }
    Write-Host "Installed Pane $($manifest.version): $target"
    if (Test-Path -LiteralPath $backup) { Write-Host "Rollback executable: $backup" }
    if (-not $NoLaunch) { Start-Process -FilePath $target -WindowStyle Hidden }
} finally {
    # Only delete files created by this invocation, never a recursive directory.
    if (Test-Path -LiteralPath (Join-Path $tempDirectory 'Pane.exe')) { Remove-Item -LiteralPath (Join-Path $tempDirectory 'Pane.exe') }
    [IO.Directory]::Delete($tempDirectory)
}
