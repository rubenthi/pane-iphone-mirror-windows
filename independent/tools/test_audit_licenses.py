from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import audit_licenses as audit


def metadata(licenses: list[str | None]) -> dict:
    """Create a chain to ensure the audit follows transitive graph edges."""
    ids = ["root"] + [f"dependency-{index}" for index in range(len(licenses))]
    packages = [{"id": "root", "name": "independent-prototype", "version": "0.1.0", "license": None}]
    packages.extend({"id": item, "name": item, "version": "1.0.0", "license": license_id,
                     "manifest_path": str(Path.cwd() / item / "Cargo.toml"),
                     "source": "registry+https://github.com/rust-lang/crates.io-index"}
                    for item, license_id in zip(ids[1:], licenses))
    return {"version": 1, "workspace_members": ["root"], "packages": packages,
            "resolve": {"root": "root", "nodes": [
                {"id": item, "dependencies": ids[index + 1:index + 2]}
                for index, item in enumerate(ids)]}}


class LicenseAuditTests(unittest.TestCase):
    def test_allowed_alternatives_and_grouping(self):
        report = audit.audit_metadata(metadata(["MIT OR Apache-2.0", "(BSD-2-Clause OR BSD-3-Clause) AND ISC"]))
        self.assertEqual(report["dependency_policy_status"], "passed")
        self.assertEqual(report["dependency_count"], 2)
        self.assertFalse(report["release_gate"]["authorized"])
        self.assertEqual(report["release_gate"]["status"], "blocked")
        self.assertEqual(report["first_party_packages"][0]["status"], "unreleased/root-license-pending")

    def test_gpl_transitive_dependency_blocks(self):
        report = audit.audit_metadata(metadata(["MIT", "GPL-3.0-only"]))
        self.assertEqual(report["dependency_policy_status"], "blocked")
        self.assertIn("GPL-3.0-only", report["dependencies"][1]["issues"][0])

    def test_every_gpl_family_and_or_branch_blocks(self):
        for expression in ("MIT OR GPL-2.0-only", "LGPL-2.1-or-later", "AGPL-3.0-only", "GPL-2.0+"):
            with self.subTest(expression=expression):
                self.assertTrue(any("prohibited" in issue for issue in audit.expression_issues(expression)))

    def test_unknown_and_missing_block(self):
        for expression in (None, "", "NOASSERTION", "LicenseRef-Company", "MPL-2.0", "Unlicense"):
            with self.subTest(expression=expression):
                self.assertEqual(audit.audit_metadata(metadata([expression]))["dependency_policy_status"], "blocked")

    def test_invalid_expressions_block(self):
        for expression in ("MIT / Apache-2.0", "MIT OR", "(MIT", "MIT)", "()", "MIT Apache-2.0",
                           "MIT AND OR Apache-2.0", "MIT or Apache-2.0", "MIT; print('hello')",
                           "(MIT) WITH LLVM-exception", "MIT WITH", "MIT WITH (Apache-2.0)"):
            with self.subTest(expression=expression):
                self.assertTrue(audit.expression_issues(expression))

    def test_with_exception_always_requires_review(self):
        for expression in ("Apache-2.0 WITH LLVM-exception", "MIT OR Apache-2.0 WITH LLVM-exception"):
            with self.subTest(expression=expression):
                self.assertIn("unaudited WITH exception: LLVM-exception", audit.expression_issues(expression))

    def test_license_file_only_is_checked_but_unknown(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            base = Path(directory)
            license_file = base / "LICENSE"
            license_file.write_text("A custom license needs review.", encoding="utf-8")
            manifest = base / "Cargo.toml"
            data = metadata([None])
            data["packages"][1].update(manifest_path=str(manifest), license_file="LICENSE")
            report = audit.audit_metadata(data)
            self.assertEqual(report["dependency_policy_status"], "blocked")
            self.assertEqual(report["dependencies"][0]["license_file"]["status"], "exists")
            license_file.unlink()
            self.assertEqual(audit.audit_metadata(data)["dependencies"][0]["license_file"]["status"], "blocked")

    def test_license_file_outside_package_blocks_without_reading(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            base = Path(directory)
            package = base / "package"
            package.mkdir()
            (base / "LICENSE").write_text("outside", encoding="utf-8")
            data = metadata(["MIT"])
            data["packages"][1].update(manifest_path=str(package / "Cargo.toml"), license_file="../LICENSE")
            with patch.object(Path, "read_text", side_effect=AssertionError("must not read license files")):
                report = audit.audit_metadata(data)
            self.assertEqual(report["dependency_policy_status"], "blocked")

    def test_incomplete_graph_cannot_hide_dependency(self):
        data = metadata(["GPL-3.0-only"])
        data["resolve"]["nodes"].pop()
        with self.assertRaises(audit.AuditError):
            audit.audit_metadata(data)

    def test_duplicate_package_and_null_graph_block(self):
        data = metadata(["MIT"])
        data["packages"].append(data["packages"][1].copy())
        with self.assertRaises(audit.AuditError):
            audit.audit_metadata(data)
        data = metadata(["MIT"])
        data["resolve"] = None
        with self.assertRaises(audit.AuditError):
            audit.audit_metadata(data)

    def test_cargo_command_is_locked_and_includes_all_features(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps(metadata(["MIT"])), "")
        with patch.object(audit.subprocess, "run", return_value=completed) as run:
            audit.load_cargo_metadata(Path("prototype/Cargo.toml"))
        self.assertEqual(run.call_args.args[0], ["cargo", "metadata", "--locked", "--format-version", "1",
                                              "--all-features", "--manifest-path", str(Path("prototype/Cargo.toml"))])

    def test_cargo_command_failure_blocks_cli(self):
        completed = subprocess.CompletedProcess([], 101, "", "lockfile needs updating")
        with patch.object(audit.subprocess, "run", return_value=completed), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(audit.main([]), 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["dependency_policy_status"], "blocked")
        self.assertIn("cargo metadata failed (101)", report["error"])
        self.assertFalse(report["release_gate"]["authorized"])

    def test_cargo_unavailable_and_invalid_output_block(self):
        with patch.object(audit.subprocess, "run", side_effect=FileNotFoundError("cargo unavailable")):
            with self.assertRaises(audit.AuditError):
                audit.load_cargo_metadata(Path("Cargo.toml"))
        completed = subprocess.CompletedProcess([], 0, "invalid", "")
        with patch.object(audit.subprocess, "run", return_value=completed):
            with self.assertRaises(audit.AuditError):
                audit.load_cargo_metadata(Path("Cargo.toml"))

    def test_saved_metadata_cli_writes_version_source_license_path(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            base = Path(directory)
            saved = base / "metadata.json"
            report_path = base / "report.json"
            saved.write_text(json.dumps(metadata(["MIT"])), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = audit.main(["--metadata-json", str(saved), "--output", str(report_path)])
            self.assertEqual(code, 0)
            record = json.loads(report_path.read_text(encoding="utf-8"))["dependencies"][0]
            for field in ("version", "source", "license_expression", "manifest_path"):
                self.assertTrue(record[field])


if __name__ == "__main__":
    unittest.main()
