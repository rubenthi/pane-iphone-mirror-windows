"""Opt-in persistence and isolation from the existing mirroring path."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from handset import notifications as n


class NotificationPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {'PANE_DATA_DIR': self.directory.name})
        env.start()
        self.addCleanup(env.stop)
        # The native launch is mocked; Linux does not define this Windows flag.
        flag = patch.object(n.subprocess, 'CREATE_NO_WINDOW', 0, create=True)
        flag.start()
        self.addCleanup(flag.stop)
        listing = patch.object(n, 'devices', return_value={'audio': [], 'notifications': []})
        self.devices = listing.start()
        self.addCleanup(listing.stop)
        for name, value in [('_PROCESS', None), ('_NEXT_START', 0.0), ('_CACHED_HELPER', None), ('_ERROR', None), ('_DESKTOP_ACTIVE', False), ('_MIRRORING', False)]:
            mock = patch.object(n, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_defaults_are_private_and_background_is_opt_in(self):
        prefs = n.preferences()
        self.assertFalse(prefs['notifications_enabled'])
        self.assertFalse(prefs['background_enabled'])
        self.assertFalse(prefs['show_previews'])
        with patch.object(n, '_helper') as helper:
            n.session(desktop=True)
            helper.assert_not_called()

    def test_preferences_preserve_pairings_and_existing_settings(self):
        root = Path(self.directory.name)
        for name in ('settings.json', 'binding.json', 'setup.json'):
            (root / name).write_text('existing user data')
        n.save({'categories': ['mail'], 'background_enabled': True})
        n.save({'audio_device_id': 'paired-phone'})
        self.assertEqual(n.preferences()['categories'], ['mail'])
        self.assertTrue(n.preferences()['background_enabled'])
        for name in ('settings.json', 'binding.json', 'setup.json'):
            self.assertEqual((root / name).read_text(), 'existing user data')

    def test_untrusted_preferences_are_validated_without_coercion(self):
        for value in ({'background_enabled': 'false'}, {'categories': ['mail', 'mail']},
                      {'categories': ['unknown']}, {'categories': [None]},
                      {'notification_device_id': 'id\ncommand'}, {'unknown': True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                n.save(value)
        (Path(self.directory.name) / 'preferences.json').write_text(json.dumps({'background_enabled': 1, 'show_previews': True}))
        self.assertFalse(n.preferences()['background_enabled'])
        self.assertTrue(n.preferences()['show_previews'])

    def test_background_worker_starts_only_when_a_feature_needs_it(self):
        n.save({'background_enabled': True})
        with patch.object(n, '_helper', return_value=None) as helper:
            n.session(desktop=False, mirroring=False)
            helper.assert_not_called()
            n.save({'notifications_enabled': True})
            helper.assert_called_once()

    def test_saved_audio_starts_with_desktop_even_without_mirroring(self):
        with patch.object(n, '_helper', return_value=None) as helper:
            n.save({'audio_device_id':'saved-phone'})
            n.session(desktop=True, mirroring=False)
            helper.assert_called_once()
            helper.reset_mock()
            n.session(desktop=False, mirroring=False)
            helper.assert_not_called()

    def test_optional_worker_failure_does_not_break_mirror_state(self):
        with patch.object(n, '_write', side_effect=OSError('test disk failure')), self.assertLogs(level='ERROR'):
            n.session(desktop=True, mirroring=True)
        self.assertIn('could not be saved', n.status()['audio'])
        with patch.object(n, '_helper', side_effect=OSError('test launch failure')), self.assertLogs(level='ERROR'):
            n._ensure_running({**n.DEFAULTS, 'audio_device_id':'saved-phone'})
        self.assertIn('could not start', n.status()['notifications'])

    def test_reset_disables_background_before_deleting_owned_state(self):
        # A prebuilt local worker would otherwise start and lock the temp folder.
        with patch.object(n, '_helper', return_value=None):
            n.save({'background_enabled': True, 'notifications_enabled': True})
        with patch.object(n, '_alive', return_value=False):
            n.stop_for_reset()
        self.assertFalse(n.preferences()['background_enabled'])
        self.assertFalse(n.preferences()['notifications_enabled'])
        self.assertEqual(json.loads((Path(self.directory.name) / 'session.json').read_text()), {'desktop_pid': 0, 'mirroring': False})

    def test_helper_cache_cleanup_preserves_unknown_files(self):
        root = Path(self.directory.name)
        source = root / 'build.exe'
        source.write_bytes(b'test executable content, never launched')
        old = root / 'native' / ('a' * 20)
        kept = root / 'native' / ('b' * 20)
        unknown = root / 'native' / 'personal'
        for folder in (old, kept, unknown):
            folder.mkdir(parents=True)
            (folder / 'PaneCompanion.exe').write_bytes(b'obsolete test file')
        (kept / 'notes.txt').write_text('preserve me')
        windows = SimpleNamespace(name='nt', environ=os.environ, replace=os.replace)
        with patch.object(n, 'os', windows), patch.object(n, '_source_helper', return_value=source):
            target = n._helper()
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertFalse(old.exists())
        self.assertEqual((kept / 'notes.txt').read_text(), 'preserve me')
        self.assertTrue((unknown / 'PaneCompanion.exe').exists())

    def test_upgrade_publishes_helper_before_launch_without_changing_preferences(self):
        root = Path(self.directory.name)
        n._DESKTOP_ACTIVE = True
        n._write(root / 'preferences.json', {**n.DEFAULTS, 'notifications_enabled': True,
                                            'background_enabled': True})
        before = (root / 'preferences.json').read_bytes()
        helper = root / 'native' / ('c' * 20) / 'PaneCompanion.exe'
        process = SimpleNamespace(poll=lambda: None)
        def launch(*args, **kwargs):
            state = json.loads((root / 'session.json').read_text())
            self.assertEqual(state['helper_executable'], str(helper))
            self.assertEqual(state['desktop_pid'], os.getpid())
            return process
        with patch.object(n, '_helper', return_value=helper), patch.object(n.subprocess, 'Popen', side_effect=launch) as spawn:
            n._ensure_running()
            n._ensure_running()
        spawn.assert_called_once()
        self.assertEqual((root / 'preferences.json').read_bytes(), before)

    def test_same_version_background_worker_is_reused(self):
        root = Path(self.directory.name)
        helper = root / 'PaneCompanion.exe'
        n._write(root / 'companion-status.json', {'pid': 42, 'helper_executable': str(helper)})
        with patch.object(n, '_helper', return_value=helper), patch.object(n, '_alive', return_value=True), patch.object(n.subprocess, 'Popen') as spawn:
            n._ensure_running({**n.DEFAULTS, 'notifications_enabled': True, 'background_enabled': True})
        spawn.assert_not_called()

    def test_failed_replacement_is_rate_limited_but_normal_restart_is_not(self):
        helper = Path(self.directory.name) / 'PaneCompanion.exe'
        prefs = {**n.DEFAULTS, 'notifications_enabled': True, 'background_enabled': True}
        n._NEXT_START = 100
        n._PROCESS = SimpleNamespace(poll=lambda: 1)
        with patch.object(n, '_helper', return_value=helper), patch.object(n.time, 'monotonic', return_value=90), patch.object(n.subprocess, 'Popen') as spawn:
            n._ensure_running(prefs)
            spawn.assert_not_called()
            self.assertIn('could not restart', n.status()['notifications'])
            n._PROCESS = SimpleNamespace(poll=lambda: 0)
            n._ensure_running(prefs)
            spawn.assert_called_once()

    def test_explicit_enable_selects_only_the_unique_paired_iphone(self):
        self.devices.return_value = {'notifications': [
            {'id': 'pane', 'name': 'Pane-baf8'}, {'id': 'xbox', 'name': 'Xbox'},
            {'id': 'phone', 'name': 'iPhone'}, {'id': 'mouse', 'name': 'MX Master'},
            {'id': 'companion', 'name': 'Pane-iPhone'},
        ]}
        n.save({'categories': ['mail'], 'audio_device_id': 'audio-phone'})
        self.devices.assert_not_called()
        result = n.save({'notifications_enabled': True})['preferences']
        self.assertEqual(result['notification_device_id'], 'phone')
        self.assertTrue(result['notifications_enabled'])
        self.assertFalse(result['show_previews'])
        self.assertFalse(result['background_enabled'])
        self.assertEqual(result['categories'], ['mail'])
        self.assertEqual(result['audio_device_id'], 'audio-phone')

    def test_ambiguous_or_custom_phone_names_require_explicit_selection(self):
        for rows in ([{'id': 'one', 'name': 'iPhone'}, {'id': 'two', 'name': "Alice's IPHONE"}],
                     [{'id': 'one', 'name': "Alice's phone"}],
                     [{'id': 'companion', 'name': 'Pane-iPhone'}]):
            with self.subTest(rows=rows):
                self.devices.return_value = {'notifications': rows}
                result = n.save({'notifications_enabled': True})['preferences']
                self.assertEqual(result['notification_device_id'], '')
                self.assertTrue(result['notifications_enabled'])

    def test_device_suggestions_ignore_malformed_rows_and_deduplicate_ids(self):
        self.devices.return_value = {'notifications': [
            None, [], 'iPhone', {'name': 'iPhone'}, {'id': 123, 'name': 'iPhone'},
            {'id': '', 'name': 'iPhone'}, {'id': '   ', 'name': 'iPhone'},
            {'id': 'broken\nid', 'name': 'iPhone'}, {'id': 'x' * 2049, 'name': 'iPhone'},
            {'id': 'invalid-name', 'name': None},
            {'id': 'phone', 'name': 'My iPhone'}, {'id': 'phone', 'name': 'iPhone'},
        ]}
        self.assertEqual(n.save({'notifications_enabled': True})['preferences']['notification_device_id'], 'phone')

    def test_saved_or_explicit_device_selection_is_never_replaced(self):
        n.save({'notification_device_id': 'offline-phone'})
        self.assertEqual(n.save({'notifications_enabled': True})['preferences']['notification_device_id'], 'offline-phone')
        self.devices.assert_not_called()
        result = n.save({'notifications_enabled': True, 'notification_device_id': ''})['preferences']
        self.assertEqual(result['notification_device_id'], '')
        self.devices.assert_not_called()
        n.save({'notifications_enabled': True, 'notification_device_id': 'chosen-phone'})
        self.devices.assert_not_called()

    def test_device_enumeration_errors_do_not_prevent_the_explicit_opt_in(self):
        for listing in (None, [], {'error': 'unavailable', 'notifications': [{'id': 'phone', 'name': 'iPhone'}]},
                        {'notifications': None}):
            with self.subTest(listing=listing):
                self.devices.return_value = listing
                result = n.save({'notifications_enabled': True})['preferences']
                self.assertEqual(result['notification_device_id'], '')
                self.assertTrue(result['notifications_enabled'])
        self.devices.side_effect = OSError('device enumeration failed')
        self.assertTrue(n.save({'notifications_enabled': True})['preferences']['notifications_enabled'])

    def test_auto_selection_never_runs_for_implicit_or_disabled_preferences(self):
        n.save({'notifications_enabled': False})
        n.save({'show_previews': True})
        n.save({'categories': ['calls']})
        self.devices.assert_not_called()

    def test_structured_notification_phase_and_computer_name(self):
        root = Path(self.directory.name)
        helper = root / 'test-helper.exe'
        helper.write_bytes(b'test helper, never launched')
        def phase(prefs, message='', *, running=True, available=True, error=None, fresh=True):
            n._write(root / 'preferences.json', {**n.DEFAULTS, **prefs})
            n._write(root / 'companion-status.json', {'pid': 42, 'notifications': message})
            # Freshness follows applied preferences, not an arbitrary clock TTL.
            os.utime(root / 'preferences.json', ns=(100_000_000_000, 100_000_000_000))
            stamp = 101_000_000_000 if fresh else 99_000_000_000
            os.utime(root / 'companion-status.json', ns=(stamp, stamp))
            with (patch.object(n, 'os', SimpleNamespace(name='nt')),
                 patch.object(n, '_source_helper', return_value=helper if available else root / 'missing.exe'),
                 patch.object(n, '_alive', return_value=running), patch.object(n, '_ERROR', error),
                 patch.object(n.platform, 'node', return_value='My laptop')):
                state = n.status()
            self.assertEqual(state['computerName'], 'My laptop')
            return state['notificationPhase']
        enabled = {'notifications_enabled': True, 'notification_device_id': 'phone'}
        connected = 'Connected. Selected notifications will appear on this PC.'
        self.assertEqual(phase({}, connected), 'off')
        self.assertEqual(phase(enabled, connected, available=False), 'unavailable')
        self.assertEqual(phase({'notifications_enabled': True}), 'needs_device')
        self.assertEqual(phase(enabled, 'Connecting to iPhone notifications…'), 'connecting')
        self.assertEqual(phase(enabled, connected), 'ready')
        self.assertEqual(phase(enabled, connected, running=False), 'connecting')
        self.assertEqual(phase(enabled, connected, fresh=False), 'connecting')
        self.assertEqual(phase(enabled, 'Waiting for iPhone. Enable Share System Notifications in its Bluetooth settings.'), 'needs_permission')
        self.assertEqual(phase(enabled, 'Check Windows notification permissions for Pane.'), 'needs_windows_permission')
        self.assertEqual(phase(enabled, 'Windows could not show notifications. Check notification permissions for Pane.'), 'needs_windows_permission')
        self.assertEqual(phase(enabled, 'iPhone disconnected. Waiting for Bluetooth to reconnect.'), 'connecting')
        self.assertEqual(phase(enabled, 'Bluetooth services could not restart.'), 'error')
        self.assertEqual(phase(enabled, connected, error='worker failed'), 'error')

    def test_notification_settings_only_opens_windows_settings(self):
        from unittest.mock import Mock
        launch = Mock()
        with patch.object(n, 'os', SimpleNamespace(name='nt', startfile=launch)):
            n.open_notification_settings()
        launch.assert_called_once_with('ms-settings:notifications')
        launch.reset_mock()
        with patch.object(n, 'os', SimpleNamespace(name='posix', startfile=launch)):
            with self.assertRaises(ValueError):
                n.open_notification_settings()
        launch.assert_not_called()
