# Provenance record

Audit date: 2026-11-08. Existing application examined at commit `5082fa433ae7e149d80a2e3a533e5a8fe36ac4b2`.

## Existing product

The GitHub fork chain is `rubenthi/pane-iphone-mirror-windows` → `aesgalexis/pane-iphone-mirror-windows` → `teyboxv1/pane-iphone-mirror-windows`. The original code import is `a068b08e9cb16f3ce1f22e184ca9ac3433bd5dd4`; the immediate-parent baseline is `c7a763f286c12a7fa551eb10f90f0438cc5fa230`.

All 31 paths from that parent baseline remain in the current product: eight are byte-identical and 23 are modified. This is provenance evidence, not a legal similarity threshold. The original logo SVG remains unchanged, and the desktop and iPhone icons were generated from it. They must not be carried into the replacement.

The current executable contains the GPL Python device stack and additional GPL dependencies. Its signing helper contains `apple-codesign-quick` under LGPL-2.1-or-later. Its PyAV/FFmpeg components have further licensing obligations. Rewriting the original application's wrapper files does not remove these dependencies or their obligations.

## New implementation process

The parent coordinator has inspected the inherited application. Fresh implementation workers for `native/` and `tools/` were given no conversation history and were explicitly instructed not to inspect or copy the inherited source, assets, tests, or packaging. They may use official platform documentation and independently specified requirements. They must report the sources they use.

These instructions and a separate folder do not constitute an audited clean-room process or prove ownership. Do not describe this candidate as legally cleared. Choose the new application license and review provenance before distribution.

## Candidate device library — unresolved

The local old `idevice` 0.1.61 dependency is MIT but lacks the required live-stream service. Current upstream 0.1.68 advertises live HEVC/RTP streaming and HID support and declares MIT. Its maintainer states that MIT applies to all repository commits in [issue 115](https://github.com/jkcoxson/idevice/issues/115#issuecomment-4948816026). Stream/HID work landed in [PR 103](https://github.com/jkcoxson/idevice/pull/103), commit `ee830c9071892d95bfddc5aeaeb6f09656eea0bc`.

However, [`core_device/mod.rs`](https://github.com/jkcoxson/idevice/blob/master/idevice/src/services/core_device/mod.rs) includes the statement “Ported from pymobiledevice3”. That is a material question to investigate, not proof of infringement. The audit found no public explanation establishing any necessary original-rights-holder permission for the affected portion. A top-level MIT declaration alone does not resolve the requested stronger assurance.

The new prototype therefore does not depend on `idevice` yet. Before adding a device implementation, resolve this provenance question or implement the required protocol component independently from a documented specification with suitable review. Do not fall back to the GPL Python stack behind a subprocess and call that removal.

With the user's explicit approval, the factual clarification request was posted as [issue 145](https://github.com/jkcoxson/idevice/issues/145) by `rubenthi` on 2026-11-08. The question is recorded in [PROVENANCE-QUESTION-DRAFT.md](PROVENANCE-QUESTION-DRAFT.md); its posting is not a licensing clearance.

## Evidence sources

- [Original Pane import](https://github.com/teyboxv1/pane-iphone-mirror-windows/commit/a068b08e9cb16f3ce1f22e184ca9ac3433bd5dd4)
- [Parent security baseline](https://github.com/aesgalexis/pane-iphone-mirror-windows/commit/c7a763f286c12a7fa551eb10f90f0438cc5fa230)
- [pymobiledevice3 licensing guidance](https://doronz88.github.io/pymobiledevice3/latest/#can-i-use-pymobiledevice3-in-a-closed-source-app)
- [Pinned isideload manifest](https://github.com/nab138/isideload/blob/326e56229d0727cb6e7b34c8cf03e37e2cd3e17d/isideload/Cargo.toml)
- [Pinned apple-codesign-quick manifest](https://github.com/Dadoum/apple-crates/blob/91fad87099663252dec23e4b5332a8ca979986f4/apple-codesign-quick/Cargo.toml)
- [FFmpeg licensing guidance](https://ffmpeg.org/legal.html)
- [U.S. Copyright Office: computer programs](https://www.copyright.gov/register/tx-programs.html)
