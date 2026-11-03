"""Exercise the actual background PowerShell helper with a hostile inherited module path."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from handset import updater

OLD = b'previous installation fixture'
NEW = b'verified replacement fixture'


def child(directory):
    root = Path(directory)
    stage = root / 'stage'
    stage.mkdir()
    target = root / 'Pane.exe'
    target.write_bytes(OLD)
    version = updater.VERSION
    manifest = dict(version=version, url=f'{updater.BASE}/download/v{version}/Pane.exe',
                    size=len(NEW), sha256=hashlib.sha256(NEW).hexdigest())
    replies = [io.BytesIO(json.dumps(manifest).encode()), io.BytesIO(NEW)]
    os.environ['PSModulePath'] = str(root / 'nonexistent-modules')
    with patch.object(sys, 'frozen', True, create=True), patch.object(updater, 'VERSION', '0.0.0'), patch.object(updater.tempfile, 'mkdtemp', return_value=str(stage)), patch.object(updater.urllib.request, 'urlopen', side_effect=replies):
        updater.check()
    assert updater.status()['phase'] == 'ready', updater.status()
    with patch.object(sys, 'executable', str(target)):
        updater.apply_on_exit()
    time.sleep(1)
    assert target.read_bytes() == OLD, 'Replaced the executable before process exit'


@unittest.skipUnless(os.name == 'nt', 'Windows updater integration')
class HandoffTests(unittest.TestCase):
    def test_staging_wait_replacement_backup_and_module_environment(self):
        with tempfile.TemporaryDirectory(prefix='Pane-handoff-', ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            subprocess.run([sys.executable, __file__, '--child', directory], check=True, timeout=30)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if (root / 'Pane.exe').read_bytes() == NEW:
                    break
                time.sleep(.1)
            logs = '\n'.join(p.read_text(errors='replace') for p in (root / 'stage').glob('*.log'))
            self.assertEqual((root / 'Pane.exe').read_bytes(), NEW, logs)
            backups = list(root.glob('Pane.exe.backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), OLD)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        unittest.main()
