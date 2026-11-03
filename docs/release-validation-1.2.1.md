# Pane 1.2.1 release validation

[Stable release](https://github.com/rubenthi/pane-iphone-mirror-windows/releases/tag/v1.2.1) · [Successful Windows build](https://github.com/rubenthi/pane-iphone-mirror-windows/actions/runs/41568433399)

Validated November 2, 2026 (America/Los_Angeles). The repository is public. No published release was overwritten; the failed v1.2.0 tag is retained.

## Published assets

All three release download URLs were fetched successfully. Downloaded sizes and SHA-256 values matched GitHub asset digests. The executable Windows metadata, application version, tag and update manifest agree on 1.2.1. Update URLs point to this fork.

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| Pane.exe | 76256448 | `7044b1b99dbe8bab278a305283dd3934f79727cdff80f32a41d2b5d772f507fc` |
| update.json | 232 | `dbdc86e150ecf20fc0bf62ee3184026d2d922ebe880407407a203501291b6f66` |
| install.ps1 | 5588 | `a93898f101b3e328a1e25070770e23d2b78d6294e83916436fd9445e04380525` |

## Validation performed

- 29 Python regressions and two JavaScript regressions passed.
- Windows installer checks passed for checksum rejection, exit timeout, locked-file failure, process-exit wait, retained backup, replacement and fresh installation.
- Native UI integration passed for client dimensions, horizontal expansion/collapse, guide and AltStore disclosure, connection tabs, pinning, simulated display aspect changes and absence of page errors.
- The exact downloaded release executable passed dependency imports, bundled updater, local HTTP UI, actual WebView2 rendering, native window-region clipping, drawer sizing and WebCodecs API availability checks. API availability does not prove hardware HEVC decoding.
- The installed 1.1.1 executable checked the public latest manifest and reported 1.2.1 staged and verified. A normal window close triggered its own PowerShell updater. The installed executable then matched the published 1.2.1 checksum above, and its retained backup matched the original 1.1.1 SHA-256: `0ad392e15be8b53433c2a612161a7acdc295ff9d5241e96e1b0dbc8958d3b11c`.
- Relaunch activated 1.2.1. Its updater reported current. The installed native window measured 388 × 760 compact and 716 × 760 expanded; sidebar and setup guide opened through desktop interaction. The existing desktop shortcut remained valid.
- Apple Devices 1.1792.39682.0, Chrome 156.0.8078.80, Edge 156.0.4314.58 and a working WebView2 runtime were present on the validation PC.

## Hardware limits

No phone was detected during final installation acceptance. Earlier USB metadata identified iPhone19,3 / iOS 27.0.1 with Developer Mode enabled. Video, keyboard/mouse, Wi-Fi pairing and the optional AltStore workaround were not exercised. See [device verification records](compatibility.md). The shell adapts to reported display aspect ratio; it does not reproduce every model's physical bezel or cutout.