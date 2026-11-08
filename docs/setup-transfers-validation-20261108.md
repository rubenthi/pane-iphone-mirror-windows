# Setup, connections and transfers — November 8, 2026

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

The changed iPhone source declares marketing version 2.5.0 and build 4, matched by the desktop companion declaration. Compiling and testing it requires Xcode on macOS. Until that exact source has passed the companion build workflow and its IPA is fetched and verified, the existing local IPA must not be described as this new companion. Installing it remains a separate user signing action. No release publication or automatic phone installation is implied by these source changes.
