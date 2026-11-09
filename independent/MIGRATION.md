# Replacement requirements and release gates

None of the following phone features is implemented in the new shell yet. A functioning existing feature is not proof that its replacement is complete.

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

Earlier public releases remain under their existing terms. Do not delete attribution, rewrite public history, or overwrite a release as part of this migration.
