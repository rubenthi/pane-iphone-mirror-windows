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
        for name, value in [('_PROCESS', None), ('_CACHED_HELPER', None), ('_ERROR', None), ('_DESKTOP_ACTIVE', False), ('_MIRRORING', False)]:
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
