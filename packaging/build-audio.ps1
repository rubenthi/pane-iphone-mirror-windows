$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
dotnet publish "$root\native\Pane.Audio\Pane.Audio.csproj" -c Release -r win-x64 -o "$root\build\audio"
if ($LASTEXITCODE -ne 0) { throw 'Audio receiver build failed' }
Copy-Item "$root\build\audio\Pane.Audio.exe" "$root\native\Pane.Audio.exe" -Force
