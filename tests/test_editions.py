import json
import os
import subprocess
import sys
import unittest


class DesktopEditionsTests(unittest.TestCase):
    def test_source_and_packaged_defaults_are_independent(self):
        code = """
import json, sys
sys.frozen = sys.argv[1] == 'release'
from handset.edition import APP_NAME, PORT, STREAM_PORT, data_dir
print(json.dumps([APP_NAME, data_dir().name, PORT, STREAM_PORT]))
"""
        env = {k: v for k, v in os.environ.items() if k not in {'PANE_DATA_DIR', 'PANE_PORT', 'PANE_STREAM_PORT'}}
        for mode, name, port in [('source', 'Pane (Development)', 8775), ('release', 'Pane', 8765)]:
            with self.subTest(mode=mode):
                result = subprocess.check_output([sys.executable, '-c', code, mode], text=True, env=env)
                self.assertEqual(json.loads(result), [name, name, port, port + 1])
