# Run from a Windows checkout with the pinned Python and npm dependencies installed.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$previousPath = $env:Path
$previousTestPython = $env:PANE_TEST_PYTHON
Push-Location $root
function Run([string]$program, [string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "$program $arguments failed ($LASTEXITCODE)" }
}
try {
    if (!(Test-Path '.venv/Scripts/python.exe')) { throw 'Create .venv as described in docs/release-workflow.md.' }
    $receipt = Join-Path $root 'dist/local-verification.json'
    if (Test-Path $receipt) { Remove-Item -LiteralPath $receipt }
    $revision = git rev-parse HEAD
    if ($LASTEXITCODE) { throw 'Cannot identify the local commit.' }
    $before = git status --porcelain
    if ($LASTEXITCODE) { throw 'Cannot read the working tree.' }
    $env:Path = "$root\.venv\Scripts;$env:Path"
    $env:PANE_TEST_PYTHON = "$root\.venv\Scripts\python.exe"
    Run python @('-m','unittest','discover','-s','tests','-v')
    Get-ChildItem handset/web/*.js | ForEach-Object { Run node @('--check',$_.FullName) }
    Run npm.cmd @('test')
    foreach ($suite in 'setup','experience','companion-update','visual','native') {
        Run npm.cmd @('run',"test:$suite")
    }
    Run cargo @('fmt','--check','--manifest-path','native/Cargo.toml')
    Run cargo @('test','--locked','--manifest-path','native/Cargo.toml')
    Run powershell.exe @('-NoProfile','-ExecutionPolicy','Bypass','-File','tests/install_update.tests.ps1')
    & "$PSScriptRoot/build.ps1"
    $version = (Get-Item dist/Pane.exe).VersionInfo.ProductVersion
    Run python @('packaging/release_manifest.py','--tag',"v$version")
    & "$PSScriptRoot/smoke.ps1"
    $manifest = Get-Content dist/update.json -Raw | ConvertFrom-Json
    $exe = Get-Item dist/Pane.exe
    if ($exe.Length -ne $manifest.size -or (Get-FileHash $exe.FullName).Hash -ne $manifest.sha256) {
        throw 'Packaged executable and update manifest differ.'
    }
    $after = git status --porcelain
    if ($LASTEXITCODE) { throw 'Cannot read the working tree.' }
    if (!$before -and !$after -and (git rev-parse HEAD) -eq $revision) {
        $hashes = [ordered]@{}
        foreach ($asset in 'dist/Pane.exe','dist/update.json','dist/install.ps1','ios/Pane-unsigned.ipa') {
            $hashes[$asset] = (Get-FileHash -LiteralPath $asset).Hash
        }
        @{commit=$revision; tag="v$version"; hashes=$hashes} | ConvertTo-Json | Set-Content -Encoding UTF8 $receipt
    }
    Write-Host "Verified local Pane $version in $root\dist"
} finally {
    $env:Path = $previousPath
    $env:PANE_TEST_PYTHON = $previousTestPython
    Pop-Location
}
