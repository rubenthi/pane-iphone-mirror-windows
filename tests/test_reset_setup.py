import asyncio
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from handset.state import prepare_state, write_json
from handset.setup import inspect_ipa, _perform
from handset import setup, state


class ResetTests(unittest.TestCase):
    def test_upgrades_preserve_state_and_only_explicit_reset_erases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'Pane'
            for name in ('window', 'webview', 'device', 'staging', 'outbox'):
                (root / name).mkdir(parents=True)
                (root / name / 'old').write_text('private')
            for name in ('pane.log', 'settings.json', 'binding.json', 'setup.json', 'transfers.json'):
                (root / name).write_text('private')
            downloads = Path(directory) / 'Downloads'; downloads.mkdir()
            (downloads / 'personal').write_text('keep')
            self.assertFalse(prepare_state(root))
            self.assertEqual((root / 'binding.json').read_text(), 'private')
            self.assertEqual((root / 'webview' / 'old').read_text(), 'private')
            write_json(root / 'state-version.json', {'schema': 1})
            self.assertFalse(prepare_state(root))
            self.assertEqual((root / 'binding.json').read_text(), 'private')
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
            prepare_state(root, force=True)
            self.assertTrue((outside / 'keep').exists())

    def test_legacy_pairings_are_copied_without_overwriting_and_reset_does_not_restore_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'Pane'; legacy=Path(directory)/'legacy'; legacy.mkdir()
            (legacy/'remote_phone.plist').write_bytes(b'paired')
            (legacy/'remote_new.plist').write_bytes(b'older')
            (root/'device').mkdir(parents=True)
            (root/'device'/'remote_new.plist').write_bytes(b'current')
            common=MagicMock(_HOMEFOLDER=legacy)
            with patch.object(state,'DEVELOPMENT',False), patch.object(state,'DATA_DIR',root), patch.dict('sys.modules',{'pymobiledevice3':MagicMock(common=common)}):
                prepare_state(root)
                state.isolate_device_state()
                self.assertEqual((root/'device'/'remote_phone.plist').read_bytes(),b'paired')
                self.assertEqual((root/'device'/'remote_new.plist').read_bytes(),b'current')
                self.assertTrue((legacy/'remote_phone.plist').exists())
                prepare_state(root,force=True)
                common._HOMEFOLDER=legacy
                state.isolate_device_state()
                self.assertFalse((root/'device'/'remote_phone.plist').exists())


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(setup, 'DATA_DIR', Path(self.tmp.name))
        patcher.start(); self.addCleanup(patcher.stop)

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


    def test_saved_pairings_skip_onboarding_even_when_phone_is_offline(self):
        with patch.object(setup, 'wifi_paired_udids', return_value=[]):
            self.assertTrue(setup.status()['onboardingRequired'])
            write_json(setup.DATA_DIR / 'binding.json', {'udid': 'saved-phone'})
            self.assertFalse(setup.status()['onboardingRequired'])
            write_json(setup.DATA_DIR / 'binding.json', {'udid': 'new-phone', 'onboardingComplete': False})
            self.assertTrue(setup.status()['onboardingRequired'])
        (setup.DATA_DIR / 'binding.json').unlink()
        with patch.object(setup, 'wifi_paired_udids', return_value=['legacy-phone']):
            self.assertFalse(setup.status()['onboardingRequired'])

    def test_disabled_developer_checks_reveal_hidden_toggle_without_enabling(self):
        for action in ('developer', 'check'):
            with self.subTest(action=action):
                lockdown = MagicMock(close=AsyncMock(), get_developer_mode_status=AsyncMock(return_value=False))
                amfi = MagicMock(reveal_developer_mode_option_in_ui=AsyncMock())
                modules = {
                    'pymobiledevice3.lockdown': MagicMock(create_using_usbmux=AsyncMock(return_value=lockdown)),
                    'pymobiledevice3.services.amfi': MagicMock(AmfiService=MagicMock(return_value=amfi)),
                    'pymobiledevice3.services.house_arrest': MagicMock(),
                    'pymobiledevice3.services.installation_proxy': MagicMock(),
                }
                with patch.dict('sys.modules', modules), patch.dict(setup._STATE, developerEnabled=True), patch.object(setup, '_companion', new_callable=AsyncMock) as companion:
                    with self.assertRaisesRegex(ValueError, 'Pane asked the iPhone to reveal'):
                        asyncio.run(_perform(action, 'phone', None))
                    self.assertFalse(setup.status()['developerEnabled'])
                    self.assertTrue(setup.status()['revealed'])
                    self.assertEqual(setup.status()['step'], 'developer')
                    companion.assert_not_awaited()
                amfi.reveal_developer_mode_option_in_ui.assert_awaited_once()
                amfi.enable_developer_mode.assert_not_called()
                amfi.enable_developer_mode_post_restart.assert_not_called()
                lockdown.close.assert_awaited_once()

    def test_developer_reveal_rejection_is_not_reported_as_success(self):
        lockdown = MagicMock(close=AsyncMock(), get_developer_mode_status=AsyncMock(return_value=False))
        amfi = MagicMock(reveal_developer_mode_option_in_ui=AsyncMock(side_effect=RuntimeError('Device refused reveal')))
        modules = {
            'pymobiledevice3.lockdown': MagicMock(create_using_usbmux=AsyncMock(return_value=lockdown)),
            'pymobiledevice3.services.amfi': MagicMock(AmfiService=MagicMock(return_value=amfi)),
            'pymobiledevice3.services.house_arrest': MagicMock(),
            'pymobiledevice3.services.installation_proxy': MagicMock(),
        }
        with patch.dict('sys.modules', modules), patch.dict(setup._STATE, developerEnabled=True, revealed=False):
            with self.assertRaisesRegex(RuntimeError, 'Device refused reveal'):
                asyncio.run(_perform('developer', 'phone', None))
            self.assertFalse(setup.status()['developerEnabled'])
            self.assertFalse(setup.status()['revealed'])
        lockdown.close.assert_awaited_once()

    def test_developer_check_does_not_require_companion_already_installed(self):
        lockdown = MagicMock()
        lockdown.close = AsyncMock()
        lockdown.get_developer_mode_status = AsyncMock(return_value=True)
        modules = {
            'pymobiledevice3.lockdown': MagicMock(create_using_usbmux=AsyncMock(return_value=lockdown)),
            'pymobiledevice3.services.amfi': MagicMock(),
            'pymobiledevice3.services.house_arrest': MagicMock(),
            'pymobiledevice3.services.installation_proxy': MagicMock(),
        }
        with patch.dict('sys.modules', modules), patch.dict(setup._STATE), patch.object(setup, '_companion', new_callable=AsyncMock) as companion:
            asyncio.run(_perform('developer', 'phone', None))
            companion.assert_not_awaited()
            self.assertTrue(setup.status()['developerEnabled'])
            self.assertEqual(setup.status()['step'], 'install')
        lockdown.close.assert_awaited_once()
