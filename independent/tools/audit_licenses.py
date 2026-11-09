"""Fail-closed dependency policy check using only Python's standard library.

This checks declared Cargo metadata, not legal rights or license compliance.
No package source code is read, and no license text is guessed from filenames.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


ALLOWED_LICENSES = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib",
    "BSL-1.0", "Unicode-3.0",
})
# Exceptions need an explicit review before any can be accepted.
ALLOWED_EXCEPTIONS: frozenset[str] = frozenset()
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+:-]*|[()]")


class AuditError(ValueError):
    pass


class SpdxParser:
    """Parse SPDX AND/OR expressions; validate every branch of an OR."""

    def __init__(self, expression: str):
        self.tokens: list[str] = []
        position = 0
        while position < len(expression):
            if expression[position].isspace():
                position += 1
                continue
            match = TOKEN.match(expression, position)
            if match is None:
                raise AuditError(f"invalid SPDX character at position {position}")
            self.tokens.append(match.group())
            position = match.end()
        self.position = 0
        self.licenses: set[str] = set()
        self.exceptions: set[str] = set()

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise AuditError("unexpected end of SPDX expression")
        self.position += 1
        return token

    def parse(self) -> tuple[set[str], set[str]]:
        self.parse_or()
        if self.peek() is not None:
            raise AuditError(f"unexpected SPDX token: {self.peek()}")
        return self.licenses, self.exceptions

    def parse_or(self) -> None:
        self.parse_and()
        while self.peek() == "OR":
            self.take()
            self.parse_and()

    def parse_and(self) -> None:
        self.parse_primary()
        while self.peek() == "AND":
            self.take()
            self.parse_primary()

    def parse_primary(self) -> None:
        token = self.take()
        if token == "(":
            self.parse_or()
            if self.take() != ")":
                raise AuditError("missing closing SPDX parenthesis")
            return
        if token in {"AND", "OR", "WITH", ")"}:
            raise AuditError(f"expected SPDX license, found {token}")
        self.licenses.add(token)
        if self.peek() == "WITH":
            self.take()
            exception = self.take()
            if exception in {"AND", "OR", "WITH", "(", ")"}:
                raise AuditError("expected SPDX exception identifier")
            self.exceptions.add(exception)


def expression_issues(expression: object) -> list[str]:
    if not isinstance(expression, str) or not expression.strip():
        return ["missing license expression; license identity requires review"]
    try:
        licenses, exceptions = SpdxParser(expression).parse()
    except AuditError as error:
        return [str(error)]
    issues = []
    for license_id in sorted(licenses):
        if re.match(r"^(?:A?GPL|LGPL)(?:-|\+|$)", license_id, re.IGNORECASE):
            issues.append(f"prohibited GPL/LGPL/AGPL family: {license_id} (including OR branches)")
        elif license_id not in ALLOWED_LICENSES:
            issues.append(f"unknown or unaudited license: {license_id}")
    for exception in sorted(exceptions - ALLOWED_EXCEPTIONS):
        issues.append(f"unaudited WITH exception: {exception}")
    return issues


def license_file_observation(package: dict) -> dict | None:
    """Check existence only, and refuse paths outside the package directory."""
    declared = package.get("license_file")
    if declared is None:
        return None
    observation = {"declared": declared, "status": "blocked"}
    if not isinstance(declared, str) or not declared:
        observation["reason"] = "invalid license_file path"
        return observation
    manifest = package.get("manifest_path")
    if not isinstance(manifest, str) or not Path(manifest).is_absolute():
        observation["reason"] = "missing absolute package manifest path"
        return observation
    try:
        base = Path(manifest).parent.resolve(strict=True)
        # Cargo may return an absolute license_file. Accept it only inside base.
        candidate = (base / declared).resolve(strict=True)
        candidate.relative_to(base)
        if not candidate.is_file():
            raise AuditError("license_file is not a regular file")
    except (OSError, ValueError, AuditError) as error:
        observation["reason"] = f"license_file missing, inaccessible, or outside package: {error}"
        return observation
    observation.update(status="exists", path=str(candidate))
    return observation


def audit_metadata(metadata: object) -> dict:
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise AuditError("expected Cargo metadata format version 1")
    packages = metadata.get("packages")
    resolve = metadata.get("resolve")
    members = metadata.get("workspace_members")
    if not isinstance(packages, list) or not isinstance(resolve, dict) or not isinstance(members, list) or not members:
        raise AuditError("metadata must include packages, resolved graph, and workspace members")
    by_id = {}
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("id"), str):
            raise AuditError("invalid package record")
        if package["id"] in by_id:
            raise AuditError("duplicate package id")
        by_id[package["id"]] = package
    nodes = resolve.get("nodes")
    if not isinstance(nodes, list):
        raise AuditError("metadata has no resolved dependency nodes")
    graph = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not isinstance(node.get("dependencies"), list):
            raise AuditError("invalid resolved graph node")
        if node["id"] in graph or not all(isinstance(item, str) for item in node["dependencies"]):
            raise AuditError("invalid or duplicate resolved graph node")
        graph[node["id"]] = node["dependencies"]
    first_party = set(members)
    pending = list(members)
    reached = set()
    while pending:
        package_id = pending.pop()
        if package_id in reached:
            continue
        if package_id not in by_id or package_id not in graph:
            raise AuditError(f"resolved package missing from metadata: {package_id}")
        reached.add(package_id)
        pending.extend(graph[package_id])
    records = []
    for package_id in sorted(reached - first_party):
        package = by_id[package_id]
        issues = expression_issues(package.get("license"))
        for field in ("name", "version", "manifest_path"):
            if not isinstance(package.get(field), str) or not package[field]:
                issues.append(f"missing package {field}")
        source = package.get("source")
        if source is not None and not isinstance(source, str):
            issues.append("invalid package source")
        file_check = license_file_observation(package)
        if file_check is not None and file_check["status"] != "exists":
            issues.append(file_check["reason"])
        records.append({
            "id": package_id, "name": package.get("name"), "version": package.get("version"),
            "source": source if source is not None else "local-path",
            "license_expression": package.get("license"), "manifest_path": package.get("manifest_path"),
            "license_file": file_check, "status": "blocked" if issues else "allowed-by-declared-license-policy",
            "issues": issues,
        })
    blocked = sum(record["status"] == "blocked" for record in records)
    return {
        "schema_version": 1,
        "audit_scope": "Cargo resolved workspace graph, all features; declared third-party licenses",
        "dependency_policy_status": "blocked" if blocked else "passed",
        "dependency_count": len(records), "blocked_dependency_count": blocked,
        "allowed_licenses": sorted(ALLOWED_LICENSES), "allowed_exceptions": sorted(ALLOWED_EXCEPTIONS),
        "gpl_family_in_any_branch": "prohibited",
        "first_party_packages": [{"id": item, "name": by_id[item].get("name"),
                                  "version": by_id[item].get("version"),
                                  "status": "unreleased/root-license-pending"} for item in sorted(first_party)],
        "release_gate": {"status": "blocked", "authorized": False,
                         "reasons": ["Prototype is unreleased; root license/copyright decision is pending.",
                                     "Release is not authorized."] +
                                    (["Dependency license policy has blocked dependencies."] if blocked else [])},
        "limitations": ["An automated policy result is not legal certification.",
                        "Declared metadata and license-file existence do not establish ownership or compliance.",
                        "Windows system APIs are platform requirements, not bundled Cargo dependencies."],
        "dependencies": records,
    }


def load_cargo_metadata(manifest: Path) -> dict:
    command = ["cargo", "metadata", "--locked", "--format-version", "1", "--all-features",
               "--manifest-path", str(manifest)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise AuditError(f"cargo metadata could not run: {error}") from error
    if result.returncode:
        raise AuditError(f"cargo metadata failed ({result.returncode}): {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AuditError(f"cargo metadata returned invalid JSON: {error}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--manifest-path", type=Path, default=Path(__file__).resolve().parents[1] / "native" / "Cargo.toml")
    inputs.add_argument("--metadata-json", type=Path, help="Audit saved Cargo metadata (also used by isolated tests)")
    parser.add_argument("--output", type=Path, help="Write a machine-readable audit report")
    args = parser.parse_args(argv)
    try:
        metadata = json.loads(args.metadata_json.read_text(encoding="utf-8-sig")) if args.metadata_json else load_cargo_metadata(args.manifest_path)
        report = audit_metadata(metadata)
    except (AuditError, OSError, ValueError, TypeError) as error:
        report = {"schema_version": 1, "dependency_policy_status": "blocked", "error": str(error),
                  "release_gate": {"status": "blocked", "authorized": False,
                                   "reasons": ["Audit failed; prototype is unreleased/root-license-pending."]}}
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["dependency_policy_status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
