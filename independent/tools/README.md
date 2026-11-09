# Dependency license policy

`audit_licenses.py` uses the Python standard library at development time. It does
not add Python to the native application or install any Python packages.

Run all development checks from PowerShell:

```powershell
./independent/check.ps1 -PythonPath 'C:/path/to/python.exe'
```

The check runs audit regression tests, obtains the locked all-features Cargo
metadata graph, writes `independent/native/target/license-audit.json`, stages
exact dependency license texts for review, and runs
Rust formatting, check, strict Clippy, tests, and a release-mode build. It does not launch the
GUI, contact a phone, install an application, or publish a release.

The audit checks every resolved third-party package reachable from workspace
members, including transitive and build dependencies. All identifiers in every
SPDX `AND`/`OR` branch must be explicitly allowed. GPL, LGPL, and AGPL identifiers
are prohibited even when paired with an allowed alternative. Unknown or missing
licenses, malformed expressions, and unaudited `WITH` exceptions block the check.
The current exception allowlist is empty.

`Unlicense` was explicitly reviewed against [SPDX's license text](https://spdx.org/licenses/Unlicense.html) on 2026-11-08. The new `memchr` dependency declares `Unlicense OR MIT`; its actual `LICENSE-MIT` file was also read, and MIT is the intended distribution choice for it. This adds a reviewed permissive identifier; GPL-family branches and unknown licenses still fail closed. Third-party notices remain required before distribution.

A `license-file` declaration is checked for existence inside its package
directory; the tool never reads its contents or infers its license. A file-only
declaration therefore remains blocked pending identification and review.

The JSON report records each package's version, source, declared license, and
manifest path. Workspace packages are excluded from third-party decisions and
reported as `unreleased/root-license-pending`. Even when dependencies pass the
declared-license policy, the report's separate release gate stays blocked:
release is not authorized and the new root's copyright/license decision is
pending. Automated metadata checks are not legal certification or proof of
ownership and compliance.

For isolated tests or review of a captured graph:

```powershell
python independent/tools/audit_licenses.py --metadata-json metadata.json --output audit.json
python -m unittest discover -s independent/tools -p 'test_*.py' -v
```

The audit command exits zero only for a passing dependency policy; this exit code
does not authorize release. Invalid metadata or a failed Cargo command exits
nonzero.

`collect_notices.py` compares that report against fresh locked metadata, chooses
permissive `OR` alternatives (preferring MIT), and preserves required `AND` terms.
Automatic text recognition supports the complete standard MIT grant, conditions
and disclaimer, and the complete Unicode-3.0 preamble and terms. Both also require
an actual copyright statement identifying a holder; a missing statement, a
year-only statement, or an unfilled template blocks collection. Whitespace is
normalized only for recognition. The original files are copied byte for byte.

Other SPDX identities accepted by the metadata policy, including Apache-2.0,
BSD, ISC, Zlib, BSL-1.0 and Unlicense, require a separate manual complete-text
review before their notices can be collected automatically. A license name or
collection of matching headings is insufficient. An MIT alternative can still
be selected when every declared branch passes the metadata policy. Mandatory
Unicode terms are never dropped when MIT is selected.

Run text verification without creating a snapshot:

```powershell
python independent/tools/collect_notices.py --dry-run
```

Without `--dry-run`, a fully passing graph produces a unique atomic snapshot
under `independent/native/target/third-party-notices/`. Its index contains package
versions, public source URLs, chosen licenses and SHA-256 hashes, with no local
package paths. Existing snapshots are never replaced or deleted. Saved metadata
is accepted only in explicit `--metadata-json ... --dry-run` fixture mode.

The current 31-dependency graph passes the declared SPDX policy, but notice
collection is blocked on nine packages. `equivalent` 1.0.3 and `indexmap` 2.14.2
have year-only MIT copyright lines without named holders. The MIT files for
`proc-macro2` 1.0.107, `quote` 1.0.47, `serde_core` and `serde_derive` 1.0.229,
`syn` 2.0.119 and 3.0.9, and `unicode-ident` 1.0.27 have no copyright lines.
The collector does not turn Cargo author metadata into a fabricated copyright
notice or waive these cases. Earlier snapshots produced by the less strict
collector remain historical review artifacts and do not pass the current gate.
No new snapshot is staged until the entire graph passes. These are review
materials, not a complete application license or distribution approval.
