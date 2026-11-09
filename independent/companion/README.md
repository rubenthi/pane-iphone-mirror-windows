# Independent iPhone companion

This Swift application targets iOS 17 and later. The container and its ReplayKit broadcast extension share one device-only Keychain entry. The independent bundle base defaults to `org.panenext.independent.companion`. The extension appends `.broadcast`. Keeping these two identifiers separate from prior installations gives this app its own files and credentials. Version **3.0.0 (7)** applies to both targets.

## Build and verify on a Mac

Install Xcode with an iOS SDK and simulator runtime, select it with `xcode-select`, and install XcodeGen (`brew install xcodegen`). From this directory run:

```sh
bash build.sh
bash Tests/simulator.sh
```

The first command runs CryptoKit interoperability, filename, and RTP tests, builds for Simulator and device, validates both bundles, and produces `build/IndependentCompanion-unsigned.ipa` plus its SHA-256. The second creates a disposable iPhone simulator, launches the app, saves a screenshot and removes that simulator. GitHub Actions runs both commands on companion pull requests and on manual dispatch. The unsigned IPA requires signing before physical installation.

## Sign and install with Xcode

On the Mac, open the generated `IndependentCompanion.xcodeproj`. Add the authorized Apple account to Xcode. Select the same development team for both targets and automatic signing. Set the **project-level** `PANE_BUNDLE_BASE` to an available identifier owned by that team and dedicated to this independent companion. Verify the derived extension ID and shared Keychain access group in both targets. Signing needs an Apple Development identity with its private key, provisioning profiles authorizing each target and the shared Keychain group, and the connected phone registered with the team. Xcode can manage these items. Apple account credentials, profiles and exported signing keys stay outside this repository and CI.

For a separately authorized install, select the unlocked, trusted iPhone as the run destination, enable Developer Mode if required, and run the IndependentCompanion scheme. For renewal, rebuild and sign with the same team, app identifiers and shared Keychain group, then install over this independent build. Inspect both signed entitlements with `codesign -d --entitlements :- <bundle>` for the app and its embedded extension. A different identity creates a separate data container. Device testing must cover permission prompts, signature validity, access to the saved key from the extension, and preservation of received files across renewal. [Apple device signing and run instructions](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices) · [Apple Keychain sharing](https://developer.apple.com/documentation/security/sharing-access-to-keychain-items-among-a-collection-of-apps)

## Connect, transfer and broadcast

Start the independent listeners on the desktop. On iPhone, enter its reachable LAN address, transfer port (default 47321), screen port (47322), and the desktop's random 64-character hexadecimal key, obtained through a trusted channel. Save, then tap **Test screen connection** while the phone app is foregrounded and allow Local Network access. The test authenticates the media listener before launching ReplayKit. Local Network permission can also be reviewed under Settings → Privacy & Security. [Apple local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy)

**Send a file** opens the system file picker. **Receive desktop’s offered file** writes the verified file to this app’s Documents folder, which appears in Files. Transfers work while the companion is in the foreground, including with screen broadcast off. Pause takes effect at the next chunk boundary. Cancelling the connection discards an incomplete incoming file. Retrying starts from the beginning. An existing filename causes a refusal. The maximum file size is 16 GiB. Each chunk is authenticated and the complete file is checked against the sender’s SHA-256 before publication.

Tap the system broadcast button and confirm **Start Broadcast** to share the screen. Stop in the system broadcast controls. ReplayKit supplies video to VideoToolbox. The encoder sends HEVC parameter sets on keyframes and RFC 7798 single NAL and fragmentation packets. Packets carry RTP timestamps and an orientation byte. A slow network drops input frames before encoding. App and microphone audio are outside this video channel. [ReplayKit sample handler](https://developer.apple.com/documentation/replaykit/rpbroadcastsamplehandler) · [VideoToolbox encoding](https://developer.apple.com/documentation/videotoolbox/encoding-video-for-low-latency-conferencing) · [RFC 7798](https://www.rfc-editor.org/rfc/rfc7798)

## Interoperability

Both TCP protocols exchange five ASCII magic bytes plus a fresh 32-byte nonce in each direction (client first). Each AES-256-GCM direction key is HMAC-SHA256 over the protocol magic, ASCII `-C` or `-S`, and the two nonces in client/server order, keyed with the pre-shared secret. Each record uses a four-zero-byte prefix and a 64-bit big-endian sequence number as its nonce, starting at zero in each direction. Its wire encoding is a four-byte big-endian ciphertext length, ciphertext, and 16-byte tag. The maximum plaintext length is 65,537 bytes. The pre-shared key must be generated randomly. The handshake does not provide forward secrecy.

File sessions use `PNFT1`. The phone sends type 1 plus an eight-byte size and a portable filename to upload, or type 2 to request a single desktop-selected file. For a download the desktop sends the same type 1 offer. The receiver accepts each offer and each type 4 data chunk with type 3. The sender ends with type 5 and the 32-byte file digest. Type 6 confirms successful publication.

Media sessions use `PNVM1`. A foreground probe sends byte 7 and expects byte 6. A broadcast starts with byte 0x20 plus the encoded width and height (two bytes each, big-endian) and expects byte 3. Each subsequent record is byte 0x21, an EXIF orientation byte (1–8), and one RTP packet of up to 1,200 bytes. A resolution change starts a new connection and encoder. The desktop must accept another media connection after each test or stream. [Apple Network framework](https://developer.apple.com/documentation/network/nwconnection) · [Apple CryptoKit](https://developer.apple.com/documentation/cryptokit/hmac)

