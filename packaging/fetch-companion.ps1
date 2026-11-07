# Restore the matching, previously released iOS binary on a Windows checkout.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tag = 'v2.3.1'
$sha256 = '79c1f7aad36688cc9eba5eb65f24c41cb48dbd332239923f10a9a858b68e4618'
$destination = Join-Path $root 'ios/Pane-unsigned.ipa'
git -C $root diff --quiet $tag -- ios ':(exclude,icase)ios/*.md' handset/companion_version.py
if ($LASTEXITCODE -ne 0) { throw "Cannot reuse the $tag companion. Check the tag and build changed iOS source with Xcode." }
$newFiles = git -C $root ls-files --others --exclude-standard -- ios ':(exclude,icase)ios/*.md'
if ($LASTEXITCODE -ne 0 -or $newFiles) { throw 'Review untracked iOS source before restoring the released companion.' }
if (Test-Path -LiteralPath $destination) {
    if ((Get-FileHash -LiteralPath $destination).Hash -eq $sha256) { return }
    throw 'A different IPA already exists. Review it before replacing it.'
}
$temp = "$destination.$([guid]::NewGuid()).tmp"
try {
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/rubenthi/pane-iphone-mirror-windows/releases/download/$tag/Pane-unsigned.ipa" -OutFile $temp
    if ((Get-FileHash -LiteralPath $temp).Hash -ne $sha256) { throw 'Companion checksum mismatch.' }
    [IO.File]::Move($temp, $destination)
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp }
}
