Pane 1.2.1 for Windows x64

- Floating, rounded phone window with a horizontally expanding connection sidebar, pinning, and display-aspect adaptation.
- Expandable iOS 27 setup guide covering prerequisites, USB, Trust, Developer Mode, input control, and optional Wi-Fi pairing. Includes optional AltStore Classic installation directions when Developer Mode is missing.
- Public device compatibility and verification records distinguish detected metadata from tested mirroring and control.
- Native WebView2 renderer, window-region and drawer integration tests, plus retained installer and updater failure-path tests. Native layout tests adapt to smaller hosted Windows desktops; v1.2.0 stopped before publication and its tag is preserved.

Requires Windows x64 and Microsoft Edge WebView2 Runtime. Apple Devices and a supported iPhone are needed for phone features. Browser fallback is available if the native renderer cannot start. The window follows display aspect ratio, not an exact physical bezel or cutout for every model.

Existing Pane 1.1.1 checks this fork on startup, stages the verified release, and installs it after Pane closes, retaining a backup. New installs: download install.ps1 and run powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version 1.2.1.

USB discovery and Developer Mode metadata were observed for iPhone19,3 / iOS 27.0.1. Physical video, keyboard/mouse control, Wi-Fi pairing, and the AltStore workaround have not been verified. This executable is not code-signed.

Rollback: close Pane and restore a retained Pane.exe.backup-* over Pane.exe. Disconnect networking temporarily if you do not want the older version to check for updates.
