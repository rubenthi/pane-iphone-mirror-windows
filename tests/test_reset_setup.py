import asyncio
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from handset.state import prepare_state, write_json
from handset.setup import inspect_ipa, _perform
from handset import setup


class ResetTests(unittest.TestCase):
    def test_first_launch_erases_profiles_state_and_pairings_once_preserving_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'Pane'
            for name in ('window', 'webview', 'device', 'staging', 'outbox'):
                (root / name).mkdir(parents=True)
                (root / name / 'old').write_text('private')
            for name in ('pane.log', 'settings.json', 'binding.json', 'setup.json', 'transfers.json'):
                (root / name).write_text('private')
            downloads = Path(directory) / 'Downloads'; downloads.mkdir()
            (downloads / 'personal').write_text('keep')
            self.assertTrue(prepare_state(root))
            self.assertEqual([p.name for p in root.iterdir()], ['state-version.json'])
            (root / 'binding.json').write_text('new')
            self.assertFalse(prepare_state(root))
            self.assertEqual((root / 'binding.json').read_text(), 'new')
            self.assertEqual((downloads / 'personal').read_text(), 'keep')
            self.assertTrue(prepare_state(root, force=True))
            self.assertFalse((root / 'binding.json').exists())

    def test_corrupt_marker_and_symlink_dont_escape_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'Pane'; root.mkdir()
            write_json(root / 'state-version.json', [])
            outside = Path(directory) / 'outside'; outside.mkdir(); (outside / 'keep').touch()
            try: (root / 'window').symlink_to(outside, target_is_directory=True)
            except OSError: self.skipTest('Symlink privilege unavailable')
            prepare_state(root)
            self.assertTrue((outside / 'keep').exists())


class SetupTests(unittest.TestCase):
    def test_installer_rejects_unsigned_and_unrelated_ipa(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.ipa'
            info = {'PaneProtocolVersion': 1, 'CFBundleExecutable': 'PaneFiles', 'CFBundleIdentifier': 'test.pane'}
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Payload/PaneFiles.app/Info.plist', plistlib.dumps(info))
            with self.assertRaisesRegex(ValueError, 'unsigned'): inspect_ipa(path)
            with zipfile.ZipFile(path, 'a') as archive:
                archive.writestr('Payload/PaneFiles.app/embedded.mobileprovision', b'signed')
                archive.writestr('Payload/PaneFiles.app/_CodeSignature/CodeResources', b'signed')
            self.assertEqual(inspect_ipa(path), 'test.pane')
            # Presence is a preflight only; iOS validates the real signature on install.
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Payload/Other.app/Info.plist', plistlib.dumps({'CFBundleExecutable': 'Other'}))
            with self.assertRaisesRegex(ValueError, 'not the Pane'): inspect_ipa(path)

    def test_no_usb_and_duplicate_actions_do_not_start_workers(self):
        with patch('handset.setup.list_devices', return_value=[]), self.assertRaises(ValueError):
            setup.start('start', 'phone')
        with patch.dict(setup._STATE, phase='working'), patch('handset.setup.list_devices', return_value=[{'udid': 'phone', 'connection': 'USB'}]), self.assertRaises(ValueError):
            setup.start('bind', 'phone')

    def test_reveal_never_enables_or_accepts_developer_mode(self):
        lockdown = MagicMock(); lockdown.close = AsyncMock()
        amfi = MagicMock(); amfi.reveal_developer_mode_option_in_ui = AsyncMock()
        modules = {
            'pymobiledevice3.lockdown': MagicMock(create_using_usbmux=AsyncMock(return_value=lockdown)),
            'pymobiledevice3.services.amfi': MagicMock(AmfiService=MagicMock(return_value=amfi)),
            'pymobiledevice3.services.house_arrest': MagicMock(),
            'pymobiledevice3.services.installation_proxy': MagicMock(),
        }
        with patch.dict('sys.modules', modules), patch.dict(setup._STATE):
            asyncio.run(_perform('start', 'phone', None))
            amfi.reveal_developer_mode_option_in_ui.assert_awaited_once()
            amfi.enable_developer_mode.assert_not_called()
            amfi.enable_developer_mode_post_restart.assert_not_called()
            self.assertEqual(setup.status()['step'], 'developer')
        lockdown.close.assert_awaited_once()
