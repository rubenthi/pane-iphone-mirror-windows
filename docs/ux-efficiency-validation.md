# Interface and efficiency changes: verification record

Base: `rubenthi/pane-iphone-mirror-windows`, main commit `6cbcdefaddc2b7415ac4b3024d4b35487d1d143d` (v2.2.1). Working branch: `codex/pane-ux-efficiency`. This base includes v2.2.0's UI regressions fixes and v2.2.1's USB reconnect fix. The earlier checkout and its changes were preserved in a separate worktree; no saved user state was reset. The iOS SwiftUI/CoreBluetooth sources, signing workflow and setup guide were read directly. No sparse checkout is active.

## Implemented

- Three compact desktop tabs with secondary settings pages, two transfers per history page, custom tooltips, reduced-motion-aware icon interaction, and a joined hover/focus island for window actions. The phone outline, overlay panel, four resize corners, volume/Siri/keyboard controls and frame-rate controls remain.
- Setup continues to use confirmed device state. Trust-profile troubleshooting is included; optional signing details collapse so the install action fits. A separate, skippable feature tour follows verified setup and can be replayed.
- Existing blue SVG supplies Windows PNG/ICO and iOS asset catalogs. SwiftUI uses native material and matching color, retains Photos/Files/Share and the encrypted transfer protocol, and stops USB-binding polling when inactive.
- Geometry commands use the direct native bridge when available. Only the newest queued drag/resize is kept. The WinForms region and WebView bounds are changed together before repainting, without a DWM frame recreation or copying the old window bitmap. Windows compositor behavior still requires a real Windows check.
- An optional Rust worker opens Windows A2DP reception while mirroring and subscribes to ANCS notifications. It uses one async event loop, a coalesced file-change signal, bounded queues, sleeping parent-process waits and error-only retry timers. No UI, Python or WebView stays open solely for background notifications. Background mode and previews default off. Existing signing data, pairings and preferences remain intact.

## Measured here

An automated Chromium fixture compared this base and the modified source with the same saved-pairing/disconnected-phone state, visible page and closed drawer. After a two-second warmup, it counted requests for 20 seconds:

| Local endpoint | Base | Modified |
| --- | ---: | ---: |
| `/api/setup` | 26 | 2 |
| `/api/uploads` | 26 | 2 |
| `/api/signing` | 13 | 2 |
| `/api/status` | 13 | 2 |
| `/api/screen` | 19 | 9 |
| **Total** | **97** | **17** |

That is approximately **82% fewer local status requests** in this observed run. To reproduce, point `PANE_BASELINE_ROOT` at an untouched v2.2.1 source directory and run `node tests/measure-idle.cjs`; the result is written to `test-results/idle-poll.json`. Active setup, signing and transfers refresh more frequently. Device-state polling is shared, retaining reconnect detection. Background/hidden-page refreshes slow further. This measures request frequency, not CPU, battery, resident memory, latency or installed size.

The geometry queue unit test submitted 100 positions while the first call was blocked. Only the first and final position were sent: two native calls, with the final position applied. HID events continue to use their ordered queue; keystrokes and button presses are not discarded.

A full Rust migration was **not** performed. The existing Rust signer, Python device integrations, Swift companion and WebView2 hardware HEVC decoder remain. A new helper adds code and can increase packaged size; it is not evidence of an overall storage reduction. Replacing the rest requires measured Windows gains and complete feature parity first.

## Available checks

The cloud checks passed: 70 Python tests discovered (65 passed, 5 platform/dependency skips), 11 JavaScript unit tests, 5 Rust protocol tests, both browser flows, Rust formatting, and Windows-target compilation/lint with warnings denied. Browser fixtures verify UI behavior without accessing a phone or radio.

Run from the repository root:

```
python3 -m unittest discover -s tests -v
npm ci --ignore-scripts
npm test
npm run test:setup
npm run test:experience
npm run test:visual
cargo fmt --check --manifest-path native/Cargo.toml
cargo test --locked --manifest-path native/Cargo.toml
cargo clippy --locked --manifest-path native/Cargo.toml --target x86_64-pc-windows-gnu -- -D warnings
```

For browser tests, set `PANE_TEST_PYTHON` and `PANE_TEST_CHROMIUM` when the executables are not the defaults. The Windows target must be installed through rustup for cross-platform checks. Tests cover authenticated preference endpoints, strict category validation, opt-in defaults, preservation of existing state, optional-worker error isolation, ANCS fragmentation/bounds/XML escaping, setup confirmation, signing USB disconnect/reconnect, transfers, tours, compact menus, tooltip focus, reduced motion and history pagination.

The existing Windows and iOS CI jobs remain and include the new helper/assets. Linux compilation of Windows bindings checks API types; it does not exercise the Windows runtime. Commit `abd92113f85892cb029170e5ff50650472251ffc` subsequently passed Windows native-window, installer/update and packaged-app smoke tests, and the iOS companion compiled in [CI run 42323942778](https://github.com/rubenthi/pane-iphone-mirror-windows/actions/runs/42323942778). This is separate from physical-device testing. No binary release was published.

The later visual refinement adds a 34-state browser review covering the three tabs, all settings views, notification and audio instructions off/on, background prerequisite, previews, tooltips, listbox focus/selection, setup stages, all tour pages, transfer progress, a small window, 160% CSS zoom and reduced motion. Tests assert local font loading, no external asset requests, normal-menu fit, keyboard listbox behavior, instruction expansion, long-filename tooltip wrapping and popup bounds. PNGs under `test-results/visual/` are rendered from current code with simulated device state, not native Windows captures. The current revision's PR checks are the source of its Windows CI result.

## Still requiring physical hardware or platform tools

- **Windows native window:** drag and resize rapidly from every corner at 100/125/150/200% DPI; confirm no white backing surface or delayed catch-up. Check minimize/restore, saved size, pinning, joined-island hit testing, monitor boundaries and live portrait/landscape changes. Run `npm run test:native` and the existing installer/update tests on Windows.
- **Bluetooth audio on Zephyrus:** pair the iPhone, choose the PC in iPhone's output menu, start/stop mirroring and test reconnect/disconnect. Confirm sound routes through the intended Windows output without changing the phone's volume. A2DP reception requires compatible Windows/adapter support; calls/microphone behavior is not claimed. Pane cannot force iOS's default route.
- **Notifications:** allow Share System Notifications, test each category, preview off/on, phone lock/privacy settings, event removal, sleep/wake and reconnect. Check real Windows toast identity/permissions. Close the GUI with background mode off and on, confirm process lifetime, then reopen and disable it. Verify concurrent file transfer and audio on the actual adapter. No phone notification content is written to Pane files or its HTTP API; Windows manages delivered toast history.
- **iOS signing and companion:** Xcode compilation/assets, integrated account verification/team selection, install/renewal, trust-profile prompts, binding import, protected settings preservation, both transfer directions, Photos/Files/Share and disconnect recovery. The cloud environment has neither Xcode nor a physical phone.
- **Whole-program performance:** compare release builds on the same Zephyrus/iPhone, same stream resolution/codec/frame target and workload. Measure installed footprint (including any cached helpers), cold/warm startup, total private working set across Pane/decoder/helper processes, idle and mirroring CPU, sustained displayed/received FPS and interaction latency. Warm up consistently and repeat runs. Reject a rewrite that loses functionality or fails any of the user's storage, memory and performance conditions.

## Reference and identity limits

Direct `https://www.rubenthi.com/` access was denied by the cloud network proxy (403 CONNECT), and the web reader also failed. No access bypass was attempted. The user subsequently supplied verified screenshot palette samples from the published ChatGPT Site, and the Sites connector confirmed the matching portfolio. The desktop dark-teal/ivory/sage palette adapts those samples; they are not claimed to be source CSS tokens. See `docs/design-details.md` for the mapping and typography.

The system developer label belongs to Apple's signing identity. App UI changes cannot hide that email/name from iOS trust screens. A different suitable identity or supported distribution route requires account/distribution work; existing credentials were preserved. No account or signing identity was changed.


## 2.3.0 release preparation (2026-11-07)

The release candidate was prepared in a clean worktree on Zephyrus_G14, leaving the older checkout and saved user state intact. Windows and iOS version metadata now identify 2.3.0. Local checks passed 73 Python tests with one existing platform/dependency skip, 11 JavaScript tests, setup and preference browser flows, all 34 visual states, native WinForms/WebView2 window checks, and the installer/update suite. The browser fixture now isolates both imported references to saved Wi-Fi pairings so the user's existing phone records do not alter test onboarding.

Release review found that an opted-in background helper could outlive a future executable upgrade. The worker now receives the desired content-addressed helper in session state, exits cooperatively when superseded, and lets its replacement wait for the lock without changing saved preferences or killing unrelated processes. Same-version workers are reused. New Python and Windows Rust lifecycle tests cover this behavior; CI must pass against the final commit before merge. Packaged smoke testing also starts the bundled native helper with disposable, radio-disabled state.

The publication workflow now repeats setup, preferences, visual and native Rust tests before publishing a version. Physical iPhone audio, notification permission, signing/install and mirroring performance checks remain unverified. The Windows update does not itself install or renew the iPhone companion.
