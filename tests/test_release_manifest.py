"""Reject stale or unrelated iPhone builds before public release publication."""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('pane_release_manifest', Path(__file__).resolve().parents[1] / 'packaging' / 'release_manifest.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class CompanionReleaseTests(unittest.TestCase):
    def validate(self, **overrides):
        info = {'CFBundleIdentifier': 'io.github.rubenthi.PaneFiles',
                'CFBundleExecutable': 'PaneFiles', 'PaneProtocolVersion': 1,
                'CFBundleShortVersionString': release.VERSION, 'CFBundleVersion': '2'}
        info.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Pane-unsigned.ipa'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Payload/PaneFiles.app/Info.plist', plistlib.dumps(info))
            return release.validate_companion(path)

    def test_matching_companion_is_accepted(self):
        self.assertEqual(self.validate()['CFBundleShortVersionString'], release.VERSION)

    def test_stale_companion_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            self.validate(CFBundleShortVersionString='0.0.0')

    def test_unrelated_app_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.validate(CFBundleIdentifier='example.other')
