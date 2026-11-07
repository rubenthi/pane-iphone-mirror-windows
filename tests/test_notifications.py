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

    def test_optional_worker_failure_does_not_break_mirror_state(self):
        with patch.object(n, '_write', side_effect=OSError('test disk failure')), self.assertLogs(level='ERROR'):
            n.session(desktop=True, mirroring=True)
        self.assertIn('could not be saved', n.status()['audio'])
        with patch.object(n, '_helper', side_effect=OSError('test launch failure')), self.assertLogs(level='ERROR'):
            n._ensure_running()
        self.assertIn('could not start', n.status()['notifications'])

    def test_reset_disables_background_before_deleting_owned_state(self):
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
