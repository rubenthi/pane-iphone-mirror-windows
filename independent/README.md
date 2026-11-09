# Independent replacement — unreleased

This directory starts a separate implementation candidate. It is not a release of the existing Pane application, not feature-complete, and not a certification of legal independence. Do not package or publish it as a replacement yet.

The working GPL application, its installed copy, records, history, and previous releases remain intact. Their existing licenses cannot be removed retroactively by replacing a future version.

The replacement must not import source, artwork, generated icons, or build assets from that application. Implementation workers receive behavioral requirements and official platform documentation, rather than an instruction to translate the old files. This process is recorded in [PROVENANCE.md](PROVENANCE.md).

## Constraints

- No GPL, LGPL, or AGPL code in the new delivered application or its bundled dependency graph.
- Audit exact resolved versions and packaged files, including native libraries and signing helpers. An MIT label on a top-level wrapper does not clear its transitive dependencies.
- Native Windows UI and rendering, with no Python or browser runtime in the shipped desktop application.
- Event-driven idle operation, bounded buffers, and native monitor density. A language choice alone is not a performance result.
- Newly authored product artwork and documentation. Product name and application license remain pending decisions.
- Preserve the existing application and user data until a complete, tested migration is available.

## Current scope

`native/` is a new Windows shell and bounded-frame-queue prototype. It has no phone connection, signing, mirroring, notification, audio, or transfer implementation. It must identify itself as a prototype and must not read the current application's profiles.

`tools/` and `check.ps1` provide a dependency-license gate and development checks. Passing that gate verifies the declared dependency policy; it is not an ownership determination or a substitute for a provenance review.

See [MIGRATION.md](MIGRATION.md) for the required feature replacements and [PERFORMANCE.md](PERFORMANCE.md) for measurement definitions and proposed budgets. Public release remains blocked until those requirements and the provenance questions are resolved.
