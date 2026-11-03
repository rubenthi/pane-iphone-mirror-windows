$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
dotnet publish "$root\native\Pane.Bluetooth\Pane.Bluetooth.csproj" -c Release -r win-x64 -o "$root\build\bluetooth"
if ($LASTEXITCODE -ne 0) { throw 'Bluetooth helper build failed' }
Copy-Item "$root\build\bluetooth\Pane.Bluetooth.exe" "$root\native\Pane.Bluetooth.exe" -Force
