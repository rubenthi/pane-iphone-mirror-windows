# Pane setup and file sharing

Pane keeps USB/Wi-Fi screen mirroring and the iPhone's hardware volume controls. It never lowers the phone's volume at startup. Optional Bluetooth audio reception is a separate Windows connection, configured in Settings → Bluetooth audio. The iPhone companion does not capture media.

## Settings and upgrades

Pane 2.2 and future updates preserve application settings, browser profiles, signing data and saved phone pairings under `%LOCALAPPDATA%\Pane`. Missing, old or damaged migration markers never authorize deleting user state. Upgrades directly from pre-2.x versions copy existing wireless pairing records into Pane's private store without overwriting newer records or changing shared Apple trust records.

Only an explicit `Pane.exe --reset` clears Pane-owned state. Close Pane before requesting a reset. Downloads and other personal files are preserved. An explicit reset does not re-import old shared pairings. Data already erased by an earlier release cannot be recovered by this update.

## Guided setup

The full guide opens automatically when no phone is saved. An existing pairing skips it even if the phone is unplugged or offline. A new, unfinished setup resumes until Bluetooth confirms the bound companion.

1. Connect an unlocked iPhone using a data-capable USB cable. Tap **Trust This Computer**. Install Apple's USB driver if needed.
2. Press **Connect**. Pane requests that the trusted USB AMFI service reveal Developer Mode; device restrictions can reject this request.
3. On iPhone, enable **Settings → Privacy & Security → Developer Mode**, restart the **iPhone**, unlock it and confirm **Turn On**. Reconnect USB and press **I've enabled it — check**. Pane verifies the setting before continuing.
4. Use **Sign & install with Pane** with your Apple Account. Complete Apple verification and team selection when prompted. The bundled isideload helper signs and installs the companion over USB.
5. Pane verifies the companion and automatically binds Wi-Fi mirroring over USB, then writes a random pairing secret into the app's Documents container.
6. Open Pane on the iPhone. If **Untrusted Developer** appears, open **Settings → General → VPN & Device Management → Developer App**, choose your signing profile and tap **Trust**. If iOS offers **Allow & Restart**, follow that prompt and reopen Pane after restarting. Verification may need an internet connection. If the profile is missing, finish installation first; an expired app needs renewal. Permit Bluetooth and accept system pairing prompts. The companion automatically imports its USB binding while open; **Activate USB link** remains available as a manual fallback.
7. Once Bluetooth confirms the bound app, the setup guide closes and a short feature tour introduces the controls. The tour can be replayed from Settings. Keep Pane in the foreground for transfers. USB can then be unplugged for Wi-Fi mirroring and Bluetooth file sharing. These are separate connections; files are not transferred over Wi-Fi.

**Settings → Setup & signing** remains available for maintenance, signed-IPA installation, optional AltStore signing and manual retries.

Reconnect explicitly after a disconnect. Phone-to-laptop transfers retry from the beginning; a completed transfer whose acknowledgement was lost is not downloaded again while it remains in the bounded history. Interrupted laptop-to-phone transfers are marked failed; select the file again. Queued desktop files are cleared on app restart and their history explains that they must be reselected. Transfer limits are 2 GiB per file and eight queued outbound files. BLE is slow for large videos.

## Signing and installation

No App Store review is required, but Apple signing is required. Pane includes an isideload signing helper. The complete Windows build includes the unsigned companion IPA. At the Install step, enter your Apple Account email and password, then choose **Sign & install with Pane**. Complete the verification-code prompt and select your developer team when asked. No separate AltStore installation is needed.

Passwords travel to the helper through anonymous pipes and are never saved or logged. Certificates and anisette state are saved under Pane/signing encrypted with Windows DPAPI. The helper uses Apple endpoints and the upstream anisette service at `https://ani.iloader.app`; network availability is required. An explicitly requested reset clears this local signing data but does not revoke certificates at Apple.

Repeat Sign & install with Pane using the included companion (or original unsigned IPA) and same Apple Account/team to renew. This build provides manual renewal; it does not run unattended renewal in the background. Certificate-limit errors require account maintenance; Pane never automatically revokes other certificates. Sessions time out after ten minutes, verification prompts after five, and can be cancelled. Cancellation cannot undo an installation or certificate already created at Apple.

**AltStore Classic on Windows:** follow [AltStore's official guide](https://faq.altstore.io/altstore-classic/how-to-install-altstore-windows), including its supported iTunes/iCloud versions. Install AltServer and use its tray menu to install AltStore on the iPhone. Authenticate directly in AltServer. Download the unsigned IPA from a successful [Pane build](https://github.com/rubenthi/pane-iphone-mirror-windows/actions/workflows/companion.yml), extract the artifact ZIP, and open the IPA in AltStore on the phone. AltStore signs and installs it. Continue with Developer Mode and USB binding in Pane. Free-account apps normally expire after seven days unless refreshed. AltStore installation is a separate, user-driven signing step, not an automated Pane signer.

**Development-signed IPA:** on a Mac, install Xcode and XcodeGen (`brew install xcodegen`). Run `xcodegen generate` in `ios`, open `PaneFiles.xcodeproj`, choose your team and a unique bundle identifier, then build/archive/export for your registered device. Select that IPA in Pane to push it over USB. Signing may change the bundle ID; Pane discovers the installed companion by its executable and display name. Keep one installed copy.

The CI build compiles the iPhone app without signing and packages `Pane-unsigned.ipa`. It is an input to a signer, not a directly installable or signed release.

## Sending and receiving

- **iPhone → laptop:** select images/videos with the Photos picker, or select Downloads and other documents with the Files picker. Only explicitly selected items are copied into the sending queue. Received files are checked for size and SHA-256, then saved to the Windows Downloads known folder, including relocated Downloads folders. Duplicate names get numbered suffixes. Unfinished files are not published as completed files.
- **Laptop → iPhone:** choose **Uploads → Send files to iPhone**. Keep Bluetooth connected. Verified received files appear in the companion and in **Files → On My iPhone → Pane → Received**. Use Share to save them elsewhere, including Photos where supported by iOS. An iOS app cannot silently write into other apps' private storage.
- **Volume:** the side buttons still send hardware volume commands to the iPhone. Optional Bluetooth audio connects the selected phone to the PC receiver while mirroring. Choose the PC in the iPhone output menu on first use; iOS retains control of its audio route.

## Verification boundaries

Automated tests exercise reset safety, authenticated HTTP actions, file limits/names, chunk ordering, checksums, duplicate names, disconnect cleanup, BLE framing and the browser setup/Uploads flow. GitHub Actions builds the iPhone companion and the Windows executable. These checks do not establish physical Bluetooth throughput, USB installation acceptance, signing eligibility, device prompts or iOS 27 mirroring compatibility. Test those on a Windows BLE-capable laptop with a physical iPhone before treating the full setup as hardware verified.


## Developer identity shown by iOS

The developer name or email shown in the system trust screen comes from the Apple signing identity. Renaming Pane, changing its icon, editing Info.plist, or hiding a label in SwiftUI cannot remove it from that system UI. No personal developer email is hardcoded into Pane's UI. Use an appropriate dedicated signing identity or supported App Store/TestFlight distribution if you want a different public identity. Distribution, account changes and Apple's approval are separate steps; Pane does not spoof the trust screen or alter existing signing credentials.

## Optional notifications and background services

The desktop Settings pages explain pairing, audio output and **Share System Notifications**. Enable phone notifications, choose the paired BLE iPhone and select categories. Message text is hidden unless previews are enabled. ANCS is an iOS system service, separate from the file-transfer companion; iOS privacy settings determine which alerts and previews are available.

**Keep notifications running** retains only the native notification helper after closing Pane. It is opt-in, requires phone notifications to be enabled, and does not enable background transfers, mirroring, signing renewal or automatic startup. Reopen Pane to disable it. A reset first asks that helper to stop before clearing Pane-owned data. See [validation and remaining hardware checks](ux-efficiency-validation.md).
