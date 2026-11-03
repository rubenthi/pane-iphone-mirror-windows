# Choose a control method

This development version preserves **Developer Mode** touch/keyboard control and
adds **Bluetooth cursor** control. Select the method in the connection sidebar.
Switching to Bluetooth stops the developer stream. Switching back stops the
Bluetooth cursor. Audio and notifications remain independent of that choice.

## What is implemented

| Feature | Implementation | Limits / verification |
| --- | --- | --- |
| Existing touch, gestures, keyboard and video | Original USB/Wi-Fi developer service | Still requires Developer Mode and the existing compatible iOS version. |
| Bluetooth cursor | Native Windows BLE HID mouse peripheral, relative motion, three buttons and wheel | Requires an adapter/driver with peripheral support, pairing, and iPhone AssistiveTouch. No keyboard or absolute touch injection in this mode. Hardware unverified. |
| Video without Developer Mode | Your separate Windows AirPlay receiver | Receiver is not bundled. Use its window beside Pane, or optionally capture its window into Pane when the browser permits. |
| Media audio on laptop | Windows `AudioPlaybackConnection` A2DP sink | Pair and select PC as iPhone audio output. Windows controls the laptop output endpoint. Hardware unverified. |
| Laptop microphone / calls | Handoff to Microsoft Phone Link → Calls | **Not a native Pane microphone implementation.** Requires Phone Link setup and supported Bluetooth hands-free calls. Not general microphone injection into iPhone apps. |
| iPhone notifications on laptop | ANCS over paired BLE, displayed in Pane sidebar | Requires iPhone authorization and service availability. Previews are controlled by iOS. No native Windows toast integration. Hardware unverified. |

Windows 10 version 2004+ or Windows 11 is required for the native media API.
Phone Link for iPhone has its own Windows/iOS requirements. Developer Mode is
not required for Bluetooth HID, ANCS or media playback; enabling Bluetooth does
not make the existing developer video service work without it.

## Bluetooth cursor + AirPlay

1. Install and start a Windows AirPlay receiver you trust. Keep phone and laptop
   on the same Wi-Fi network. Choose the receiver in iPhone Control Center →
   Screen Mirroring.
2. Open Pane's sidebar and choose **Bluetooth cursor · AirPlay receiver**.
3. Click **Start cursor pairing**. Pair the Windows PC in iPhone Bluetooth
   settings. The PC uses its Windows Bluetooth name, not necessarily “Pane”.
4. Enable iPhone **Settings → Accessibility → Touch → AssistiveTouch**. Wait for
   a subscribed cursor client to appear and choose **Use selected cursor client**.
   With multiple clients, select the intended phone explicitly; input is never
   broadcast to every subscriber.
5. Move over Pane's pad, click, drag or scroll. This behaves like a relative
   Bluetooth mouse, not a coordinate-matched touchscreen. Use AssistiveTouch's
   menu for Home and other system actions.
6. Optionally choose **Show receiver window**, then select only the receiver's
   window in the capture picker. This is a local preview of that window, not an
   AirPlay implementation. If WebView2 does not offer capture, use the receiver
   beside Pane or open `http://127.0.0.1:8765` in Edge/Chrome. Capture audio is
   disabled to avoid duplicating the Bluetooth audio path.

Input is released on focus loss, pointer cancellation and mode changes. A native
watchdog releases held buttons after 1.5 seconds without input. Close Pane or
press **Stop cursor** to stop advertising. Pairing remains in Windows/iOS until
you remove it in system settings.

## Laptop audio and microphone (either control mode)

1. Pair the iPhone and PC in Windows Bluetooth settings. Press **Refresh Bluetooth
   devices**, select the phone under Media audio and press **Connect audio**.
2. On iPhone, select the PC as the audio output. In Windows Sound settings, select
   the laptop speakers or headphones. Pane does not change the global Windows
   output device. Leave the iPhone media volume audible; startup no longer sends
   volume-down events that could silence the Bluetooth stream.
3. AirPlay receivers can retain the audio route. Use a receiver's video-only
   option if supported and verify the iPhone output selector. Simultaneous
   AirPlay video and Bluetooth audio depends on the receiver/iOS combination.
   Muting the phone's media volume is not an audio-routing solution.
4. For calls, choose **Open Phone Link for calls**, complete its iPhone pairing
   and Calls setup, then select laptop microphone and speakers. A2DP carries
   media toward the PC; hands-free calling uses a separate connection. Pane
   neither registers restricted phone-call capabilities nor reports Phone Link's
   microphone as connected. Calls may interrupt media playback.

Bluetooth disconnection can cause iOS to return sound to the phone. Pane cannot
guarantee that the phone will remain silent after the audio connection is lost.

## Notifications (either control mode)

Choose the paired iPhone under Notification device, then **Connect notifications**.
Approve the iPhone prompt and enable **Share System Notifications** for the PC
in its Bluetooth settings where offered. BLE, audio and cursor IDs differ;
select the same phone explicitly in each section.

Notifications are delivered automatically while that subscription remains active.
Pane handles additions, changes and removals, and requests title/message details
when ANCS exposes the optional characteristics. At most 100 entries remain in
memory. Disconnect clears them; they are not written to logs or disk. Notification
text is rendered as text, never HTML. Notification actions/replies and Windows
Action Center toasts are not implemented. If iOS changes the ANCS service, denies
access or Bluetooth drops, the panel reports it and requires reconnecting.

## Build and run

Install Python 3.12 and the .NET 8 SDK on Windows, then from the repository root:

```powershell
pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-bluetooth.ps1
python -m handset.app
```

`packaging/build.ps1` now builds and embeds the self-contained Windows x64 helper
before PyInstaller packages Pane. No .NET runtime installation is required on the
destination machine. `native/Pane.Bluetooth.exe` is generated, not tracked.

The helper has no HTTP listener. Pane communicates through owned process pipes;
the existing same-origin/token checks protect all Bluetooth HTTP endpoints.
Settings links are allowlisted. Commands validate payloads and the helper only
connects to device IDs returned by its own enumeration. No Bluetooth addresses,
notification text or pairing secrets are persisted by this implementation.

## Validation

Automated checks cover HTTP authorization, command validation, helper failures,
ANCS request framing, every response fragmentation split, malformed/oversized
responses, cursor report limits, UI mode changes, releases and notification text
escaping. The native helper cross-compiles for Windows x64. These checks do not
prove radio operation, iOS interoperability, audio latency, AirPlay routing or
Phone Link microphone support. Validate on the target Windows laptop/iPhone
before making this a release.

```powershell
python -m unittest discover -s tests -v
npm test
dotnet run --project native/Pane.ProtocolTests -c Release
npm ci --ignore-scripts
npx playwright install chromium
node tests/bluetooth-ui.cjs
```

Physical acceptance: test each mode, click/drag/scroll and focus-loss release;
check real media at the laptop; perform a call through Phone Link and confirm
the laptop microphone; add/change/remove a notification; then disconnect/reconnect
Bluetooth and confirm connection indicators, history clearing and audio fallback.

## Platform references

- [Microsoft: Bluetooth GATT server](https://learn.microsoft.com/en-us/windows/apps/develop/devices-sensors/gatt-server)
- [Microsoft: receive Bluetooth audio](https://learn.microsoft.com/en-us/windows/apps/develop/media-playback/enable-remote-audio-playback)
- [Apple: ANCS specification](https://developer.apple.com/library/archive/documentation/CoreBluetooth/Reference/AppleNotificationCenterServiceSpecification/Specification/Specification.html)
- [Microsoft: phone-line transport access capability](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice.requestaccessasync)
