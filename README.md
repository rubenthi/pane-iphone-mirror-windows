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

Updates preserve existing preferences, browser profiles, signing data and saved phone pairings. A reset happens only when explicitly requested with `Pane.exe --reset`. The iPhone volume controls remain; startup never lowers the volume. Pane 2.3.0 adds optional Bluetooth audio and system notifications; radio behavior still requires the hardware checks below.

The custom native phone-shaped window and joined control rail from 1.7.4 are restored. The Connection panel overlays the phone screen without widening the window. A full setup guide opens automatically only when no saved phone pairing exists: USB trust, Developer Mode reveal and iPhone confirmation, installation of **Pane**, then USB/Wi-Fi/Bluetooth binding. The compact sidebar has **Connection**, **Uploads** and **Settings** tabs. Settings contains signing, display controls, audio and notification choices. **Uploads** sends files both ways over Bluetooth Low Energy. Incoming files are verified and saved to the laptop's Downloads folder without overwriting existing files. Keep the iPhone companion open during transfers.

See the [complete setup and signing guide](docs/companion-setup.md). GitHub Actions produces the [unsigned companion IPA](../../actions/workflows/companion.yml) for AltStore signing and the [Windows executable](../../actions/workflows/desktop-check.yml). A source update on main is not itself an installed laptop update. Automatic updates check published releases at launch and every six hours while Pane stays open, retry after fifteen minutes on failure, and install the verified executable when Pane closes. Open Pane again to use the new version. Qualifying application, build, dependency, or release-workflow changes merged into main trigger a tested release with an automatically allocated desktop patch version. Documentation-only and tests-only changes do not publish. Explicit higher major/minor versions are preserved. See [the release workflow](docs/release-workflow.md) for versioning, independent iPhone versions, review gates, recovery, and update limits.

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
6. Pane binds USB and Wi-Fi automatically after installation. Open Pane on the iPhone. If it says **Untrusted Developer**, open **Settings → General → VPN & Device Management → Developer App**, select the signing profile and tap **Trust** (or **Allow & Restart**, if offered). Reopen Pane, allow Bluetooth and accept pairing prompts. Keep the app open.
7. Once Bluetooth confirms the connection, the guide closes and a short feature tour introduces the controls. Use **Uploads** for files and **Connect** for mirroring. See [setup details and limitations](docs/companion-setup.md).

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

Drag the handle above the joined side controls to move Pane. Hover it to reveal minimize, maximize/restore and close. Drag any of the four phone corners to resize proportionally. The connection arrow opens a panel over the screen; the window stays the same width. Hold Home to invoke Siri. Select a 15/30/60 FPS display target and view measured received/displayed frame rates in Settings → Display & controls. Volume and mute controls remain; optional Bluetooth audio uses a separate Windows receiver.


### Bluetooth audio, notifications and background mode

In **Settings → Bluetooth audio**, pair your iPhone with your Zephyrus in Windows, refresh devices and select it. Audio reception is on by default after selecting a phone and starts only while mirroring. On first use, select the PC in the iPhone audio output menu. Windows cannot force iOS to change its default route; availability depends on the Bluetooth adapter and Windows 10 version 2004 or newer. Calls and microphone routing are not promised.

In **Settings → Phone notifications**, choose the paired iPhone and enable **Share System Notifications** for the PC in the iPhone's Bluetooth settings. Enable forwarding and choose calls, messages/social, mail, calendar or other categories. Categories come from iOS; this does not read another app's private storage or expose an app-by-app filter. Previews are off by default.

The sidebar's **Keep notifications running** switch is off by default. If enabled along with phone notifications, the event-driven Rust helper stays open after Pane closes. It does not retain Python, WebView2, mirroring, file transfers or signing in the background, and does not register Windows startup. Reopen Pane and switch it off to stop background forwarding. Windows may retain delivered alerts in Notification Center; Pane stores no notification text in its settings, logs or HTTP responses.

The Swift companion continues to provide foreground encrypted file transfers. System notifications use Apple's ANCS service; audio uses Windows A2DP reception. Neither feature is media capture or cross-app notification forwarding implemented inside the companion.

**Performance:** the full stack has not been rewritten in Rust. The existing Rust signer, Swift companion and hardware-decoded video path are retained. Idle polling and window command traffic were reduced; a new bounded Rust worker handles optional background services. A language change alone does not demonstrate smaller storage, lower memory or faster mirroring. See [measurements and verification limits](docs/ux-efficiency-validation.md).

### iPhone companion updates

On opening Pane, a dismissible popup appears only when the bundled iPhone app is newer than a verified installed version. Disconnected phones use the last USB-verified version; unknown, missing or ambiguous installations never trigger a popup. Check manually in Settings > Setup & signing after connecting and unlocking the phone. Checks are read-only and use existing trust. The app-version query has a five-second timeout after USB discovery, and results are cached for 60 seconds. A failed current read clears the old version rather than claiming an update is needed.

The update action opens the existing Install Pane section. It never signs in, installs, resets, or rebinds automatically. Use the same Apple Account and signing team to preserve the app identity and existing pairing. A desktop update does not install or renew the iPhone app.

Release maintenance: change `handset/companion_version.py` (`COMPANION_VERSION`) and `ios/project.yml` together when releasing iPhone changes. Desktop-only releases change the desktop version without changing either mobile version, so they do not manufacture mobile-update prompts.
