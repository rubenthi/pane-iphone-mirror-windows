# Restore the exact companion built by the checked macOS workflow.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$source = 'e0b174a9791194b7f9079961efdbcf15d28516f6'
$run = '42528253999'
$sha256 = 'EEE4338F3703850D0AD496D01E28747AC4F5AA49657447DFA4A6EA3B455CBC75'
$destination = Join-Path $root 'ios/Pane-unsigned.ipa'
git -C $root diff --quiet $source -- ios ':(exclude,icase)ios/*.md' handset/companion_version.py
if ($LASTEXITCODE -ne 0) { throw "The companion sources differ from $source. Build the changed iOS source with the companion workflow." }
$newFiles = git -C $root ls-files --others --exclude-standard -- ios ':(exclude,icase)ios/*.md'
if ($LASTEXITCODE -ne 0 -or $newFiles) { throw 'Review untracked iOS source before restoring the companion.' }
if (Test-Path -LiteralPath $destination) {
    if ((Get-FileHash -LiteralPath $destination).Hash -eq $sha256) { return }
    throw 'A different IPA already exists. Review it before replacing it.'
}
$temp = New-Item -ItemType Directory -Path (Join-Path $root "ios/.restore-$([guid]::NewGuid())")
$file = Join-Path $temp.FullName 'Pane-unsigned.ipa'
try {
    # Once published, prefer the durable release asset. Only a missing release
    # falls back to the exact CI artifact. Both must match the same digest.
    try {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/rubenthi/pane-iphone-mirror-windows/releases/download/v2.5.7/Pane-unsigned.ipa' -OutFile $file
    } catch {
        if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 404) { throw }
        gh run download $run --repo rubenthi/pane-iphone-mirror-windows --name Pane-unsigned --dir $temp.FullName
        if ($LASTEXITCODE) { throw "Could not download the companion from run $run. Check gh authentication and artifact availability." }
    }
    if ((Get-FileHash -LiteralPath $file).Hash -ne $sha256) { throw 'Companion checksum mismatch.' }
    [IO.File]::Move($file, $destination)
} finally {
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    [IO.Directory]::Delete($temp.FullName)
}
