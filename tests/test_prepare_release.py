"""Version allocation and immutable release-snapshot regression tests."""
import importlib.util
from pathlib import Path
import tempfile
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_release', ROOT / 'packaging/prepare_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseVersionTests(unittest.TestCase):
    def test_release_input_scope_matches_trigger(self):
        for path in ('handset/server.py', 'ios/project.yml', 'native/Cargo.lock', 'packaging/build.ps1',
                     'signer/Cargo.toml', 'requirements-build.txt', 'package-lock.json',
                     '.github/workflows/release.yml', '.github/workflows/companion.yml'):
            self.assertTrue(release.release_input(path), path)
        for path in ('README.md', 'handset/README.md', 'packaging/release-notes.md',
                     'tests/test_security.py', 'AGENTS.md', '.github/workflows/security.yml'):
            self.assertFalse(release.release_input(path), path)

    def test_docs_and_tests_advancement_does_not_cancel_release(self):
        with patch.object(release, 'git', side_effect=['', 'README.md\ntests/test_security.py']):
            release.check_current('source', 'current')
        with patch.object(release, 'git', side_effect=['', 'handset/server.py']):
            with self.assertRaisesRegex(ValueError, 'newer release inputs'):
                release.check_current('source', 'current')

    def test_first_release_retains_request(self):
        self.assertEqual(release.choose_version('2.3.0', []), '2.3.0')

    def test_stale_main_gets_next_patch_above_all_reserved_versions(self):
        self.assertEqual(release.choose_version('2.3.0', ['v2.3.0', 'v2.3.9', 'v2.3.10']), '2.3.11')

    def test_explicit_minor_and_major_are_preserved(self):
        for version in ('2.4.0', '3.0.0'):
            self.assertEqual(release.choose_version(version, ['v2.3.8']), version)

    def test_nonstable_tags_do_not_drive_stable_numbering(self):
        self.assertEqual(release.choose_version('2.3.0', ['v9.0.0-rc1', 'archive']), '2.3.0')

    def test_manual_tag_exact_version_and_no_downgrade(self):
        self.assertEqual(release.choose_version('2.4.0', ['v2.3.9', 'v2.4.0'], 'v2.4.0'), '2.4.0')
        with self.assertRaises(ValueError):
            release.choose_version('2.3.0', ['v2.4.0'], 'v2.3.0')
        with self.assertRaises(ValueError):
            release.choose_version('2.3.0', [], 'v2.4.0')

    def test_windows_range_and_strict_semver(self):
        for value in ('02.3.0', '2.3', '2.3.0-beta', '65536.0.0'):
            with self.assertRaises(ValueError):
                release.version_tuple(value)
        with self.assertRaises(ValueError):
            release.choose_version('2.3.0', ['v2.3.65535'])

    def test_only_desktop_version_files_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('handset/version.py', 'packaging/version.txt', 'handset/companion_version.py'):
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_text((ROOT / name).read_text())
            original = (root / 'handset/companion_version.py').read_text()
            with patch.object(release, 'ROOT', root):
                release.write_versions('2.4.12')
            self.assertIn('VERSION = "2.4.12"', (root / 'handset/version.py').read_text())
            resource = (root / 'packaging/version.txt').read_text()
            self.assertEqual(resource.count('"2.4.12"'), 2)
            self.assertEqual(resource.count('(2, 4, 12, 0)'), 2)
            self.assertEqual((root / 'handset/companion_version.py').read_text(), original)

    def test_companion_identity_must_match(self):
        project = (ROOT / 'ios/project.yml').read_text()
        declaration = (ROOT / 'handset/companion_version.py').read_text()
        version, build = release.companion_identity(project, declaration)
        self.assertEqual(len(version), 3)
        self.assertGreater(build, 0)
        with self.assertRaises(ValueError):
            release.companion_identity(project, 'COMPANION_VERSION = "9.0.0"')

    def test_changed_ios_requires_version_and_build_bumps(self):
        project = (ROOT / 'ios/project.yml').read_text()
        declaration = (ROOT / 'handset/companion_version.py').read_text()
        def fake_git(*args):
            if args[0] == 'diff':
                return 'ios/PaneFiles/App.swift'
            return project if args[1].endswith('project.yml') else declaration
        with patch.object(release, 'git', side_effect=fake_git):
            with self.assertRaisesRegex(ValueError, 'higher companion'):
                release.validate_companion_change([{'tag_name': 'v2.3.0'}])

    def test_desktop_only_change_keeps_companion(self):
        project = (ROOT / 'ios/project.yml').read_text()
        declaration = (ROOT / 'handset/companion_version.py').read_text()
        def fake_git(*args):
            if args[0] == 'diff':
                return ''
            return project if args[1].endswith('project.yml') else declaration
        with patch.object(release, 'git', side_effect=fake_git):
            release.validate_companion_change([{'tag_name': 'v2.3.0'}])


class ReleaseSnapshotTests(unittest.TestCase):
    def test_snapshot_is_versioned_without_moving_main_and_rerun_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('handset/version.py', 'packaging/version.txt', 'handset/companion_version.py', 'ios/project.yml'):
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_text((ROOT / name).read_text())
            with patch.object(release, 'ROOT', root):
                release.write_versions('2.3.0')
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            git('init', '-b', 'main')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            git('add', '.')
            git('commit', '-m', 'Baseline')
            git('tag', 'v2.3.0')
            (root / 'handset/example.py').write_text('FEATURE = True\n')
            git('add', '.')
            git('commit', '-m', 'Feature')
            source = git('rev-parse', 'HEAD')
            git('checkout', '--detach', source)
            inventory = root / 'releases.json'
            inventory.write_text(json.dumps([[{'tag_name': 'v2.3.0', 'draft': False, 'prerelease': False}]]))
            output = root / 'output'
            argv = ['prepare_release.py', '--releases', str(inventory), '--source', source, '--output', str(output)]
            with patch.object(release, 'ROOT', root), patch.object(sys, 'argv', argv):
                release.main()
                target = git('rev-parse', 'HEAD')
                self.assertNotEqual(target, source)
                self.assertEqual(git('rev-parse', 'main'), source)
                self.assertEqual(git('rev-parse', 'HEAD^'), source)
                self.assertEqual(set(git('diff', '--name-only', source, target).splitlines()),
                                 {'handset/version.py', 'packaging/version.txt'})
                self.assertIn('PANE_RELEASE_TAG=v2.3.1', output.read_text())
                git('tag', 'v2.3.1')
                git('checkout', '--detach', source)
                with self.assertRaisesRegex(ValueError, 'already reserved'):
                    release.main()
