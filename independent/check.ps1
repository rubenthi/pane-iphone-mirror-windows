[CmdletBinding()]
param([string]$PythonPath = '')

$ErrorActionPreference = 'Stop'
$prototypeRoot = $PSScriptRoot
$manifestPath = Join-Path $prototypeRoot 'native/Cargo.toml'
$lockPath = Join-Path $prototypeRoot 'native/Cargo.lock'
$toolsPath = Join-Path $prototypeRoot 'tools'
$reportPath = Join-Path $prototypeRoot 'native/target/license-audit.json'
$pythonPrefixArguments = @()
if (-not $PythonPath) {
    # Skip WindowsApps execution aliases, which can exist without Python installed.
    $pythonCommand = Get-Command py, python -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -and $_.Source -notmatch '\\WindowsApps\\' } |
        Select-Object -First 1
    if (-not $pythonCommand) {
        throw 'Python 3.12+ is required. Pass -PythonPath with the full path to a working Python interpreter.'
    }
    $PythonPath = $pythonCommand.Source
    if ($pythonCommand.Name -eq 'py.exe' -or $pythonCommand.Name -eq 'py') {
        $pythonPrefixArguments = @('-3.12')
    }
}

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Independent prototype manifest is missing: $manifestPath"
}
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw 'A committed Cargo.lock is required. This check never creates or updates the dependency lock.'
}

Write-Host 'Running isolated standard-library license-audit regression tests.'
& $PythonPath @pythonPrefixArguments -m unittest discover -s $toolsPath -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'License-audit regression tests failed.' }

Write-Host 'Auditing the locked all-features Cargo dependency graph.'
& $PythonPath @pythonPrefixArguments (Join-Path $toolsPath 'audit_licenses.py') --manifest-path $manifestPath --output $reportPath
if ($LASTEXITCODE -ne 0) { throw "Dependency license policy failed. Review $reportPath" }

Write-Host 'Checking the independent native prototype without launching it.'
& cargo fmt --check --manifest-path $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Independent native prototype formatting check failed.' }
& cargo check --locked --all-features --manifest-path $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Independent native prototype check failed.' }
& cargo test --locked --all-features --manifest-path $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Independent native prototype tests failed.' }
& cargo build --release --locked --all-features --manifest-path $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Independent native prototype release-mode build failed.' }

Write-Host "Development checks passed. Audit report: $reportPath"
Write-Host 'RELEASE BLOCKED: unreleased/root-license-pending; release is not authorized.'
Write-Host 'This automated dependency policy check is not legal certification.'
