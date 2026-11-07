# Pane Bluetooth worker

Windows-only A2DP receiver and ANCS notification subscriber. This is separate from the existing Swift/CoreBluetooth file-transfer companion and Rust signing helper. Build with `cargo build --release --locked --manifest-path native/Cargo.toml`; the Windows packaging script bundles the executable. Windows 10 version 2004 or newer and a compatible Bluetooth adapter are needed for A2DP reception.

`pane-companion.exe --devices` returns paired audio and BLE choices. `--run <Pane data directory>` reads `preferences.json` and `session.json`, watches changes, and writes connection state to `companion-status.json`. An exclusive file lock prevents duplicate workers. The Python launcher copies the executable into a content-addressed application-data directory so closing a PyInstaller one-file app does not remove a running worker.

No notification title/body is saved in these files or forwarded through HTTP. ANCS previews are opt-in, escaped into Windows toast XML, bounded to 128 title bytes / 512 message bytes, and correlated across GATT fragments. Pre-existing events are ignored; removed events dismiss the associated Windows toast. Queues and remembered IDs are bounded. iOS decides categories and available content. Messages/social are one iOS category, not an app-specific SMS permission.

Audio exists only during a live desktop mirroring session. Notifications survive GUI exit only when both notification forwarding and background mode are enabled. There is no Windows startup registration. Disabling features wakes the helper through a coalesced notification, separate from radio-event queues, and releases its connections. Parent death is observed through a Windows process handle. Files/signing/mirroring never run in this helper.

For unpackaged Windows toasts the worker registers `Pane.Desktop` under HKCU and creates the current user's Start-menu `Pane.lnk` with that AUMID and the real packaged Pane executable/icon. It never creates a startup shortcut or opens a network listener. Windows notification permission and iPhone Share System Notifications must be enabled. Toast clicking/reply actions are not implemented.

See [verification boundaries and measurements](../docs/ux-efficiency-validation.md). Rust tests exercise protocol parsing on Linux; Windows API compilation alone is not radio or toast verification.
