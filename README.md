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

- 📱 **Live iPhone screen mirroring on Windows**: low-latency HEVC (H.265) video decoded in hardware.
- 🖱️ **Control the iPhone with your mouse**: tap, long-press, drag and swipe directly on the mirrored screen.
- ⌨️ **Type on your iPhone with the PC keyboard**: real keystrokes, including Ctrl+C / Ctrl+V / Ctrl+A / Ctrl+Z mapped to ⌘ shortcuts.
- 📶 **Wireless mirroring over Wi-Fi**: pair once over USB, then go cable-free on the same network.
- 🔌 **USB cable mode**: the most stable, lowest-latency connection.
- 🏠 **Hardware buttons & gestures**: Home, App Switcher, Lock/Power, Siri, Volume up/down, Mute, Notification Center, Control Center, back/forward swipes.
- 🖥️ **Realistic iPhone frame** with fit-to-window, zoom, rotate and **full-screen touch mode**.
- 🔁 **One-click restart** if the stream ever freezes.
- 🪟 **Single portable `Pane.exe`**: no Python installation required.
- 🔒 **Local mirroring**: video and input stay on USB/your local network. Updates check this GitHub fork; initial developer-image setup may download Apple resources.

## Pane 2.2: floating interface, guided setup and preserved settings

See the [update history](CHANGELOG.md) for what each version adds, how automatic updates work, and behavior changes.

Updates preserve existing preferences, browser profiles, signing data and saved phone pairings. A reset happens only when explicitly requested with `Pane.exe --reset`. The iPhone volume controls remain; startup no longer lowers the volume and no sound is streamed to the PC.

The custom native phone-shaped window and joined control rail from 1.7.4 are restored. The Connection panel overlays the phone screen without widening the window. A full setup guide opens automatically only when no saved phone pairing exists: USB trust, Developer Mode reveal and iPhone confirmation, installation of **Pane**, then USB/Wi-Fi/Bluetooth binding. The second tab, **Uploads**, sends files both ways over Bluetooth Low Energy. Incoming files are verified and saved to the laptop's Downloads folder without overwriting existing files. Keep the iPhone companion open during transfers.

See the [complete setup and signing guide](docs/companion-setup.md). GitHub Actions produces the [unsigned companion IPA](../../actions/workflows/companion.yml) for AltStore signing and the [Windows executable](../../actions/workflows/desktop-check.yml). A source update on main is not itself an installed laptop update. Automatic updates check published releases at launch and every six hours while Pane stays open, retry after fifteen minutes on failure, and install the verified executable when Pane closes. Open Pane again to use the new version. Version bumps merged into main trigger a tested release publication; ordinary source-only commits do not publish a new version.

The companion requires Apple signing, supported directly in Pane with a free or paid Apple Account. Pane can sign and install its companion using your Apple Account through its bundled isideload helper. Passwords are not saved; certificates and authentication-support data are encrypted with Windows DPAPI. Complete Windows builds include the unsigned Pane companion. Free-account apps generally need refreshing every seven days. File sharing requires iOS 17+ and a Windows BLE adapter. The pinned screen-streaming library requires **iOS 27+**.

## Tested devices and iOS versions

See the [compatibility and verification table](docs/compatibility.md). A connected iPhone19,3 on iOS 27.0.1 was detected with Developer Mode enabled, but video, mouse/keyboard, and Wi-Fi have not yet been verified. No phone combination is labeled fully verified without evidence. Submit results through the device-verification issue template.

This repository is public and licensed under GPL-3.0: anyone can view or fork it under the license terms.

## Quick start

1. Launch the Windows build. Existing settings and paired phones are preserved; new installations open the full setup guide.
2. Install **Apple Devices** for its USB driver, plug in the unlocked iPhone and tap **Trust This Computer**.
3. Press **Connect** in the guide. Pane requests the Developer Mode switch.
4. On the iPhone, enable **Settings → Privacy & Security → Developer Mode**, restart the iPhone and confirm **Turn On**. Reconnect USB, then press **I've enabled it — check**.
5. Choose **Sign & install with Pane**, enter your Apple Account and complete verification.
6. Pane binds USB and Wi-Fi automatically after installation. Open Pane on the iPhone, trust your developer profile if prompted, allow Bluetooth and accept pairing prompts. Keep the app open.
7. Once Bluetooth confirms the connection, the guide closes and Pane opens the normal interface. Use **Uploads** for files and **Connect** for mirroring. See [setup details and limitations](docs/companion-setup.md).

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
- iPhone or iPad running **iOS / iPadOS 27 or newer** with Developer Mode enabled
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

Pane uses [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) to open a secure RemoteXPC / RSD tunnel to the iPhone (over USB, or over Wi-Fi via Bonjour remote pairing), starts the iOS screen-capture service, and streams the HEVC video to a local web UI that decodes it with WebCodecs. Touches, buttons and keystrokes are sent back as HID events. The desktop UI binds to `127.0.0.1`. The companion exchanges files through encrypted BLE GATT, with a pairing secret provisioned over trusted USB.

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
Pane signs and installs the bundled companion directly on Windows using its isideload helper. No separate AltStore or local Xcode installation is needed. Building the Swift companion from source uses the macOS CI build or a Mac with Xcode.

**Why does it need Developer Mode?**
iOS only exposes screen streaming and input injection through its developer services, which require Developer Mode. You can turn it off again at any time.

**Windows SmartScreen warns about Pane.exe — is it safe?**
The executable isn't code-signed yet, so Windows shows a warning for new downloads. Click *More info → Run anyway*, or build it yourself from source.

**Is my data sent anywhere?**
Video, input and transferred files stay between your iPhone and PC. Initial setup/signing and update downloads contact their respective providers.

## Keywords

iPhone screen mirroring Windows · mirror iPhone to PC · control iPhone from PC · iPhone remote control Windows 11 · iOS screen mirror Windows · scrcpy for iPhone · scrcpy iOS alternative · iPhone to laptop screen share · use iPhone on computer · type on iPhone with PC keyboard · wireless iPhone mirroring Wi-Fi · USB iPhone mirror · free ApowerMirror alternative · open source iPhone mirroring · no jailbreak

## License

Pane is licensed under the [GNU General Public License v3.0](LICENSE).
Not affiliated with or endorsed by Apple Inc. iPhone, iOS and AirPlay are trademarks of Apple Inc.

See [1.2.1 release validation](docs/release-validation-1.2.1.md) for published checksums and the verified 1.1.1 → 1.2.1 updater transition.


### Floating controls

Drag the handle above the joined side controls to move Pane. Hover it to reveal minimize, maximize/restore and close. Drag any of the four phone corners to resize proportionally. The connection arrow opens a panel over the screen; the window stays the same width. Hold Home to invoke Siri. Select a 15/30/60 FPS display target and view measured received/displayed frame rates in Connection. Volume and mute controls remain; audio streaming is not included.
