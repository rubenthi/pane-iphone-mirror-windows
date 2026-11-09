# Pane Next native prototype

Unreleased independent implementation. Publication is disabled. The project's own license has not been selected; provenance and license review are required before distribution.

This Windows-only Rust program creates a separate `pane-next-prototype.exe` process and `PaneNextIndependentPrototypeWindow` window class. It stores no settings, pairing records, browser profile, or other application data. It does not read the existing Pane installation. It performs no network, device, signing, install, or update operations.

The shell uses Win32 messages, GDI drawing, and the Windows system message font. Per-monitor-v2 awareness handles Windows DPI changes; logical sizes are scaled at 96/192 DPI (100/200%). Painting occurs in response to window invalidation; the blocking message loop has no animation timer, polling, or background worker. This is an implementation property, not a measured CPU or memory claim. Visual checks at both scaling settings remain required.

Phone connection is not implemented. Neither the executable nor the mailbox constitutes a mirroring solution. There is no iPhone companion, transport, decoder, audio, input forwarding, or renderer for received frames.

`src/lib.rs` provides a first-party single-pending-frame CPU BGRA mailbox. Each valid submission transfers an owned `Box<[u8]>` without allocating or copying pixel bytes, and drops the obsolete pending image. Its retained-pixel budget is configurable. Replacing a pending frame briefly retains up to two budget-sized allocations. Producer allocations and frames removed by the caller are outside that budget. The queue does not create threads; a future transport must synchronize shared access and set its own decoder/output budgets. This helper is not a zero-copy video pipeline: future hardware decoding should keep frames in GPU surfaces rather than copy them into these CPU buffers.

Build and test from this directory on Windows with Rust and MSVC build tools:

```powershell
cargo test --locked --offline
cargo fmt --check
cargo build --release --locked --offline
```

Dependency: Microsoft's `windows` 0.62.2 crate with only the required Win32 feature groups, plus its transitive Rust support crates recorded in `Cargo.lock`. No code or assets are copied from the existing Pane implementation. No third-party source is vendored. Dependency licenses still require the repository-level provenance gate before distribution.

API references used for fresh implementation:

- [Win32 window messages and message loop](https://learn.microsoft.com/en-us/windows/win32/learnwin32/window-messages)
- [CreateWindowExW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createwindowexw)
- [SetProcessDpiAwarenessContext](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext)
- [WM_DPICHANGED](https://learn.microsoft.com/en-us/windows/win32/hidpi/wm-dpichanged)
- [SystemParametersInfoForDpi](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-systemparametersinfofordpi)
- [DrawTextW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-drawtextw)
