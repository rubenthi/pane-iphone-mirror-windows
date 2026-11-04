Pane 1.6.0 for Windows x64

- Adds a bundled Windows Bluetooth audio receiver. Pair once, select the iPhone once if it cannot be uniquely identified, and Pane automatically opens its remembered audio connection while mirroring. Initial pairing approval remains required; if iOS retains another audio route, selecting this PC once may still be necessary. AirPlay remains an optional manual route; no external Bluetooth receiver app is needed.
- Clips the WebView2 child renderer windows as well as the parent, requests a transparent WebView background, and repairs clipping when renderer windows are recreated. Windows tests verify actual desktop pixels outside the phone and rail, including after resizing.
- Uses one symmetric 7px bezel and explicitly positioned video to eliminate uneven inset/baseline spacing. Continues adapting to live phone dimensions.
- App Switcher, Notification Center and Control Center now send Home on a consecutive repeat click. A different button or manual input resets the repeat action; changing between buttons no longer injects an extra Home.
- Reduces motion-time keyframe pressure, enables per-frame receiver feedback over USB, prefers hardware decoding, avoids repeated network-buffer copies and bounds the decode backlog.
- Shows measured received/displayed FPS and live resolution in the connection panel. 60 FPS is a target, not a guaranteed lock: iOS controls the encoder and may reduce frame rate or resolution. Native HEVC video is decoded without an extra transcoding step. Use USB for the most stable results.

Windows build, native desktop/UI tests, audio-helper packaging checks, regression tests and updater checks run before publication. Physical iPhone audio routing, sustained FPS, and iPhone Duo compatibility still require device verification. Bluetooth A2DP handles media playback; it does not provide an iPhone microphone or call route.

Automatic updates: launch Pane, wait for the verified download, close normally and reopen. Verify Product version 1.6.0 in Pane.exe Properties > Details.
