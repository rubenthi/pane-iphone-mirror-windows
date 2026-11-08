# Develop and release Pane from Windows

## Set up a checkout

Use Python 3.12, Node.js with npm, stable Rust for Windows MSVC, the Visual Studio C++ build tools with a Windows SDK, and Git. WebView2 is required for the native-window checks. Publishing also uses GitHub CLI signed into the fork. Run the following in PowerShell from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
npm.cmd ci --ignore-scripts
npx.cmd playwright install chromium
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/fetch-companion.ps1
cargo build --release --locked --manifest-path signer/Cargo.toml
if ($LASTEXITCODE) { throw 'Signing helper build failed' }
Copy-Item signer/target/release/pane-signer.exe signer/pane-signer.exe -Force
cargo build --release --locked --manifest-path native/Cargo.toml
```

The fetch script restores the exact unsigned iPhone companion used by the previous compatible release and verifies its SHA-256. The IPA, native outputs, virtual environment and build directories are ignored by Git.

## Edit and run

Use a local feature branch. Close any other copy of Pane and run `.\.venv\Scripts\python.exe -m handset.app`. Restart it after Python, HTML, CSS or JavaScript edits. Rebuild the corresponding helper after Rust edits. A Windows shortcut can target `.venv\Scripts\pythonw.exe` with arguments `-m handset.app` and its **Start in** folder set to the checkout.

Source runs appear as **Pane (Development)**. They store settings, pairing records, and the browser profile in `%LOCALAPPDATA%\Pane (Development)` and use ports 8775 and 8776 for the UI and mirror. The downloaded **Pane** release uses `%LOCALAPPDATA%\Pane` and ports 8765 and 8766. Only the packaged release checks for desktop updates. For a disposable instance, set `PANE_DATA_DIR`, `PANE_PORT`, and `PANE_STREAM_PORT` before launching.

Choose **Reset development app** in Settings or at the bottom of first-run setup to clear the standard development profile and reopen the Connect step. Files already saved in Downloads remain available.

## Build and upload a release

1. Choose a desktop version above every reserved stable tag or release, including drafts. Update `handset/version.py`, both numeric and both string version fields in `packaging/version.txt`, and the changelog. Commit the finished source locally.
2. Run the local check command below from the clean commit. It runs Python, JavaScript, browser, native window, Rust and Windows installer tests, builds both native helpers and the executable, creates the update manifest and installer, and smoke-tests the packaged app. For a clean checkout it records the tested commit and all four file hashes in `dist/local-verification.json`. Hardware checks require a physical device and are recorded separately.
3. Push the final source branch to your fork and open a draft PR. Review and merge when authorized. Security CI can check the uploaded source. Desktop and macOS builds in Actions are available on demand. A push, tag or merge does not publish a release.
4. When ready to publish, run the upload command from the tested checkout. It requires that the tested commit be on main with identical file contents, checks the desktop and companion versions, reserves a fresh tag, uploads all four files to a draft, verifies GitHub's sizes and SHA-256 digests, then publishes the draft as latest. Use a merge commit or fast-forward to retain the tested source commit. For a squash or rebase, check out the merged commit and rerun the local check.
5. Verify the public release and the latest update manifest. Release installs check GitHub at launch and every six hours, retry after a transient failure and apply a verified update on normal exit. Reopen the release executable to run the update.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/check-local.ps1
# After review, merge and authorization to publish:
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/upload-release.ps1
```

If an upload fails, inspect the reserved tag, draft and hashes against the receipt before resuming. Keep existing releases immutable. An executable rollback backup is retained by the installer.

## iPhone companion changes

Windows can package an existing IPA. Compiling changed Swift source requires Xcode on macOS. Increase both the marketing version and build in `ios/project.yml` and match the marketing version in `handset/companion_version.py`. Build the exact source on a Mac or manually run the companion workflow for that commit. Put its unsigned IPA in `ios/Pane-unsigned.ipa` before testing on Windows. Update the restore script's source tag and checksum when the new IPA has a published baseline. Desktop-only changes reuse the verified IPA. Installing or renewing the companion on a phone remains a separate signing operation.
