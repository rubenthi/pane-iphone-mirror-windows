# Pane 2.0 setup and file sharing

Pane keeps USB/Wi-Fi screen mirroring and the iPhone's hardware volume controls. It does not capture or play sound, and it no longer lowers the phone's volume at startup.

## Clean start on the laptop

The first launch of 2.0 clears Pane-owned state in `%LOCALAPPDATA%\Pane`: its WebView/browser profiles, preferences, logs, staged files, history, protected signing data and app pairing state. Subsequent launches preserve the new configuration. Close Pane and run `Pane.exe --reset` to repeat the reset. If an old profile is locked, close the other Pane/browser processes before retrying; reset must finish before the new profile opens.

Downloads and other personal files are preserved. Apple Devices/iTunes trust records are shared operating-system data and are preserved. Old shared pymobiledevice3 records are not imported; new wireless records are isolated under Pane's own data directory. A cloud checkout cannot erase the user's laptop: the installed update performs this migration when launched there.

## Guided setup

1. Install Apple's USB driver and connect a data-capable cable. Unlock the iPhone and tap **Trust This Computer**. Select the phone in Pane.
2. Open **Connection → iPhone setup → Initiate setup**. Pane uses the trusted USB AMFI service to request that iOS reveal Developer Mode. It does not enable it or confirm the phone's prompts automatically. Device restrictions can cause this request to fail.
3. Install **Pane** using one of the signing paths below. The **Choose signed IPA & install** button stages a signed companion and pushes it using Apple's installation service. iOS validates its signature and device eligibility. Unsigned artifacts are rejected with signing instructions.
4. On the iPhone, open **Settings → Privacy & Security → Developer Mode**. Enable it, restart the **iPhone**, unlock it and confirm **Turn On**. Trust your own developer profile in **General → VPN & Device Management** if prompted. Reconnect USB and choose **Check Developer Mode & app** in Pane.
5. Choose **Bind USB & Wi-Fi**. Pane verifies the installed companion, pairs wireless mirroring over USB and writes a random pairing secret into the companion's shared Documents container.
6. Open Pane and tap **Activate USB link**. The app consumes that file into its protected application storage. Permit Bluetooth and choose **Connect Bluetooth** in Pane. Accept system pairing prompts on both devices. The secret and encrypted GATT characteristics restrict file access to the USB-bound laptop.
7. Keep Pane in the foreground during transfers. You can now unplug USB and use Wi-Fi for mirroring and Bluetooth for file sharing. Wi-Fi mirroring and BLE transfer are separate connections; this version does not transfer files over Wi-Fi.

Reconnect explicitly after a disconnect. Phone-to-laptop transfers retry from the beginning; a completed transfer whose acknowledgement was lost is not downloaded again while it remains in the bounded history. Interrupted laptop-to-phone transfers are marked failed; select the file again. Queued desktop files are cleared on app restart and their history explains that they must be reselected. Transfer limits are 2 GiB per file and eight queued outbound files. BLE is slow for large videos.

## Signing and installation

No App Store review is required, but Apple signing is required. Pane includes an isideload signing helper. The complete Windows build includes the unsigned companion IPA. In step 2, enter your Apple Account email and password, then choose **Sign & install with Pane**. Complete the verification-code prompt and select your developer team when asked. No separate AltStore installation is needed.

Passwords travel to the helper through anonymous pipes and are never saved or logged. Certificates and anisette state are saved under Pane/signing encrypted with Windows DPAPI. The helper uses Apple endpoints and the upstream anisette service at `https://ani.iloader.app`; network availability is required. Reset clears this local signing data but does not revoke certificates at Apple.

Repeat Sign & install with Pane using the included companion (or original unsigned IPA) and same Apple Account/team to renew. This build provides manual renewal; it does not run unattended renewal in the background. Certificate-limit errors require account maintenance; Pane never automatically revokes other certificates. Sessions time out after ten minutes, verification prompts after five, and can be cancelled. Cancellation cannot undo an installation or certificate already created at Apple.

**AltStore Classic on Windows:** follow [AltStore's official guide](https://faq.altstore.io/altstore-classic/how-to-install-altstore-windows), including its supported iTunes/iCloud versions. Install AltServer and use its tray menu to install AltStore on the iPhone. Authenticate directly in AltServer. Download the unsigned IPA from a successful [Pane build](https://github.com/rubenthi/pane-iphone-mirror-windows/actions/workflows/companion.yml), extract the artifact ZIP, and open the IPA in AltStore on the phone. AltStore signs and installs it. Continue with Developer Mode and USB binding in Pane. Free-account apps normally expire after seven days unless refreshed. AltStore installation is a separate, user-driven signing step, not an automated Pane signer.

**Development-signed IPA:** on a Mac, install Xcode and XcodeGen (`brew install xcodegen`). Run `xcodegen generate` in `ios`, open `PaneFiles.xcodeproj`, choose your team and a unique bundle identifier, then build/archive/export for your registered device. Select that IPA in Pane to push it over USB. Signing may change the bundle ID; Pane discovers the installed companion by its executable and display name. Keep one installed copy.

The CI build compiles the iPhone app without signing and packages `Pane-unsigned.ipa`. It is an input to a signer, not a directly installable or signed release.

## Sending and receiving

- **iPhone → laptop:** select images/videos with the Photos picker, or select Downloads and other documents with the Files picker. Only explicitly selected items are copied into the sending queue. Received files are checked for size and SHA-256, then saved to the Windows Downloads known folder, including relocated Downloads folders. Duplicate names get numbered suffixes. Unfinished files are not published as completed files.
- **Laptop → iPhone:** choose **Uploads → Send files to iPhone**. Keep Bluetooth connected. Verified received files appear in the companion and in **Files → On My iPhone → Pane → Received**. Use Share to save them elsewhere, including Photos where supported by iOS. An iOS app cannot silently write into other apps' private storage.
- **Volume:** the side buttons still send hardware volume commands to the iPhone. Bluetooth is used for files only; no sound is streamed to Windows.

## Verification boundaries

Automated tests exercise reset safety, authenticated HTTP actions, file limits/names, chunk ordering, checksums, duplicate names, disconnect cleanup, BLE framing and the browser setup/Uploads flow. GitHub Actions builds the iPhone companion and the Windows executable. These checks do not establish physical Bluetooth throughput, USB installation acceptance, signing eligibility, device prompts or iOS 27 mirroring compatibility. Test those on a Windows BLE-capable laptop with a physical iPhone before treating the full setup as hardware verified.
