# Replacement requirements and release gates

The following complete phone workflows remain required. Read-only discovery and packet-processing building blocks are implemented, but a functioning existing feature is not proof that its replacement is complete.

| Area | Required independent replacement | Acceptance evidence |
| --- | --- | --- |
| Desktop host | Native Windows application, per-monitor DPI, black uniform screen border, proportional corner resizing, settings | Real 100%/200% monitor transitions, corner/edge resize checks, idle measurements |
| Discovery and trust | USB and Wi-Fi discovery, use of authorized trust records, clear trust instructions | Read-only detection first; separately authorized pairing test; preserved old records |
| Device transport | Independently cleared tunnel, RSD/XPC, connection lifecycle and reconnect | Bounded timeouts, disconnect recovery, audited exact dependency graph |
| Video and input | Live HEVC/RTP, hardware decode through Windows APIs, touch/keyboard routing | Real iPhone stream, rotation, controls, latency and dropped-frame measurement; no FFmpeg dependency by default |
| Companion | New Swift implementation using Apple platform APIs, independent artwork and identity/migration plan | Mac build, simulator checks, separately authorized signing/installation and data migration |
| Transfers | Authenticated direct Wi-Fi channel, integrity checks, bounded streaming, pause/cancel on both devices | Large real transfers with mirroring off, failure/retry/cancel, no overwrites |
| Notifications/audio | Native Windows Bluetooth integration and explicit user consent | Real device delivery/playback; privacy-preserving defaults; no false compatibility promise |
| Signing | New permissively cleared signing path, or a documented external signing workflow | Full transitive audit, credential handling review, actual Apple-team/install/renewal checks |
| Distribution | New build pipeline, identity, notices, license decision, source/artifact provenance, safe update migration | Clean immutable build, complete final package audit, rollback, explicit publish authorization |

Release is blocked while any required feature is a prototype, while dependency provenance is unresolved, or while the application license and branding remain undecided. No old GPL binary or companion may be repackaged as a component of the independent build to bypass these gates.

## Current building-block evidence

- Windows SetupAPI discovery identifies present Apple USB nodes and reports mobile-driver readiness separately. The connected iPhone produced three Windows nodes with one ready mobile driver; these are not three phones or proof of trust.
- The new loopback-only Apple service client implements `ListDevices`, with bounded XML/packet sizes and deadlines. One live snapshot returned one USB route; later snapshots were empty despite Windows USB presence. No pairing record was changed to resolve that difference.
- The RFC 3550/7798 HEVC/RTP assembler handles single NAL, aggregation and fragmentation packets, with bounded access units and loss/reset behavior. Synthetic protocol tests do not establish compatibility with a live iPhone stream.
- Windows exposes one activatable, D3D11-aware HEVC decoder on this laptop. Actual phone-stream decoding and GPU acceleration remain untested.
- Native controls were checked across 100% and 200% monitors and through maximize/restore. Four-corner resizing and a rendered phone bezel still require validation once the video renderer exists.

Earlier public releases remain under their existing terms. Do not delete attribution, rewrite public history, or overwrite a release as part of this migration.
