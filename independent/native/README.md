# Pane Next native prototype

Unreleased independent implementation. Publication is disabled. The project's own license has not been selected; provenance and license review are required before distribution.

This Windows-only Rust program creates a separate `pane-next-prototype.exe` process and `PaneNextIndependentPrototypeWindow` window class. It does not read the existing Pane installation, settings, pairing records, or browser profile. Its only local application data is optional error diagnostics in `%LOCALAPPDATA%\Pane Next Prototype\Logs`. Discovery reads Windows metadata and sends only a device-list request to the local Apple service at `127.0.0.1:27015`. It performs no remote-network, phone-opening, pairing, signing, install, or update operations.

The shell uses Win32 messages, GDI drawing, native text/list/button controls, and the Windows system message font. Fonts and brushes are cached for the lifetime of the window; fonts are recreated only when DPI or system settings change. Per-monitor-v2 awareness handles Windows DPI changes; logical sizes are scaled at 96/192 DPI (100/200%). Native controls expose standard text and keyboard semantics, including Tab focus and the device list's arrow-key navigation. Visual checks across both monitor densities and maximize/restore passed locally; a screen-reader session and four-corner resize checks remain unverified.

Window state owns an `Rc` token on the UI thread. Each callback retains a short-lived owner before calling child-window APIs, so reentrant window destruction cannot free GDI resources underneath it. Font generations are retained independently across synchronous child messages, with no `RefCell` borrow held while those messages run. Destruction immediately cancels the scan job and releases its receiver even if another callback still retains resources. Worker threads receive only the atomic cancellation flag, result channel, and an integer window notification token, never the UI `Rc`.

The native title bar opts into the system's dark-mode frame colors through DWM where supported. An unsupported theme attribute does not prevent startup.

The native device list has a dedicated **Available devices** text label directly before it in control creation order, preserving the Windows accessibility proxy's label association independently of the release-status footer.

Painting occurs in response to window invalidation. The blocking message loop has no animation timer or polling. Discovery runs once at startup, on **Refresh devices**, and on the documented `WM_DEVICECHANGE` / `DBT_DEVNODES_CHANGED` broadcast. A small scheduler allows one active scan and one pending rescan, coalescing repeated events without accumulating jobs. Pure tests exercise a 10,000-event burst and cancellation. Device-change notifications describe Windows hardware changes; changes to Wi-Fi records that do not produce a Windows hardware event still require **Refresh devices**.

Each short-lived worker reads a bounded SetupAPI USB snapshot, then makes one local Apple `ListDevices` request with an overall three-second deadline for that request. It opens no phone connection. The UI prefers the service's USB/Wi-Fi routing records over composite Windows device nodes. Labels are generic: **Apple mobile device · USB/Wi-Fi · pairing not checked**. Counts describe records, rather than unique or paired phones. If the service is unavailable or empty, a separate Windows USB diagnostic summarizes node/ready-driver counts and the UI suggests opening Apple Devices before refreshing. USB node presence, mobile-driver readiness, and routing records do not establish pairing, trust, or a usable session.

Opaque Apple identifiers and routing IDs are discarded on the worker; only transport enums reach the UI. Windows instance IDs and names are reduced to numeric diagnostic counts before delivery. A closed window cancels result delivery and queued rescans; channel ownership releases abandoned results without leaking a posted heap pointer. These are implementation properties, not measured CPU or memory claims.

Handled errors show a brief status with a useful next action. Local diagnostics record only a timestamp, static event name, and numeric code; they exclude device names, IDs, credentials, arbitrary backend error messages, and panic payloads. Logs rotate at approximately 64 KiB into one previous file and are written only on errors. Logging failures do not prevent the UI from reporting an error. The release build aborts on a Rust panic after the generic panic hook runs; recovery from arbitrary panics is not promised.

Phone connection is not implemented. Neither the executable nor the mailbox constitutes a mirroring solution. There is no iPhone companion, transport, decoder, audio, input forwarding, or renderer for received frames.

`src/devices.rs` implements bounded Windows USB enumeration. `src/usbmux.rs`
implements only the local Apple service's device-list request, with a three-second
overall deadline, one-MiB packet bound, bounded XML preflight and redacted errors.
It does not read trust records or start a phone session. The observed WinUSB
mobile-driver rule is narrowly limited to the tested Apple VID/PID combination;
it is not a complete iPhone compatibility catalogue.

`src/hevc_rtp.rs` is a standalone RFC 3550/7798 depacketizer with explicit
packet/access-unit bounds and loss handling. It performs no networking or video
decoding. Its documented no-DONL, single-source limits must match a future
negotiated stream. `src/media.rs` enumerates and activates Windows HEVC transform
candidates; a D3D11-aware transform does not prove hardware decoding. Run the
explicit, read-only capability probe with:

```powershell
cargo run --release --locked --offline --example capabilities
```

This diagnostic prints only counts and codec capabilities, never phone IDs.

`src/lib.rs` provides a first-party single-pending-frame CPU BGRA mailbox. Each valid submission transfers an owned `Box<[u8]>` without allocating or copying pixel bytes, and drops the obsolete pending image. Its retained-pixel budget is configurable. Replacing a pending frame briefly retains up to two budget-sized allocations. Producer allocations and frames removed by the caller are outside that budget. The queue does not create threads; a future transport must synchronize shared access and set its own decoder/output budgets. This helper is not a zero-copy video pipeline: future hardware decoding should keep frames in GPU surfaces rather than copy them into these CPU buffers.

Build and test from this directory on Windows with Rust and MSVC build tools:

```powershell
cargo test --locked --offline
cargo fmt --check
cargo build --release --locked --offline
```

Dependencies include Microsoft's `windows` 0.62.2 crate with the required Win32 feature groups, `plist` for property lists, and `quick-xml` for bounded XML preflight, with their exact dependency tree recorded in `Cargo.lock`. No code or assets are copied from the existing Pane implementation. No third-party source is vendored. Dependency licenses still require the repository-level provenance gate before distribution.

API references used for fresh implementation:

- [Win32 window messages and message loop](https://learn.microsoft.com/en-us/windows/win32/learnwin32/window-messages)
- [CreateWindowExW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createwindowexw)
- [SetProcessDpiAwarenessContext](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext)
- [WM_DPICHANGED](https://learn.microsoft.com/en-us/windows/win32/hidpi/wm-dpichanged)
- [SystemParametersInfoForDpi](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-systemparametersinfofordpi)
- [DrawTextW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-drawtextw)
- [Static controls](https://learn.microsoft.com/en-us/windows/win32/controls/about-static-controls)
- [WM_SETFONT](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-setfont)
- [PostMessageW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-postmessagew)
- [DwmSetWindowAttribute](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmsetwindowattribute)
- [DBT_DEVNODES_CHANGED](https://learn.microsoft.com/en-us/windows/win32/devio/dbt-devnodes-changed)
- [RTP header specification](https://www.rfc-editor.org/rfc/rfc3550.html)
- [HEVC payload specification](https://www.rfc-editor.org/rfc/rfc7798.html)
- [Windows HEVC decoder](https://learn.microsoft.com/en-us/windows/win32/medfound/h-265---hevc-video-decoder)
- [MFTEnumEx](https://learn.microsoft.com/en-us/windows/win32/api/mfapi/nf-mfapi-mftenumex)
- [Apple service API descriptions](https://docs.rs/idevice/latest/idevice/usbmuxd/index.html) (API/wire facts only; this crate is not linked)
