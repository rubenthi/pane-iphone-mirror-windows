import asyncio
import sys
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from handset import companion_update as update
from handset.state import write_json, read_json

class CompanionUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = patch.object(update, 'DATA_DIR', self.root); self.data.start()
        self.devices = patch.object(update, 'list_devices', return_value=[]); self.mock_devices = self.devices.start()
        self.package = patch.object(update, 'validate_companion')
        self.validate = self.package.start()
        self.addCleanup(self.package.stop)
        update._LAST.clear(); update._RESULTS.clear(); update._INVALIDATED.clear()
        write_json(self.root / 'binding.json', {'udid': 'phone', 'bundle': 'app'})
    def tearDown(self):
        self.devices.stop(); self.data.stop(); self.temp.cleanup()
    def saved(self, version='2.2.0', udid='phone', bundle='app'):
        write_json(self.root / 'companion-version.json', {'udid': udid, 'bundle': bundle, 'version': version})
    def test_unknown_disconnected_does_not_prompt(self):
        self.assertFalse(update.check()['updateAvailable'])
    def test_old_cached_phone_requires_a_matching_local_package(self):
        self.saved()
        self.validate.side_effect = ValueError('wrong package')
        self.assertTrue(update.check()['packageUnavailable'])
        self.assertFalse(update.check()['updateAvailable'])
    def test_cached_older_prompts_and_current_or_newer_does_not(self):
        for value, expected in [('2.2.0', True), ('2.3.0', True), (update.COMPANION_VERSION, False), ('3.0', False), ('invalid', False)]:
            self.saved(value)
            self.assertEqual(update.check()['updateAvailable'], expected)
    def test_other_phone_or_bundle_cannot_supply_baseline(self):
        self.saved(udid='other'); self.assertFalse(update.check()['updateAvailable'])
        self.saved(bundle='other'); self.assertFalse(update.check()['updateAvailable'])
    def test_usb_verified_and_cached_with_throttle(self):
        self.mock_devices.return_value = [{'udid': 'phone', 'connection': 'USB'}]
        with patch.object(update, '_read', AsyncMock(return_value={'version': '2.2.0', 'bundle': 'app'})) as read:
            self.assertTrue(update.check()['updateAvailable'])
            self.assertTrue(update.check()['updateAvailable'])
            self.assertEqual(read.await_count, 1)
        self.mock_devices.return_value = []
        self.assertTrue(update.check()['cached'])
    def test_missing_ambiguous_or_failed_read_clears_stale_baseline(self):
        self.mock_devices.return_value = [{'udid': 'phone', 'connection': 'USB'}]
        for result in [None, TimeoutError()]:
            update._LAST.clear(); self.saved()
            reader = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
            with patch.object(update, '_read', reader):
                self.assertIsNone(update.check()['installedVersion'])
            self.assertNotIn('version', read_json(self.root / 'companion-version.json', {}))
    def test_install_invalidation_preserves_identity_and_settings(self):
        self.saved(); write_json(self.root / 'preferences.json', {'keep': True})
        update.invalidate('phone')
        self.assertFalse(update.check()['updateAvailable'])
        self.assertEqual(read_json(self.root / 'binding.json', {}), {'udid':'phone', 'bundle':'app'})
        self.assertEqual(read_json(self.root / 'preferences.json', {}), {'keep':True})
    def test_install_cache_write_failure_is_nonfatal_and_forgets_old_version(self):
        self.saved()
        with patch.object(update, 'write_json', side_effect=PermissionError()), patch.object(Path, 'unlink', side_effect=PermissionError()):
            update.invalidate('phone')
        self.assertFalse(update.check()['updateAvailable'])
    def test_corrupt_state_and_long_version_fail_quietly(self):
        write_json(self.root / 'binding.json', [])
        write_json(self.root / 'setup.json', 'bad')
        self.assertFalse(update.check()['updateAvailable'])
        self.assertIsNone(update.version('9' * 10000))
    def test_failed_disk_write_keeps_verified_result_in_memory(self):
        self.saved()
        self.mock_devices.return_value = [{'udid': 'phone', 'connection': 'USB'}]
        with patch.object(update, '_read', AsyncMock(return_value={'version':update.COMPANION_VERSION, 'bundle':'app'})), patch.object(update, 'write_json', side_effect=OSError()):
            self.assertFalse(update.check()['updateAvailable'])
            self.assertFalse(update.check()['updateAvailable'])
    def test_ambiguous_devices_without_binding_do_not_use_cached_identity(self):
        write_json(self.root / 'binding.json', {})
        self.saved()
        self.mock_devices.return_value = [{'udid': d, 'connection':'USB'} for d in ['phone', 'other']]
        with patch.object(update, '_read', AsyncMock()) as read:
            self.assertFalse(update.check()['updateAvailable']); read.assert_not_awaited()
    def test_wifi_is_not_used_for_verification(self):
        self.mock_devices.return_value = [{'udid': 'phone', 'connection': 'Network'}]
        with patch.object(update, '_read', AsyncMock()) as read:
            update.check(); read.assert_not_awaited()
    def test_usb_reader_requires_existing_trust_and_unique_matching_app(self):
        phone = AsyncMock()
        installer = AsyncMock()
        service = MagicMock(); service.return_value.__aenter__ = AsyncMock(return_value=installer)
        service.return_value.__aexit__ = AsyncMock(return_value=False)
        app = {'CFBundleExecutable':'PaneFiles', 'CFBundleDisplayName':'Pane', 'CFBundleIdentifier':'app', 'CFBundleShortVersionString':'2.2.0'}
        connect = AsyncMock(return_value=phone)
        # Keep this read-only protocol test independent of optional device packages.
        modules = {'pymobiledevice3.lockdown': SimpleNamespace(create_using_usbmux=connect),
                   'pymobiledevice3.services.installation_proxy': SimpleNamespace(InstallationProxyService=service)}
        with patch.dict(sys.modules, modules):
            for apps, expected in [([], None), ([app, app], None), ([dict(app, CFBundleShortVersionString='bad')], None), ([app], {'version':'2.2.0','bundle':'app'})]:
                installer.browse.return_value = apps
                self.assertEqual(asyncio.run(update._read('phone', 'app')), expected)
            connect.assert_awaited_with(serial='phone', connection_type='USB', autopair=False)
            self.assertEqual(phone.close.await_count,4)
    def test_check_timeout_is_bounded(self):
        self.mock_devices.return_value = [{'udid': 'phone', 'connection': 'USB'}]
        async def slow(*args): await asyncio.sleep(1)
        with patch.object(update, '_read', slow), patch.object(update, 'CHECK_SECONDS', .01):
            self.assertFalse(update.check()['updateAvailable'])

if __name__ == '__main__': unittest.main()
