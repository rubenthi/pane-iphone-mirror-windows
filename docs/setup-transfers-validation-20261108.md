# Setup, connections and transfers — November 8, 2026

## Direct Wi-Fi upload follow-up

Desktop 2.5.1 and companion 2.6.0 (6) add `wifi-upload-v1` for phone-to-laptop data. Bluetooth remains the control channel; its authenticated, encrypted handshake conveys a temporary TLS certificate fingerprint, one-time channel secret and private LAN endpoints. The phone pins the exact leaf certificate and authenticates inside TLS. The desktop listener exists only for the active file and closes on completion, cancellation or failure. The UI server remains loopback-only; this is a separate temporary TLS socket.

Bulk requests are 12-byte big-endian offset/length frames and replies contain a status byte, four-byte length and at most 256 KiB of raw data. No base64 or per-block Bluetooth file requests are required. Local controls, remote controls, final checksum and atomic delivery still apply. Wi-Fi interruption resumes over Bluetooth from the last fully written offset. Older companions retain the existing BLE path. This requires reachable local networking, iPhone Local Network permission and Windows firewall permission; no firewall policy is changed automatically.

Real loopback TLS tests exercise certificate fingerprints, channel authentication, malformed frames, cancellation, timeouts, bounds and an 8 MiB hash-verified transfer. Transfer integration tests cover Wi-Fi success, fallback before data, fallback after a completed block at the exact offset, and pause/cancel without publishing partial files. Host loopback speed is not evidence of iPhone radio throughput or a measured tenfold improvement. The updated companion must be built and installed before physical acceptance.

## Behavior

- Short illustrated iPhone Settings paths replace the longer trust and Developer Mode instructions. Detailed credential handling remains available under Password & privacy.
- Certificate recovery retains separate explicit confirmation and warns that replacement cannot be undone and may stop other apps using the old certificate.
- Settings uses grouped icon rows, chevrons, Back navigation and switches. Failure text presents a short description and a first action; diagnostic responses remain in the local API.
- Connect your iPhone starts a Wi-Fi attempt immediately. Volume wheel input is accumulated, bounded and sent through the ordered phone-control queue; disabled controls and zoom gestures do not send volume changes.
- A completed saved file binding reconnects automatically while Pane runs, with bounded retry delays. Explicit Disconnect pauses this until manual reconnect or the next app launch. First-time trust and system pairing remain user actions.
- The saved audio receiver runs while Pane is open when audio is enabled and a device is selected. This changes its lifecycle, not iOS's choice of audio route.
- File transfers use their own Bluetooth session and do not require the mirror. Pause/resume/cancel are available on both devices with the updated companion. Data stays private until size/hash verification and atomic delivery succeed.
- Transfer enhancements negotiate capabilities without changing protocol version 1. Larger acknowledged batches and negotiated ATT write sizes reduce transaction overhead. Physical throughput is not established by host tests.

## Verification scope

The isolated native Windows fixture measured resize presentation up to 118 ms in its recorded run, with 15 desktop samples and no sampled white points. It also checked clipping, transparency, all four anchored resize corners, minimize/restore, menus and controls. These are observations from a disposable native window with synthetic video; they do not establish every GPU, display or live-phone scenario.

Browser checks use disposable profiles and mock devices. Python transfer and lifecycle checks do not connect radios or install apps. Native Rust checks exercise the saved audio preference and desktop lifecycle without asserting audible phone playback.

## iPhone build and installation

The changed iPhone source declares marketing version 2.5.1 and build 5, matched by the desktop companion declaration. It includes an optional foreground-only Keep iPhone awake switch; normal idle locking resumes when Pane is no longer visible. Compiling and testing it requires Xcode on macOS. Until that exact source has passed the companion build workflow and its IPA is fetched and verified, the existing local IPA must not be described as this new companion. Installing it remains a separate user signing action. No release publication or automatic phone installation is implied by these source changes.

Mac run [42526219415](https://github.com/rubenthi/pane-iphone-mirror-windows/actions/runs/42526219415) passed the iPhone build and simulator tests at commit `1dba7e09aa02dfca503b40a007d904ee1758f5f7`. It tested Pause/Resume/Cancel in both directions, USB setup and the isolated keep-awake preference. The artifact ZIP checksum was verified before staging the IPA. The current Windows packaging changes do not change that tested iPhone source.

## Windows application

Local upload follow-up: the receive batch is independent of acknowledged Windows write size. A capable companion can provide 32 KiB per read even at low ATT MTU; legacy companions remain at 4 KiB. Unchanged full control snapshots are polled at most once per 750 ms during a file, while local actions, queue changes and the final pre-publication check bypass throttling. Incoming control rows omit redundant names/sizes; outgoing rows remain complete for compatibility. A deterministic 1 MiB test uses 32 reads and two control exchanges, validates exact received bytes, and exercises final cancellation. This measures application exchanges, not radio throughput. The iPhone source and bundled IPA are unchanged.

The local executable is version 2.5.0. `Pane.exe --development` uses the existing development profile and ports, has its own Windows application identity and Pane icon, and cannot apply production updates. The standard executable mode retains the production identity. Builds use a fresh temporary work directory so a locked previous cache is not deleted or reused. Installer, rollback and packaged smoke checks remain required before installation.
