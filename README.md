> **Pane Bluetooth — local development fork.** Forked from
> `rubenthi/pane-iphone-mirror-windows` at `a4e7aa1`, with both Developer Mode
> control and Bluetooth cursor control available in the sidebar. This archive
> is source code, not a released `Pane.exe`. A separate GitHub repository has not
> been published. Automatic updates are disabled so the original project's
> release cannot overwrite this fork. Follow [the Bluetooth setup/build guide](docs/bluetooth.md).
> The original project's README and license are retained below for attribution;
> its download/release links and clone command refer to the original project.

<p align="center">
  <img src="handset/web/logo.svg" width="120" alt="Pane logo - iPhone screen mirroring for Windows">
</p>

<h1 align="center">Pane — Mirror and Control Your iPhone from a Windows PC</h1>

<p align="center">
  <b>Free, open-source iPhone screen mirroring and remote control for Windows 10 &amp; 11.</b><br>
  See your iPhone screen live on your PC, tap and swipe with the mouse, and type with your computer keyboard —<br>
  over a USB cable <i>or</i> wirelessly over Wi-Fi. No jailbreak, no Mac, no subscription.
</p>

<p align="center">
  <a href="../../releases/latest"><b>⬇ Download Pane.exe for Windows</b></a>
  ·
  <a href="#features">Features</a>
  ·
  <a href="#quick-start">Quick start</a>
  ·
  <a href="#faq">FAQ</a>
</p>

---

**Pane** is like [scrcpy](https://github.com/Genymobile/scrcpy), but for **iPhone on Windows**. It streams the iPhone display to your desktop in real time and sends your mouse clicks, swipes and key presses back to the phone, so you can use iOS apps, reply to messages, play games, record demos or present your phone screen from your laptop or PC.

It is an alternative to paid tools such as ApowerMirror, LonelyScreen, Reflector, AirServer, iMyFone MirrorTo and Phone Link for iPhone — but free, private (everything stays on your own computer and network), and with full touch control instead of view-only AirPlay.

## Features

**Development preview: two control methods.** The connection sidebar now offers
the existing Developer Mode touch/keyboard path and a Bluetooth cursor path used
with a separate AirPlay receiver. Both can use Bluetooth media playback and
iPhone notifications. Calls and laptop microphone use are handed off to Phone
Link; native microphone injection is not implemented. These new Bluetooth paths
are not yet hardware-verified. See [setup, limits and build instructions](docs/bluetooth.md).

- 📱 **Live iPhone screen mirroring on Windows**: low-latency HEVC (H.265) video decoded in hardware.
- 🖱️ **Control the iPhone with your mouse**: tap, long-press, drag and swipe directly on the mirrored screen.
- ⌨️ **Type on your iPhone with the PC keyboard**: real keystrokes, including Ctrl+C / Ctrl+V / Ctrl+A / Ctrl+Z mapped to ⌘ shortcuts.
- 📶 **Wireless mirroring over Wi-Fi**: pair once over USB, then go cable-free on the same network.
- 🔌 **USB cable mode**: the most stable, lowest-latency connection.
- 🏠 **Hardware buttons & gestures**: Home, App Switcher, Lock/Power, Siri, Volume up/down, Mute, Notification Center, Control Center, back/forward swipes.
- 🖥️ **Realistic iPhone frame** with fit-to-window, zoom, rotate and **full-screen touch mode**.
- 🔁 **One-click restart** if the stream ever freezes.
- 🪟 **Single portable `Pane.exe`**: no Python, no installer, no account.
- 🔒 **Local mirroring**: video and input stay on USB/your local network. Updates check this GitHub fork; initial developer-image setup may download Apple resources.

## This fork's release and updater

Version 1.2.1 adds a native, phone-shaped floating window and an expandable connection sidebar. Open its arrow, then the iOS 27 setup guide for prerequisites, USB/Wi-Fi instructions, and the optional AltStore Classic fallback for a missing Developer Mode setting. The outline follows the live display aspect ratio; before video starts it uses a standard portrait shape. It is not an exact physical bezel/camera-cutout replica of every model. Automatic updates check only this fork, verify executable size and SHA-256, and apply after closing Pane. An existing executable is retained as `Pane.exe.backup-*`; timeout or verification failure leaves it unchanged. Download `install.ps1` from the release and run it with PowerShell to install under `%LOCALAPPDATA%\Programs\Pane` and create a desktop shortcut.

The pinned screen-streaming library requires **iOS 27+**. The older iOS 17+ claim described tunnel support, not verified display streaming. Physical USB/Wi-Fi mirroring and input must be tested with a compatible phone; automated tests use local stand-ins.

## Tested devices and iOS versions

See the [compatibility and verification table](docs/compatibility.md). A connected iPhone19,3 on iOS 27.0.1 was detected with Developer Mode enabled, but video, mouse/keyboard, and Wi-Fi have not yet been verified. No phone combination is labeled fully verified without evidence. Submit results through the device-verification issue template.

This repository is public and licensed under GPL-3.0: anyone can view or fork it under the license terms.

## Quick start (Developer Mode control)

1. **Download** `Pane.exe` from the [latest release](../../releases/latest).
2. Install Apple's USB driver by installing **[Apple Devices](https://apps.microsoft.com/detail/9np83lwlpz9k)** (or iTunes) from the Microsoft Store.
3. Plug the iPhone into the PC, unlock it and tap **Trust This Computer**.
4. Turn on **Developer Mode** on the iPhone: *Settings → Privacy & Security → Developer Mode → On* (the iPhone restarts).
   If the option is missing, do not assume Pane can enable it; follow Apple's Developer Mode setup guidance.
5. Run **Pane.exe**, open the sidebar arrow, choose **Cable**, and click **Start mirroring**. The built-in guide and [AltStore fallback instructions](docs/ios27-setup.md) are available if setup is incomplete.

### Go wireless (Wi-Fi)

1. While the iPhone is connected by cable, switch Pane to **Wi-Fi** and click **Set up Wi-Fi** (one-time pairing).
2. Unplug the cable. Keep the PC and iPhone on the **same Wi-Fi network** and the iPhone unlocked.
3. Click **Start mirroring**.

> Tip: if the iPhone isn't found over Wi-Fi, set the Windows network profile to **Private** and make sure the router doesn't isolate wireless clients.

## Controls

| Action on PC | Result on iPhone |
| --- | --- |
| Left click / drag | Tap / swipe |
| Swipe up from the bottom edge | Go Home (pause before releasing for the App Switcher) |
| Right click | Home |
| Keyboard | Types into the focused text field |
| Ctrl + C / V / X / A / Z | Copy / Paste / Cut / Select all / Undo |
| Side buttons on the frame | Lock, Volume up/down, Mute |

## Requirements

- Windows 10 or Windows 11 (64-bit)
- Microsoft Edge WebView2 Runtime (native window); Chrome or Edge is a fallback if the runtime is unavailable
- For the existing developer video/control path: iPhone or iPad running **iOS / iPadOS 27 or newer** with Developer Mode enabled. Bluetooth cursor + external AirPlay does not use that service; see the [Bluetooth guide](docs/bluetooth.md).
- Apple Devices app or iTunes (for the USB driver)

## Run from source

```powershell
git clone https://github.com/rubenthi/pane-iphone-mirror-windows.git
cd pane-iphone-mirror-windows
pip install -r requirements.txt
python -m handset.server      # then open http://127.0.0.1:8765
```

### Build the Windows EXE

```powershell
pip install pyinstaller pillow
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # -> dist\Pane.exe
```

## How it works

Pane uses [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) to open a secure RemoteXPC / RSD tunnel to the iPhone (over USB, or over Wi-Fi via Bonjour remote pairing), starts the iOS screen-capture service, and streams the HEVC video to a local web UI that decodes it with WebCodecs. Touches, buttons and keystrokes are sent back as HID events. Everything runs locally on `127.0.0.1`.

```
iPhone ──USB / Wi-Fi tunnel──▶ Pane server (Python) ──localhost──▶ App window (WebCodecs + HID input)
```

## FAQ

**Can I mirror my iPhone to Windows for free?**
Yes. Pane is free and open source (GPL-3.0).

**Can I control my iPhone from my PC, not just view it?**
Yes. Unlike AirPlay receivers, Pane sends real touch, button and keyboard input to the iPhone.

**Does it work without a cable?**
Yes. After a one-time USB pairing, Pane mirrors and controls the iPhone over Wi-Fi on the same network.

**Do I need to jailbreak my iPhone?**
No. Pane uses Apple's built-in developer services. You only need Developer Mode turned on.

**Do I need a Mac or Xcode?**
No. Everything runs on Windows.

**Why does it need Developer Mode?**
iOS only exposes screen streaming and input injection through its developer services, which require Developer Mode. You can turn it off again at any time.

**Windows SmartScreen warns about Pane.exe — is it safe?**
The executable isn't code-signed yet, so Windows shows a warning for new downloads. Click *More info → Run anyway*, or build it yourself from source.

**Is my data sent anywhere?**
No. The video and input stay between your iPhone and your PC.

## Keywords

iPhone screen mirroring Windows · mirror iPhone to PC · control iPhone from PC · iPhone remote control Windows 11 · iOS screen mirror Windows · scrcpy for iPhone · scrcpy iOS alternative · iPhone to laptop screen share · use iPhone on computer · type on iPhone with PC keyboard · wireless iPhone mirroring Wi-Fi · USB iPhone mirror · free ApowerMirror alternative · open source iPhone mirroring · no jailbreak

## License

Pane is licensed under the [GNU General Public License v3.0](LICENSE).
Not affiliated with or endorsed by Apple Inc. iPhone, iOS and AirPlay are trademarks of Apple Inc.

See [1.2.1 release validation](docs/release-validation-1.2.1.md) for published checksums and the verified 1.1.1 → 1.2.1 updater transition.


### Floating controls in 1.3.0

Drag the three-line handle above the side controls to move Pane. Hover it to reveal minimize, maximize/restore and close. Drag the bottom-right resize grip to resize the phone proportionally. Volume buttons sit above the connection arrow; Home, app switcher, Notifications and Control Center sit below. Hover each button for its tooltip. Connection and error messages are in the sidebar, never over the phone. In Developer Mode, scroll over the mirrored picture to swipe; the sidebar scrolls independently. Bluetooth media audio is configured separately in the sidebar; the developer video tunnel remains video-only.
