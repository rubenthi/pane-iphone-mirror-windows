# Dependency license policy

`audit_licenses.py` uses the Python standard library at development time. It does
not add Python to the native application or install any Python packages.

Run all development checks from PowerShell:

```powershell
./independent/check.ps1 -PythonPath 'C:/path/to/python.exe'
```

The check runs audit regression tests, obtains the locked all-features Cargo
metadata graph, writes `independent/native/target/license-audit.json`, and runs
Rust formatting, check, tests, and a release-mode build. It does not launch the
GUI, contact a phone, install an application, or publish a release.

The audit checks every resolved third-party package reachable from workspace
members, including transitive and build dependencies. All identifiers in every
SPDX `AND`/`OR` branch must be explicitly allowed. GPL, LGPL, and AGPL identifiers
are prohibited even when paired with an allowed alternative. Unknown or missing
licenses, malformed expressions, and unaudited `WITH` exceptions block the check.
The current exception allowlist is empty.

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
