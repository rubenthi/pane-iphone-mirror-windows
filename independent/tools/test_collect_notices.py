"""Isolated notice collector tests with newly authored fake package metadata."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import collect_notices as notices
from audit_licenses import audit_metadata


class NoticeTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(__file__).resolve().parents[1] / "native" / "target" / "notice-test-fixtures"
        fixture_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=fixture_root)
        self.root = Path(self.temporary.name)
        def clean_fixture():
            # Verify the exact recursive-cleanup target stays in test storage.
            self.root.resolve(strict=True).relative_to(fixture_root.resolve(strict=True))
            self.temporary.cleanup()
        self.addCleanup(clean_fixture)
        self.package = self.root / "fake-1.0.0"
        self.package.mkdir()
        (self.package / "Cargo.toml").write_text("# Test-only manifest\n", encoding="utf-8")
        self.raw = ("Copyright (c) 2026 Fixture Author\r\n\r\n" + notices.MIT_BODY + ".\r\n").encode()
        (self.package / "LICENSE-MIT").write_bytes(self.raw)
        self.metadata = {
            "version": 1, "workspace_members": ["root"],
            "packages": [{"id": "root", "name": "test-root", "version": "0.0.0"},
                         {"id": "fake", "name": "fake", "version": "1.0.0",
                          "source": "registry+https://github.com/rust-lang/crates.io-index",
                          "license": "MIT OR Apache-2.0", "license_file": None,
                          "manifest_path": str(self.package / "Cargo.toml")}],
            "resolve": {"nodes": [{"id": "root", "dependencies": ["fake"]},
                                  {"id": "fake", "dependencies": []}]},
        }

    def plan(self):
        return notices.build_plan(self.metadata, audit_metadata(self.metadata))

    def test_exact_bytes_and_private_path_free_index(self):
        index, files = self.plan()
        self.assertEqual(list(files.values()), [self.raw])
        public = json.dumps(index)
        self.assertNotIn(str(self.root), public)
        self.assertNotIn("manifest_path", public)
        self.assertEqual(index["packages"][0]["chosen_licenses"], ["MIT"])
        self.assertEqual(index["packages"][0]["source_url"], "https://crates.io/crates/fake/1.0.0")
        self.assertFalse(index["release_gate"]["authorized"])

    def test_mit_choice_and_and_precedence(self):
        self.assertEqual(notices.choose_licenses("Apache-2.0 OR MIT OR Unlicense"), ["MIT"])
        self.assertEqual(notices.choose_licenses("(MIT OR Apache-2.0) AND Unicode-3.0"), ["MIT", "Unicode-3.0"])
        self.assertEqual(notices.choose_licenses("MIT OR Apache-2.0 AND Unicode-3.0"), ["MIT"])

    def test_unicode_obligation_must_have_actual_text(self):
        self.metadata["packages"][1]["license"] = "(MIT OR Apache-2.0) AND Unicode-3.0"
        with self.assertRaisesRegex(notices.NoticeError, "Unicode-3.0"):
            self.plan()
        # This is an isolated license-pattern fixture, never release notice text.
        unicode_bytes = ("UNICODE LICENSE V3\nCOPYRIGHT AND PERMISSION NOTICE\nCopyright 2026 Unicode, Inc.\n"
                         + notices.UNICODE_PREAMBLE + "\n\n" + notices.UNICODE_BODY).encode()
        (self.package / "LICENSE-UNICODE").write_bytes(unicode_bytes)
        index, files = self.plan()
        self.assertEqual(index["packages"][0]["chosen_licenses"], ["MIT", "Unicode-3.0"])
        self.assertIn(unicode_bytes, files.values())
        self.assertEqual(len(files), 2)
        (self.package / "LICENSE-UNICODE").write_bytes(unicode_bytes[:-50])
        with self.assertRaisesRegex(notices.NoticeError, "Unicode-3.0"):
            self.plan()

    def test_gpl_in_any_branch_is_blocked(self):
        for expression in ["GPL-3.0-only OR MIT", "MIT OR LGPL-2.1-only", "MIT OR AGPL-3.0-only"]:
            with self.subTest(expression=expression):
                self.metadata["packages"][1]["license"] = expression
                with self.assertRaisesRegex(notices.NoticeError, "blocked"):
                    self.plan()

    def test_unknown_and_with_exceptions_refused(self):
        for expression in ["MIT OR Mystery", "Apache-2.0 WITH LLVM-exception", "MIT OR", ""]:
            with self.assertRaises(notices.NoticeError):
                notices.choose_licenses(expression)

    def test_stale_or_manipulated_audit_refused(self):
        report = audit_metadata(self.metadata)
        report["dependencies"][0]["version"] = "0.9.0"
        with self.assertRaisesRegex(notices.NoticeError, "does not match"):
            notices.build_plan(self.metadata, report)

    def test_missing_or_truncated_or_mismatched_text(self):
        path = self.package / "LICENSE-MIT"
        for data in [b"MIT\nCopyright fixture\n", self.raw[:-90], b"Apache License Version 2.0"]:
            path.write_bytes(data)
            with self.assertRaisesRegex(notices.NoticeError, "missing, mismatched"):
                self.plan()
        path.unlink()
        with self.assertRaisesRegex(notices.NoticeError, "missing, mismatched"):
            self.plan()

    def test_mit_body_without_real_copyright_holder_is_rejected(self):
        path = self.package / "LICENSE-MIT"
        for prefix in ["", "MIT License\n", "Copyright (c) 2016--2023\n", "Copyright (c) [year] [copyright holders]\n"]:
            with self.subTest(prefix=prefix):
                path.write_text(prefix + notices.MIT_BODY + ".\n", encoding="utf-8")
                with self.assertRaisesRegex(notices.NoticeError, "unattributed MIT"):
                    self.plan()

    def test_unreviewed_terms_before_or_after_complete_body_are_rejected(self):
        for text in [("Copyright (c) 2026 Fixture Author\nAdditional condition: no redistribution.\n" + notices.MIT_BODY),
                     (self.raw.decode() + "Additional condition: no redistribution.\n")]:
            self.assertFalse(notices.matches_license(text.encode(), "MIT"))

    def test_unicode_copyright_or_mandatory_preamble_removed_is_rejected(self):
        valid = ("UNICODE LICENSE V3\nCOPYRIGHT AND PERMISSION NOTICE\nCopyright 2026 Unicode, Inc.\n"
                 + notices.UNICODE_PREAMBLE + "\n" + notices.UNICODE_BODY)
        self.assertTrue(notices.matches_license(valid.encode(), "Unicode-3.0"))
        for text in [valid.replace("Copyright 2026 Unicode, Inc.\n", ""),
                     valid.replace(notices.UNICODE_PREAMBLE, "")]:
            self.assertFalse(notices.matches_license(text.encode(), "Unicode-3.0"))

    def test_generic_filename_requires_matching_text(self):
        (self.package / "LICENSE-MIT").rename(self.package / "LICENCE")
        self.assertEqual(len(self.plan()[1]), 1)

    def test_other_licenses_require_manual_complete_text_review(self):
        skeleton = b"Apache License\nVersion 2.0, January 2004\nGrant of Copyright License\nRedistribution\n"
        (self.package / "LICENSE-APACHE").write_bytes(skeleton)
        self.assertFalse(notices.matches_license(skeleton, "Apache-2.0"))
        for license_id in ["Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "BSL-1.0", "Unlicense"]:
            self.metadata["packages"][1]["license"] = license_id
            with self.subTest(license_id=license_id), self.assertRaisesRegex(notices.NoticeError, "manual complete-text review"):
                self.plan()

    def test_declared_path_escape_and_symlink_escape_refused(self):
        outside = self.root / "outside-license"
        outside.write_bytes(self.raw)
        self.metadata["packages"][1]["license_file"] = "../outside-license"
        with self.assertRaisesRegex(notices.NoticeError, "blocked"):
            self.plan()
        self.metadata["packages"][1]["license_file"] = None
        (self.package / "LICENSE-MIT").unlink()
        try:
            (self.package / "LICENSE-MIT").symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation unavailable on this Windows account")
        with self.assertRaisesRegex(notices.NoticeError, "escapes"):
            self.plan()

    def test_duplicate_metadata_ids_and_package_identity_refused(self):
        self.metadata["packages"].append(copy.deepcopy(self.metadata["packages"][1]))
        with self.assertRaises(ValueError):
            self.plan()
        self.metadata["packages"][-1]["id"] = "duplicate-source"
        self.metadata["resolve"]["nodes"].append({"id": "duplicate-source", "dependencies": []})
        self.metadata["resolve"]["nodes"][0]["dependencies"].append("duplicate-source")
        with self.assertRaisesRegex(notices.NoticeError, "duplicate package"):
            self.plan()

    def test_unreviewed_source_not_exposed(self):
        self.metadata["packages"][1]["source"] = "git+https://private.example/repo"
        with self.assertRaisesRegex(notices.NoticeError, "source review"):
            self.plan()

    def test_append_only_staging(self):
        index, files = self.plan()
        stage_root = self.root / "target" / "third-party-notices"
        first = notices.stage_plan(index, files, stage_root, self.root)
        second = notices.stage_plan(index, files, stage_root, self.root)
        self.assertNotEqual(first, second)
        self.assertEqual((first / next(iter(files))).read_bytes(), self.raw)
        self.assertEqual(json.loads((second / "index.json").read_text()), index)
        self.assertEqual(len(list(stage_root.iterdir())), 2)

    def test_temporary_windows_rename_lock_retried_atomically(self):
        index, files = self.plan()
        original = Path.rename
        calls = []
        def rename(source, destination):
            calls.append((source, destination))
            if len(calls) == 1:
                raise PermissionError("temporary indexer lock")
            return original(source, destination)
        with patch.object(Path, "rename", rename), patch.object(notices.time, "sleep"):
            output = notices.stage_plan(index, files, self.root / "stage", self.root)
        self.assertEqual(len(calls), 2)
        self.assertTrue((output / "index.json").is_file())

    def test_staging_escape_and_unsafe_file_rejected(self):
        index, files = self.plan()
        with self.assertRaisesRegex(notices.NoticeError, "escapes"):
            notices.stage_plan(index, files, self.root.parent / "escape", self.root)
        with self.assertRaisesRegex(notices.NoticeError, "unsafe"):
            notices.stage_plan(index, {"../escape.txt": b"bad"}, self.root / "stage", self.root)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_dry_run_uses_fresh_cargo_loader_by_default(self):
        audit_path = self.root / "audit.json"
        audit_path.write_text(json.dumps(audit_metadata(self.metadata)), encoding="utf-8")
        with patch.object(notices, "load_cargo_metadata", return_value=self.metadata) as loader:
            self.assertEqual(notices.main(["--audit-json", str(audit_path), "--dry-run"]), 0)
            loader.assert_called_once()

    def test_cli_fixture_dry_run(self):
        metadata_path, audit_path = self.root / "metadata.json", self.root / "audit.json"
        metadata_path.write_text(json.dumps(self.metadata), encoding="utf-8")
        audit_path.write_text(json.dumps(audit_metadata(self.metadata)), encoding="utf-8")
        result = subprocess.run([sys.executable, str(Path(notices.__file__)), "--metadata-json", str(metadata_path),
                                 "--audit-json", str(audit_path), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 1 dependencies", result.stdout)


if __name__ == "__main__":
    unittest.main()
