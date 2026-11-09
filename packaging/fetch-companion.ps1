# Restore the exact companion built by the checked macOS workflow.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$source = 'a5df3345e95d0639d9caf52df58f514f30a4fbeb'
$run = '42552614206'
$sha256 = '14364F40B322299AE3F0444AC5B732EB03EA3FC0ACC8AA4DB8184D65D8E1E5B7'
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
    # Both mirrors must match the same pinned digest. A transport failure or
    # an unpublished release can make the public download unavailable.
    try {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/rubenthi/pane-iphone-mirror-windows/releases/download/v2.5.8/Pane-unsigned.ipa' -OutFile $file
    } catch {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
        gh run download $run --repo rubenthi/pane-iphone-mirror-windows --name Pane-unsigned --dir $temp.FullName
        if ($LASTEXITCODE) { throw "Could not download the companion from run $run. Check gh authentication and artifact availability." }
    }
    if ((Get-FileHash -LiteralPath $file).Hash -ne $sha256) { throw 'Companion checksum mismatch.' }
    [IO.File]::Move($file, $destination)
} finally {
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    [IO.Directory]::Delete($temp.FullName)
}
