# Desktop features and verification

## Audio design

The pinned pymobiledevice3 11.49.4 implementation of
`ScreenStreamServer._missing_audio_deps` rejects non-macOS platforms because its
AAC-ELD decoder uses AudioToolbox. Simply enabling `audio_default_on` does not
add Windows audio.

Pane uses Windows.Media.Audio.AudioPlaybackConnection through a bundled Windows
PowerShell helper. Windows handles A2DP decoding and playback; Python does not
decode PCM, record a microphone, or transcode video. Device discovery is
user-triggered. The helper blocks while idle and receives status commands only
while the UI is connecting/connected. Closing Pane releases the connection.
Bluetooth pairing and selecting the laptop's output route are required.
The default Windows output must be Speakers for laptop-speaker playback.
A connected state is not proof of exclusive acoustic output.

Microsoft API references:
- https://learn.microsoft.com/uwp/api/windows.media.audio.audioplaybackconnection
- https://learn.microsoft.com/uwp/api/windows.media.audio.audioplaybackconnection.open
- https://learn.microsoft.com/uwp/api/windows.media.audio.audioplaybackconnection.trycreatefromid

The helper sends device IDs over stdin as JSON, never as shell code. Only IDs
returned by a discovery operation can be connected. The local API uses the same
origin/token checks as other Pane controls. It does not automatically pair
devices or alter system-wide audio settings.

## Input behavior

Navigation starts with Space mapped to Home. A printable character enters typing
mode; F2 also switches modes. Space stays a literal space until F2, Esc or Home
returns to navigation. This explicit state avoids unreliable idle-time guesses.
The display/HID transport has no remote text-field focus signal.

Ctrl+V uses a browser paste event so clipboard permission prompts are not needed
for normal keyboard paste. The Paste button uses the browser Clipboard API and
directs users to Ctrl+V if access is denied. Text (including Unicode/newlines)
and PNG files are supported up to 1 MiB. A single control transaction releases
modifiers, sets the phone pasteboard, sends Cmd+V, then releases modifiers.
If the clipboard write fails, Cmd+V is never sent against stale phone content.
There is no clipboard polling or automatic uploading.

## Performance evidence

In a JavaScript execution test, a 4,194,308-byte framed payload delivered in
4 KiB fragments caused:
- Previous merge-per-read algorithm: 2,153,775,108 copied bytes.
- New reusable packet reader: 12,517,380 copied bytes.
- Reduction in this workload: 99.42%.

The payload length and byte contents were checked. This measures packet assembly
only, not total CPU, memory, battery, latency or FPS on a real laptop. The buffer
grows geometrically up to a 32 MiB packet limit and reuses storage; tests exercise
split headers, multiple packets, invalid lengths and truncation.

Rendering retains the full decoded dimensions and source frame stream. No
resolution, bitrate or frame-rate setting was reduced. The browser can skip
presentation of superseded frames as before. Backpressure waits for the decoder
instead of feeding an unbounded queue. Restart/unload closes readers, decoders
and frames; status DOM/message updates happen only on changes. Drag events keep
the newest pending position instead of queuing every mouse movement.

## Automated checks and hardware acceptance

CI runs Python lifecycle/API tests, JavaScript packet/input/clipboard tests,
Windows PowerShell parsing/API availability, native WebView2 overlay/input
checks and a packaged development build. Synthetic UI tests do not verify a
physical iPhone or Bluetooth audio.

Before releasing:
1. Pair an iPhone and play media. Connect audio, select the laptop on iOS and
   Speakers in Windows. Verify laptop playback and no iPhone-speaker playback.
   Check video over both USB and Wi-Fi, pause/resume, volume and disconnect.
2. Unplug/reconnect Bluetooth and close/reopen Pane; confirm the connection
   indicator follows the link and no helper process is left running.
3. Paste Unicode, multiline text and a PNG into compatible iPhone apps.
   Confirm the iOS clipboard actually changes and paste errors are visible.
4. Check Space Home, F2, leading spaces, regular text, IME, local form fields,
   held modifiers, overlay opening and rapid switching between typing/navigation.
5. Compare the previous build on the same laptop/phone/app for five minutes:
   Task Manager CPU/memory, GPU decode, frame rate, latency and rotation/restart.
   Record Windows build, GPU, iOS version, transport and Bluetooth adapter.
6. Check shaped-window hit testing, overlay scrolling, portrait/landscape,
   100/150/200% DPI, moving between monitors and small displays.

The development workspace failed to provision during authoring. Local Python,
Windows and physical-device tests were therefore unavailable; CI results are
reported separately in the pull request. No hardware performance or audio
acceptance result is claimed here.
