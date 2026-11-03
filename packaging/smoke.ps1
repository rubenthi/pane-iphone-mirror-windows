param([string]$Executable = "$PSScriptRoot/../dist/Pane.exe")
$ErrorActionPreference = 'Stop'
$report = Join-Path ([IO.Path]::GetTempPath()) ('Pane-smoke-' + [guid]::NewGuid().ToString('N') + '.json')
$process = Start-Process -FilePath $Executable -ArgumentList @('--smoke-test', ('"' + $report + '"')) -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(120000)) { Stop-Process -Id $process.Id; throw 'Packaged smoke check timed out.' }
if (-not (Test-Path $report)) { throw 'Packaged smoke check did not write a report.' }
$result = Get-Content $report -Raw | ConvertFrom-Json
if ($process.ExitCode -ne 0 -or -not $result.ok) { throw ($result | ConvertTo-Json -Depth 5) }
$result | ConvertTo-Json
Remove-Item -LiteralPath $report
