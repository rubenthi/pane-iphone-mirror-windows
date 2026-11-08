# Builds dist\Pane.exe from the repository root.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
# Each invocation owns a fresh work directory. A previous sandbox or OneDrive
# sync can keep an old localpycs directory locked during PyInstaller --clean.
$buildWork = Join-Path ([IO.Path]::GetTempPath()) ('Pane-build-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($buildWork) | Out-Null

cargo build --release --locked --manifest-path "$root\signer\Cargo.toml"
if ($LASTEXITCODE -ne 0) { throw "Pane signing helper build failed" }
Copy-Item "$root\signer\target\release\pane-signer.exe" "$root\signer\pane-signer.exe" -Force

cargo build --release --locked --manifest-path "$root\native\Cargo.toml"
if ($LASTEXITCODE -ne 0) { throw "Pane Bluetooth helper build failed" }

python -m PyInstaller --noconfirm --clean `
  --distpath "$root\dist" `
  --workpath "$buildWork" `
  "$root\packaging\pane.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Host "Built $root\dist\Pane.exe"
