# Pane companion

SwiftUI iPhone/iPad app, iOS 17+. It exposes Photos/Files pickers and an encrypted CoreBluetooth peripheral service for two-way file transfer. It deliberately has no microphone permission or media playback/capture subsystem.

Generate the Xcode project with `cd ios && xcodegen generate`. Use Xcode with your signing team for device builds. The companion workflow produces an unsigned IPA for the integrated Pane signer or optional AltStore signing. Full setup, signing and transfer instructions are in [the setup guide](../docs/companion-setup.md).

The Transfers screen uses Apple's SwiftUI Liquid Glass button style on iOS 26 and later, with standard controls on iOS 17 and 18. Tap the laptop row for USB setup. The macOS workflow builds the device IPA and exercises the transfer controls and pairing sheet on an iPhone simulator.

## Protocol v1

USB provisioning assigns a random 128-bit BLE service UUID per binding. Discovery uses that UUID, because iOS may truncate or omit the advertised name. The write-with-response command characteristic is `8a5d1001-7b44-4b1b-9bb6-a42e447a0001`; the encrypted notify characteristic is `8a5d1002-7b44-4b1b-9bb6-a42e447a0001`. Requests and replies are UTF-8 JSON followed by LF, fragmented at the negotiated ATT MTU. Frames are limited to 64 KiB and file data chunks to 4096 bytes with legacy peers or 32768 bytes when both sides advertise `chunk-32768`. Writes use responses; notifications use CoreBluetooth readiness backpressure. One request is in flight at a time, correlated by integer `request`.

USB provisioning writes `Documents/pane-pairing.json` with protocol `version`, a random 256-bit `token`, advertised `peerName`, and random `service` UUID. Activation consumes this file into protected Application Support storage. The laptop sends `hello` with the token only over encrypted GATT, then uses `list`, `read`, `received` for phone-to-laptop transfers, or `begin`, `write`, `finish` for laptop-to-phone transfers. Metadata includes ID, safe name, byte count and SHA-256. Acknowledgement occurs only after verified delivery. No arbitrary filesystem paths are accepted from the peer. Keep the app foregrounded; this release does not claim background transfers.


The approved blue icon is generated from `handset/web/logo.svg` into the iOS asset catalog and Windows packaging assets with `node packaging/build-icons.cjs` (development dependencies and Chromium required). AppIcon is explicitly selected in `project.yml`.

The updated interface uses native material, a shared blue accent and connection-triggered symbol motion that respects Reduce Motion. USB-binding checks run only while the app is active; all transfer limits, protocol fields, protected pairing storage, progress and Share actions remain unchanged.

Windows now has a separate optional Rust helper for A2DP reception and ANCS notifications. The iOS app still has no microphone/media capture subsystem or arbitrary cross-app notification access. Keep it foregrounded for files. Background system notifications do not imply background file transfers.


Companion 2.5.1 (build 5) adds negotiated `transfer-control-v1`. `hello` retains protocol version 1 and adds a capability array; old peers continue using the existing operations and 4096-byte chunks. Updated Windows sends a bounded `controls` snapshot of active transfers plus explicit pending controls; replies return states keyed by the wire file ID. `paused` retains the private partial and acknowledged offset, yielding the serial RPC slot so other files and controls continue. Both apps can pause, resume, or cancel queued and active transfers independently of screen mirroring. Cancel closes/removes private partials; only verified complete files are published. Actions take effect at acknowledged batch boundaries; this does not claim instantaneous cancellation during a disconnected or timed-out RPC.

The phone retains up to eight inbound partial handles keyed by file ID, avoiding replacement of a paused file when another begins. Partial handles are discarded on Bluetooth disconnect; Windows resets a suspended outbound file to byte zero before reconnecting. Process restarts discard private partials rather than claiming durable resume. These source changes require a new Mac/Xcode companion build; an older bundled IPA does not contain these features. No hardware throughput measurement is implied by the larger negotiated batches.

With a legacy companion, pausing an outbound file reserves its single inbound slot: other laptop-to-phone files wait, while phone-to-laptop files and Windows controls continue. This avoids overwriting the paused legacy partial. Updated companions use independent inbound slots.

Keep iPhone awake is enabled by default while Pane is visible. Its connection-sheet switch is saved locally. Scene changes and view dismissal restore the idle timer; this is not a background Bluetooth entitlement. Simulator UI preference tests use a separate defaults suite.
