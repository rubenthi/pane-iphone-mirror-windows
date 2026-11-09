"""Exercise the Windows signing bridge with real pipes and DPAPI, without Apple or USB."""
import hashlib
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from handset import companion_update, setup, signing


# Emulate the pinned worker's JSON-lines requests and email-derived storage key.
HELPER = """
import hashlib,json,sys
def send(**ev):
    print(json.dumps(ev),flush=True)
def ask(**ev):
    send(**ev)
    return json.loads(input())
request=json.loads(input())
assert request['password']=='fixture-password'
key=hashlib.sha256(request['email'].encode()).hexdigest()+'/key'
stored=ask(event='retrieve',key=key)['value']
if stored is None:
    assert ask(event='store',key=key,value='fixture-private-key')['ok']
    answer=ask(event='prompt',kind='certificate',choices=[{'id':'old','name':'Pane'}])
    assert answer=={'value':'old','confirmed':True}
else:
    assert stored=='fixture-private-key'
send(event='complete')
"""


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI and process pipes')
class SigningWorkflowTests(unittest.TestCase):
    def test_interrupted_bundled_copy_discards_only_its_partial_upload(self):
        def interrupted(source, destination):
            destination.write_bytes(b'partial')
            raise OSError('Disk full')
        with tempfile.TemporaryDirectory() as directory, patch.object(signing, 'DATA_DIR', Path(directory)):
            root = Path(directory)
            original = root / 'bundled.ipa'
            original.write_bytes(b'original package')
            with (patch.object(signing, 'bundled_package', return_value=original),
                  patch.object(signing.shutil, 'copyfile', side_effect=interrupted)):
                with self.assertRaisesRegex(ValueError, 'free disk space'):
                    signing.stage_bundled()
            self.assertEqual(original.read_bytes(), b'original package')
            self.assertEqual(list((root / 'staging').iterdir()), [])

    def wait_phase(self, expected):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = signing.status()
            if current['phase'] == expected and (expected != 'complete' or signing._PROCESS is None):
                return current
            if current['phase'] == 'error':
                self.fail(current['note'])
            time.sleep(.02)
        self.fail('Timed out waiting for ' + expected)

    def test_bound_renewal_reuses_key_after_email_case_change(self):
        real_popen = subprocess.Popen
        def launch(args, **kwargs):
            self.assertEqual(args, [sys.executable])
            return real_popen([sys.executable, '-I', '-u', '-c', HELPER], **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = root / 'binding.json'
            binding.write_text(json.dumps({'udid':'fixture-phone','token':'fixture-binding'}))
            original = binding.read_bytes()
            pair = root / 'device' / 'remote_fixture.plist'
            pair.parent.mkdir()
            pair.write_bytes(b'fixture-pairing')
            with (patch.object(signing, 'DATA_DIR', root), patch.object(setup, 'DATA_DIR', root),
                  patch.object(companion_update, 'DATA_DIR', root), patch.dict(signing._STATE, phase='idle'),
                  patch.dict(setup._STATE, phase='idle', developerEnabled=True),
                  patch.object(setup, 'require_usb'), patch.object(signing, 'helper_path', return_value=Path(sys.executable)),
                  patch.object(signing.subprocess, 'Popen', side_effect=launch)):
                try:
                    for i, account in enumerate(('Fixture@Example.invalid', 'fixture@example.invalid')):
                        ipa = root / 'staged.ipa'
                        with zipfile.ZipFile(ipa, 'w') as z:
                            z.writestr('Payload/Pane.app/Info.plist', plistlib.dumps({
                                'CFBundleIdentifier':'app.fixture','CFBundleExecutable':'PaneFiles','PaneProtocolVersion':1}))
                        signing.start('fixture-phone', ipa, account, 'fixture-password')
                        if i == 0:
                            state = self.wait_phase('prompt')
                            with self.assertRaises(ValueError):
                                signing.answer(state['prompt']['id'], 'old', False)
                            signing.answer(state['prompt']['id'], 'old', True)
                        complete = self.wait_phase('complete')
                        self.assertFalse(ipa.exists())
                        self.assertIn('preserved', complete['note'])
                        self.assertEqual(binding.read_bytes(), original)
                        self.assertEqual(pair.read_bytes(), b'fixture-pairing')
                    keys = list((root/'signing').rglob('*.bin'))
                    self.assertEqual(len(keys), 1)
                    self.assertEqual(signing.protect(keys[0].read_bytes(), True), b'fixture-private-key')
                    for path in root.rglob('*'):
                        if path.is_file():
                            for private in (b'fixture-password', b'fixture-private-key', b'example.invalid'):
                                self.assertNotIn(private, path.read_bytes())
                finally:
                    if signing._PROCESS is not None:
                        signing.cancel()

    def test_prior_mixed_case_key_is_preserved_and_conflicting_store_fails(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(signing, 'DATA_DIR', Path(directory)):
            def digest(s):
                return hashlib.sha256(s.encode()).hexdigest()
            account = digest('a@b.invalid')
            old = digest('A@B.invalid') + '/key'
            folder = Path(directory) / 'signing' / account
            folder.mkdir(parents=True)
            path = folder / (digest(old) + '.bin')
            original = signing.protect(b'first')
            path.write_bytes(original)
            for key in (old, account + '/key', digest('a@B.invalid') + '/key'):
                self.assertEqual(signing._storage(account, {'event':'retrieve','key':key}, key), {'value':'first'})
            with self.assertRaisesRegex(ValueError,'already exists'):
                signing._storage(account, {'event':'store','key':old,'value':'second'}, old)
            self.assertEqual(path.read_bytes(), original)
