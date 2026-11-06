# Pane companion

SwiftUI iPhone/iPad app, iOS 17+. It exposes Photos/Files pickers and an encrypted CoreBluetooth peripheral service for two-way file transfer. It deliberately has no microphone permission or media playback/capture subsystem.

Generate the Xcode project with `cd ios && xcodegen generate`. Use Xcode with your signing team for device builds. The companion workflow produces an unsigned IPA for AltStore signing. Full setup, signing and transfer instructions are in [the setup guide](../docs/companion-setup.md).

## Protocol v1

USB provisioning assigns a random 128-bit BLE service UUID per binding. Discovery uses that UUID, because iOS may truncate or omit the advertised name. The write-with-response command characteristic is `8a5d1001-7b44-4b1b-9bb6-a42e447a0001`; the encrypted notify characteristic is `8a5d1002-7b44-4b1b-9bb6-a42e447a0001`. Requests and replies are UTF-8 JSON followed by LF, fragmented at the negotiated ATT MTU. Frames are limited to 64 KiB and file data chunks to 4096 bytes. Writes use responses; notifications use CoreBluetooth readiness backpressure. One request is in flight at a time, correlated by integer `request`.

USB provisioning writes `Documents/pane-pairing.json` with protocol `version`, a random 256-bit `token`, advertised `peerName`, and random `service` UUID. Activation consumes this file into protected Application Support storage. The laptop sends `hello` with the token only over encrypted GATT, then uses `list`, `read`, `received` for phone-to-laptop transfers, or `begin`, `write`, `finish` for laptop-to-phone transfers. Metadata includes ID, safe name, byte count and SHA-256. Acknowledgement occurs only after verified delivery. No arbitrary filesystem paths are accepted from the peer. Keep the app foregrounded; this release does not claim background transfers.
