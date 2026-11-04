Pane 1.5.1 for Windows x64

- Fixes the phone-shaped native window by applying a persistent WinForms region to the actual Pane WebView window and disabling the rectangular DWM shadow.
- Window controls expand upward; Minimize replaces the three-line handle without overlapping the volume or phone buttons.
- Hold Home for 0.6 seconds to invoke Siri. A short click still goes Home.
- Notification Center and Control Center buttons toggle their panels closed on the next press. Opening gestures are serialized, including rapid clicks.
- Replaces the duplicate Gestures, Buttons and View controls in the connection overlay with a practical How to use Pane guide.
- Sizes the frame around the actual video area, including its bezel insets. Adapts to small model aspect-ratio differences, rotation and near-square/wider displays without a model list. iPhone Duo hardware compatibility is not yet verified.
- Retains USB/Wi-Fi Developer Mode control, Connect/Disconnect, and external AirPlay receiver setup for laptop audio.

Automatic updates: launch Pane, wait for the verified update, close normally and reopen. Verify Product version 1.5.1 in Pane.exe Properties > Details or the version in the connection panel.

Windows native tests inspect the actual HWND region before and after resize, plus hover-menu placement. UI tests exercise Home click/hold/cancel, panel toggles and failure recovery. Siri and system gestures still need verification on a physical iPhone; Siri must be enabled on the phone.
