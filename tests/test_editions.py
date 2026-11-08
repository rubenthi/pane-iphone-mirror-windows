import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from handset import updater


class DesktopEditionsTests(unittest.TestCase):
    def test_source_and_packaged_defaults_are_independent(self):
        code = """
import json, sys
sys.frozen = sys.argv[1] != 'source'
from handset.edition import APP_NAME, PORT, STREAM_PORT, data_dir
print(json.dumps([APP_NAME, data_dir().name, PORT, STREAM_PORT]))
"""
        env = {k: v for k, v in os.environ.items() if k not in {'PANE_DATA_DIR', 'PANE_PORT', 'PANE_STREAM_PORT'}}
        for mode, name, port in [('source', 'Pane (Development)', 8775), ('release', 'Pane', 8765), ('frozen-development', 'Pane (Development)', 8775)]:
            with self.subTest(mode=mode):
                args = [sys.executable, '-c', code, mode]
                if mode == 'frozen-development':
                    args.append('--development')
                result = subprocess.check_output(args, text=True, env=env)
                self.assertEqual(json.loads(result), [name, name, port, port + 1])


    def test_frozen_development_never_checks_or_applies_production_updates(self):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'argv', ['Pane.exe', '--development']), \
             patch.object(updater.urllib.request, 'urlopen') as fetch, \
             patch.object(updater.subprocess, 'Popen') as launch, \
             patch.object(updater, '_STAGED', ('unused-helper', 'unused-exe', 'a' * 64)), \
             patch.dict(updater._STATE, {}, clear=True):
            updater.check()
            self.assertEqual(updater.status()['phase'], 'source')
            updater.apply_on_exit()
            fetch.assert_not_called()
            launch.assert_not_called()

    def test_frozen_production_retains_automatic_update_check(self):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'argv', ['Pane.exe']), \
             patch.object(updater.os, 'name', 'nt'), \
             patch.object(updater.urllib.request, 'urlopen', side_effect=OSError('offline test')) as fetch, \
             patch.object(updater.logging, 'exception'), \
             patch.dict(updater._STATE, {}, clear=True):
            updater.check()
            fetch.assert_called_once_with(updater.MANIFEST_URL, timeout=20)
            self.assertEqual(updater.status()['phase'], 'error')
