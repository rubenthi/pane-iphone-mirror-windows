Pane 1.1.1 for Windows x64

- Reconstructed automatic updater, restricted to rubenthi/pane-iphone-mirror-windows. Checks on startup and stages verified newer releases for installation after Pane closes.
- Corrected the Windows PowerShell helper environment and added a real process-handoff regression test. The v1.1.0 workflow was cancelled before publication; its tag is preserved.
- Standalone installer, desktop shortcut, SHA-256/size validation, bounded exit wait, and retained executable backups.
- Fixed malformed API requests, proxy framing, restart reporting, Wi-Fi connection cleanup, concurrent stream switching, stale UI responses, and control ordering.
- Secured the upstream stream server with a process-specific credential and pinned the Windows build dependencies.
- Added Windows installer failure-path tests, Python and JavaScript regression tests, and packaged dependency/local UI smoke checks.

The earlier uncommitted cloud workspace was unavailable. These changes were reconstructed and tested from the fork's published source. The pinned streaming engine requires iOS 27 or later. Physical iPhone mirroring, keyboard/mouse control, and Wi-Fi require validation with a connected phone. This executable is not code-signed.

Install: download install.ps1, then run `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version 1.1.1`.
Rollback: close Pane and restore a retained `Pane.exe.backup-*` file over `Pane.exe`. Temporarily disconnect networking when launching the older version if you do not want it to check for updates.
