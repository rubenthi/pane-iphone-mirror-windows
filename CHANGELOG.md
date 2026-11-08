# Pane update history

This log explains changes to the Windows application and its iPhone companion. Downloadable versions and publication status are listed in [GitHub Releases](https://github.com/rubenthi/pane-iphone-mirror-windows/releases). A source commit or build artifact is not itself an automatic-update release.

## 2.5.6 - Native display density and flat colors (development build)

Pane renders at each monitor's own pixel density instead of letting Windows stretch a 100%-scale bitmap on a 200%-scale laptop screen. The packaged executable declares PerMonitorV2, source runs enable the same mode before opening the window, and moving between monitors updates the physical window shape and browser surface together. The three-pixel black bezel stays consistent.

Flat Slate surfaces and Blue action colors from [Radix Colors](https://www.radix-ui.com/colors/docs/palette-composition/composing-a-palette) replace the layered blue gradients, glossy highlights and hover glows. Controls keep their existing layout and behavior. The iPhone companion is unchanged.

## 2.5.5 - Simpler notification setup and black bezel (development build)

Phone notification setup starts with one switch. Pane selects a paired iPhone automatically when there is one unambiguous choice, while keeping saved choices. A compact Bluetooth settings preview shows the laptop name and Share System Notifications switch; it disappears once connected. Check again refreshes devices and retries, and Windows notification permission failures offer the correct settings shortcut. Alert categories and message previews are under Alerts & privacy; previews and background behavior remain separate opt-ins.

The uniform three-pixel bezel is solid black. The iPhone companion is unchanged.

## 2.5.4 - Thin uniform bezel and Wi-Fi reconnection (development build)

The bezel is a single uniform three-pixel ring. Screen rendering uses the integrated display dimensions reported by the iPhone to remove small encoder padding at the right and bottom, rather than treating that padding as part of the display. It does not guess from black app content or hardcode phone models. Normalized touch coordinates cover the complete real display.

Wi-Fi discovery waits for the complete address list, tries IPv4 first and returns on the first verified connection. Full pairing handshakes and tunnel startup have deadlines; failed candidates close promptly. A rejected saved pairing now asks for USB repair instead of another unlock. Connection attempts do not change pairing records. The iPhone companion is unchanged.

## 2.5.3 - Essential tooltips and uniform bezel (development build)

Tooltips are limited to ambiguous icon controls and filenames that are actually truncated. Visible button labels and settings no longer repeat themselves in hover bubbles. The mirrored image fills the symmetric seven-pixel screen opening, preserving aspect while clipping the small rounding excess instead of adding black letterbox strips. The existing iPhone companion is unchanged.

## 2.5.2 - Four-corner resizing (development build)

Diagonal resize gestures use a continuous aspect-preserving calculation, keeping direction changes smooth. Native bounds and the anchored opposite corner update together, instead of exposing an intermediate position. Late bridge replies no longer overwrite current viewport dimensions. Open panels have a usable minimum height, and their title leaves room for the header buttons. The existing 2.6.0 (6) iPhone companion is unchanged.

## 2.5.1 - Direct Wi-Fi phone uploads (development build)

Phone-to-laptop files can use a direct local TLS connection instead of Bluetooth for bulk data. The existing USB-bound, encrypted Bluetooth link conveys a temporary certificate pin and channel secret. Transfers retain bounded buffers, Pause/Cancel, checksums and atomic delivery; interrupted Wi-Fi resumes at the last written offset over Bluetooth. Requires companion 2.6.0 (6), local-network permission and a reachable local network. No cloud relay or public release. Actual radio speed must be measured on the devices.

## 2.5.0 - Visual setup and independent transfers (local test build)

Local follow-up: phone uploads use independent 32 KiB receive batches when supported, omit redundant incoming metadata and rate-limit unchanged control snapshots. Local Pause/Cancel and changed queues bypass the limit; completion forces a final remote control check. This desktop-only optimization retains the existing companion and has not been pushed or published.

Prepared locally; this version has not been published. The packaged development edition runs as Pane.exe with its own taskbar identity and reuses the development profile via `--development`.

Setup uses short illustrated Settings paths, compact certificate recovery and brief failure messages with a next action. Settings uses grouped icon rows and Back navigation. Connect your iPhone immediately attempts Wi-Fi. Scroll over the side volume buttons to adjust volume while connected.

Saved Bluetooth file pairing reconnects while Pane is open, independently of screen mirroring. A manually disconnected file link stays disconnected until explicitly reconnected or Pane restarts. The saved audio receiver also follows the desktop app's lifetime while honoring its existing switch and selected device.

The iPhone companion source is now 2.5.1, build 5. It adds Pause, Resume and Cancel for transfers in both directions and negotiates larger acknowledged batches with Windows. Keep iPhone awake prevents idle screen locking while Pane is visible and restores normal behavior when leaving the app. Existing companions retain the legacy transfer protocol. Actual Bluetooth speed depends on the devices and connection; no hardware throughput improvement is claimed from automated tests.

The Enable step requests Developer Mode again if the setting is still hidden. Enabling it, restarting and confirming remain on the iPhone. Installation now explains how credentials are processed locally, identifies the stage of signing failures, and offers credential-free service diagnostics. Saved signing keys and pairings are preserved.

When Apple reports certificate limit 7460, setup offers a certificate list and a separate **Revoke selected certificate & retry** confirmation. Selecting a certificate does not revoke it. The warning explains that revocation cannot be undone and may stop other apps signed with that certificate from opening.

## 2.4.0 - iPhone transfers and USB updates

The iPhone companion has a Transfers screen with native Liquid Glass send controls on iOS 26 and later. Received files, sharing and the outgoing queue are together. Tap the laptop connection row for USB pairing and the installed version. iOS 17–18 use standard SwiftUI buttons.

Windows checks the bundled companion before offering an update. A verified older installation triggers a prompt at startup or when the phone connects by USB. Choose **Update via USB** and sign with the same Apple Account and team to update the existing app.

## 2.3.2 - Local Windows development and releases

Pane now runs from the developer's Windows checkout. The Windows executable and native helpers are compiled and tested on the laptop before the finished files are uploaded to GitHub Releases. The installer and updater still use the published release. Shorter notification setup text keeps the status visible at the default window size. This desktop release includes the same 2.3.0 iPhone companion as 2.3.1.

## 2.3.0 - Compact controls and optional Bluetooth services

- Adds compact Connection, Uploads and Settings navigation, dark teal controls, locally bundled typography, accessible custom dropdowns, clearer required setup steps and a replayable feature tour.
- Retains the phone-shaped native window, joined control island, blue Pane icon, volume/Siri/keyboard controls and frame-rate choices. Coalesces drag/resize commands and reduces idle status polling.
- Adds optional Windows Bluetooth audio reception while mirroring and category-filtered iPhone system notifications. Background notification mode and message previews default off. iOS still controls audio routing and notification permissions.
- Preserves existing preferences, saved phone pairings, browser profiles and protected signing data. Includes the 2.2.1 USB reconnect fix. Updates install on normal close; reopen Pane to use the new version.
- Bundles the 2.3.0 iPhone companion. Installing or renewing it remains a separate signing step, not an automatic effect of the Windows update.
- Shows a startup popup only for a verified newer mobile app, using its own version rather than the PC version. With an unknown installed version, Settings offers a USB check instead of guessing.

Automated Windows, browser, Rust and iOS checks cover the supported build and update paths. Physical iPhone Bluetooth/audio/notification/signing behavior and whole-program performance still need device acceptance testing. See [verification scope](docs/ux-efficiency-validation.md).

## 2.2.1 — Enable installation after USB reconnection

- Fixes the greyed-out Sign & install button when the phone is plugged in or reconnects after Developer Mode setup. The guide now refreshes the USB status used by signing.
- Explains when a USB connection is required to enable installation.
- Preserves settings, setup progress and saved phone pairings.

## 2.2.0 — Restored floating window and first-run setup

- Restores 1.7.4's native WinForms/WebView region clipping, phone outline, joined control rail and upward hover menu. The Connection/Uploads panel overlays the phone without expanding the window; all four corners resize proportionally.
- Restores Connect/Disconnect, Home-hold Siri, queued gestures and keyboard handling, bounded video packet decoding, display frame pacing and 15/30/60 FPS targets with measured frame-rate telemetry.
- Automatically opens a full setup guide only when no phone pairing is saved. Guides USB trust and Developer Mode reveal, verifies the user's iPhone restart/confirmation, signs and installs the companion with Pane, then binds USB/Wi-Fi and connects Bluetooth. Progress survives app restarts; Bluetooth errors allow an explicit retry.
- The iPhone companion imports a newly provisioned USB link while open. Bluetooth confirmation completes onboarding and opens the regular interface.
- **Updates preserve settings and saved phones.** Removes automatic state clearing and browser preference clearing. Preserves older wireless pairings on direct pre-2.x upgrades. Only an explicit `Pane.exe --reset` erases Pane-owned state; it does not restore old shared pairings.
- Retains 2.1.1's integrated isideload signer, bundled companion, Uploads transfers in both directions, Downloads destination, volume/mute controls and automatic updater.
- Published through the existing stable update feed. Verified downloads install when Pane closes; reopen Pane to run the update.

Validation covers state preservation, legacy pairing migration, setup sequencing/retries, transfers, stream framing, and real Windows HWND clipping/desktop pixels. Live Apple-account authentication, USB installation and physical Bluetooth transfers still require device acceptance testing.

[Setup guide](docs/companion-setup.md) · [2.2.0 release](https://github.com/rubenthi/pane-iphone-mirror-windows/releases/tag/v2.2.0)

## 2.1.1 — Automatic updates and integrated iPhone setup

This release includes the changes developed on main as Pane 2.0 and 2.1; those development versions were not separately published to the automatic-update feed.

### Windows automatic updates

- Pane checks this fork's published update feed at launch and every six hours while it remains open. Failed checks retry after fifteen minutes, so starting offline does not require restarting Pane to check again.
- A newer Windows executable downloads in the background. Pane verifies the expected size and SHA-256 before staging it.
- Closing Pane normally installs the verified update automatically. Reopen Pane to use the new version. The previous executable is retained as a rollback backup; active mirroring is not forcibly interrupted.
- Version bumps on main trigger the release pipeline. The pipeline builds the iPhone companion and Windows app, runs Windows tests and packaged-app checks, validates the version/checksum manifest, then publishes the assets together. Ordinary source-only changes do not create a new version.

### Install the iPhone companion from Pane

- **Sign & install with Pane** uses a bundled isideload helper to sign and install the included companion over USB. A separate AltStore or Xcode installation is not needed on the user's laptop.
- Setup supports Apple Account sign-in, verification-code prompts, developer-team selection, cancellation and timeouts. Apple signing and network access remain required.
- Passwords are not saved or logged. Certificates and authentication-support state are encrypted for the current Windows user with DPAPI. Pane does not automatically revoke other development certificates.
- Renew the iPhone app manually through the same signing flow using the same Apple Account/team. Free-account apps normally need renewal every seven days. **Windows automatic updates do not automatically renew the iPhone signing certificate/profile.**
- An optional IPA picker remains available for an unsigned replacement companion; an already signed IPA can also be installed directly.

### Guided connections and file sharing

- Setup guides USB trust, revealing Developer Mode, installing Pane, enabling Developer Mode on the phone, restarting/confirming on the iPhone, and binding USB/Wi-Fi/Bluetooth.
- The **Uploads** sidebar tab sends files in both directions over Bluetooth Low Energy. The iPhone app offers Photos and Files pickers.
- Incoming laptop files are verified and saved to the Windows Downloads folder, including relocated Downloads folders. Duplicate filenames receive numbered suffixes instead of overwriting existing files.
- Files sent to the phone appear in Pane's Received folder and native sharing controls. Keep the companion open during transfers; Bluetooth transfer speed is limited for large files.
- Interrupted transfers show a failure/recovery state. Desktop queues are cleared on restart and affected files must be selected again.

### Interface, volume and reset behavior

- Both apps display **Pane**. Compact tabs, consistent outline icons, quieter separators, readable transfer states and measured progress refine the desktop interface. The iPhone app uses native grouped sections and sharing controls. [Design references and details](docs/design-details.md).
- iPhone volume and mute controls remain. Automatic startup volume reduction is removed, and audio streaming is disabled. Bluetooth is used for file sharing.
- Historical behavior (removed in 2.2.0): first launch of Pane 2.0–2.1.1 resets old Pane-owned preferences, browser profiles, logs and saved application state. `Pane.exe --reset` repeats the reset, including protected local signing data.
- Personal Downloads and shared Apple system trust records are preserved. Reset does not revoke certificates held by Apple.

### Validation and remaining device checks

The integrated-signing build passed iPhone compilation, Windows Python/JavaScript tests, DPAPI encryption, native WebView UI, updater handoff, packaging and packaged helper/IPA smoke tests. The 2.1.1 release pipeline repeats the applicable checks before publication. Live Apple authentication, physical iPhone installation, Bluetooth transfers and signing renewal still require device acceptance testing.

[Setup instructions](docs/companion-setup.md) · [2.1.1 release](https://github.com/rubenthi/pane-iphone-mirror-windows/releases/tag/v2.1.1)

## 1.7.5 — Previous published release

As documented in its original release notes:

- Selected the paired Bluetooth audio endpoint matching the mirrored iPhone. The Apple Music playback issue remained unresolved. Audio playback is removed from the Pane 2.x flow described above.
- Used the primary display dimensions to remove encoder padding and refined the screen border, window resizing, window-button gaps and minimize behavior.
- Changed trackpad scrolling to a continuous iPhone touch gesture.
- Supported downloading an update, closing Pane normally to install it, and reopening the new version.

[Original 1.7.5 release notes](https://github.com/rubenthi/pane-iphone-mirror-windows/releases/tag/v1.7.5). Earlier published history remains available in [GitHub Releases](https://github.com/rubenthi/pane-iphone-mirror-windows/releases).
