Pane 1.3.2 for Windows x64

- Fixed the Windows HEVC decoder cropping the phone to 1280 x 720. Decoder dimensions now come from the stream SPS and update when in-band parameter sets change. Full 1328 x 2896 USB and Wi-Fi video was observed on iPhone19,3 / iOS 27.0.1.
- Fixed Wi-Fi discovery's incompatible callback signature and Windows IPv6 adapter scope names. Existing pairing records are preserved.
- Blue glass side controls with tooltips: volume above the sidebar arrow; Home, app switcher, Notifications and Control Center below it.
- Removed hover controls, status messages and decorative Home bar from the phone surface. Status lives in the sidebar.
- Drag the top-right three-line handle to move Pane; hover it for minimize, maximize/restore and close. Drag the bottom-right resize grip to resize while preserving the display aspect ratio.
- Native window regions follow the rounded phone, individual side controls and expanded drawer. Empty corners and gaps are outside the input region.
- Mouse-wheel and trackpad scrolling over the video becomes a bounded iPhone swipe. Sidebar scrolling stays local.
- Audio is intentionally not included, as requested. Sound remains on the iPhone.

Includes regression coverage for HEVC dimensions and rotation configuration, Wi-Fi signatures and scopes, native resize/menu/region behavior, full-frame rendering and wheel-to-touch mapping. Physical pointer accuracy and scrolling still require confirmation on the phone; simulated input checks do not establish physical acceptance.

The iOS 27 setup guide, including optional AltStore Classic directions, remains available. Install with install.ps1 -Version 1.3.2, or start the existing installed Pane, wait for the verified update, close it normally and reopen. The updater retains a rollback executable.

Mirroring starts with iPhone volume lowered to zero. Audio playback on the PC remains disabled. Use Volume up if you want phone sound during the session.
