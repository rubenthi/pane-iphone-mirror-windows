# Builds dist\Pane.exe from the repository root.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& "$root\packaging\build-bluetooth.ps1"

python -m PyInstaller --noconfirm --clean `
  --distpath "$root\dist" `
  --workpath "$root\build" `
  "$root\packaging\pane.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Host "Built $root\dist\Pane.exe"
