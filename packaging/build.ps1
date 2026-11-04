# Builds dist\Pane.exe from the repository root.
param([switch]$ReleaseReceiver)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($ReleaseReceiver) {
    python "$PSScriptRoot\release_receiver.py"
    if ($LASTEXITCODE -ne 0) { throw 'Release receiver verification failed.' }
} else {
    & "$PSScriptRoot\build-audio.ps1"
}

python -m PyInstaller --noconfirm --clean `
  --distpath "$root\dist" `
  --workpath "$root\build" `
  "$root\packaging\pane.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Host "Built $root\dist\Pane.exe"
