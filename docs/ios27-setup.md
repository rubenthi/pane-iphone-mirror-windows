# iOS 27 setup

The complete step-by-step guide is built into Pane: open the sidebar arrow, then **iOS 27 setup guide**. It covers Windows/Chrome/Edge, Apple Devices, a data cable, Trust, Developer Mode, USB, input, Wi-Fi and troubleshooting. No Python is required for the executable.

## Developer Mode is missing: optional AltStore Classic route

Installing a development-signed app can help expose Developer Mode. This is an optional workaround, not a guaranteed fix for every iOS 27 device or managed phone. Pane itself does not require AltStore or an Apple Account.

1. Read [AltStore's official Windows installation guide](https://faq.altstore.io/altstore-classic/how-to-install-altstore-windows). Choose **AltStore Classic with AltServer**, not AltStore PAL.
2. Install the Apple-distributed iTunes and iCloud versions linked by that guide. Its standard instructions exclude Microsoft Store builds; consult its linked troubleshooting alternative if you must retain Store iCloud. Review compatibility before replacing an existing Apple setup.
3. Download AltServer for Windows from [altstore.io](https://altstore.io/), extract its ZIP, run Setup, then launch AltServer as administrator. Permit private-network access if needed on your trusted network.
4. Connect and unlock the phone, approve Trust, and enable iTunes Wi-Fi sync.
5. From AltServer's tray icon, choose **Install AltStore → your iPhone**. Complete Apple Account authentication yourself in AltServer. Never enter those credentials in Pane or a support report.
6. Once installed, on the phone open **Settings → General → VPN & Device Management** (the label may vary), and trust your own developer profile. Try opening AltStore.
7. Revisit **Settings → Privacy & Security → Developer Mode**. Enable it, restart, and confirm after unlocking. Return to Pane's Cable connection.

If the switch is still missing, do not assume installation succeeded or that restrictions were removed. Check AltStore's installation errors and [Apple's Developer Mode guidance](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device). A managed device may require its administrator. This workaround has not been hardware-verified by this fork on iOS 27.

If you keep using AltStore with a free Apple Account, sideloaded apps generally require refreshing within seven days; see [AltStore's getting-started guide](https://faq.altstore.io/altstore-classic/your-altstore). That maintenance requirement belongs to AltStore, not Pane's Windows updater.
