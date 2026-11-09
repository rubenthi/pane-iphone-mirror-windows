# Publish the exact files verified by check-local.ps1. Run after source review.
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $repo = 'rubenthi/pane-iphone-mirror-windows'
    $assets = @('dist/Pane.exe','dist/update.json','dist/install.ps1','ios/Pane-unsigned.ipa')
    $receipt = Get-Content dist/local-verification.json -Raw | ConvertFrom-Json
    $tag = $receipt.tag
    if ($tag -cnotmatch '^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') { throw 'Invalid release tag.' }
    $head = git rev-parse HEAD
    if ($LASTEXITCODE -or $head -ne $receipt.commit) { throw 'Recheck the final release commit locally.' }
    $changes = git status --porcelain
    if ($LASTEXITCODE -or $changes) { throw 'Recheck a clean release commit.' }
    foreach ($asset in $assets) {
        if ((Get-FileHash -LiteralPath $asset).Hash -ne $receipt.hashes.$asset) { throw "Recheck changed asset $asset." }
    }
    $remote = "https://github.com/$repo.git"
    git fetch $remote main --tags
    if ($LASTEXITCODE) { throw 'Cannot check published source and tags.' }
    git merge-base --is-ancestor $head FETCH_HEAD
    if ($LASTEXITCODE) { throw 'Merge the tested source into main before uploading.' }
    git diff --quiet $head FETCH_HEAD
    if ($LASTEXITCODE) { throw 'Main differs from the tested source. Review and recheck.' }
    $existing = git tag --list $tag
    if ($LASTEXITCODE -or $existing) { throw "Inspect existing tag $tag before recovery." }
    $inventory = gh api "repos/$repo/releases?per_page=100" --paginate --slurp
    if ($LASTEXITCODE) { throw 'Cannot inspect GitHub releases. Check gh auth status.' }
    $inventory | Set-Content -Encoding UTF8 dist/release-inventory.json
    & .venv/Scripts/python.exe packaging/prepare_release.py --source $head --tag $tag --releases dist/release-inventory.json --output dist/release-version.txt
    if ($LASTEXITCODE) { throw 'Version or companion policy check failed.' }
    git tag $tag $head
    if ($LASTEXITCODE) { throw 'Cannot create release tag.' }
    git push $remote "refs/tags/$tag"
    if ($LASTEXITCODE) { throw 'Tag reservation failed. Inspect local and remote tags.' }
    gh release create $tag @assets --repo $repo --verify-tag --draft --title "Pane $tag" --generate-notes --notes "Windows build compiled and verified locally. [Matching source and build instructions](https://github.com/$repo/tree/$head)."
    if ($LASTEXITCODE) { throw 'Draft upload failed. Inspect the reserved tag and draft.' }
    $json = gh release view $tag --repo $repo --json assets
    if ($LASTEXITCODE) { throw 'Cannot verify draft files.' }
    $uploaded = ($json | ConvertFrom-Json).assets
    if ($uploaded.Count -ne $assets.Count) { throw 'Unexpected draft asset count.' }
    foreach ($asset in $assets) {
        $file = Get-Item -LiteralPath $asset
        $match = @($uploaded | Where-Object name -eq $file.Name)
        if ($match.Count -ne 1 -or $match[0].size -ne $file.Length -or $match[0].digest -ne "sha256:$($receipt.hashes.$asset)") {
            throw "GitHub digest or size differs for $asset. Draft retained."
        }
    }
    gh release edit $tag --repo $repo --draft=false --latest
    if ($LASTEXITCODE) { throw 'Publication failed. Inspect the verified draft.' }
} finally {
    Pop-Location
}
