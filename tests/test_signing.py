import json
import io
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from handset import signing

class SigningTests(unittest.TestCase):
    def test_certificate_revocation_requires_listed_choice_and_explicit_confirmation(self):
        prompt = {'id':'current', 'kind':'certificate', 'choices':[{'id':'old-pane'}]}
        answers = queue.Queue()
        with patch.dict(signing._STATE, phase='prompt', prompt=prompt), patch.object(signing, '_ANSWERS', answers):
            for value, confirmation in [('old-pane', False), ('old-pane', 'true'), ('unlisted', True)]:
                with self.assertRaises(ValueError): signing.answer('current', value, confirmation)
            self.assertTrue(answers.empty())
            signing.answer('current', 'old-pane', True)
            self.assertEqual(answers.get_nowait(), {'value':'old-pane','confirmed':True})
            self.assertEqual(signing.status()['phase'], 'working')
            with self.assertRaises(ValueError): signing.answer('current', 'old-pane', True)
    def test_worker_error_retains_safe_diagnostics_and_clears_credentials(self):
        process = MagicMock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO(json.dumps({'event': 'error', 'code': 'connection', 'stage': 2, 'note': 'A signing connection failed.'}) + '\n')
        process.poll.return_value = 1
        initial = {'email': 'private@example.com', 'password': 'test-secret', 'udid': 'phone'}
        with tempfile.TemporaryDirectory() as directory, patch.dict(signing._STATE, phase='working', prompt=None), patch.object(signing, '_PROCESS', process):
            package = Path(directory) / 'staged.ipa'
            package.write_bytes(b'test')
            signing._run(process, package, initial)
            state = signing.status()
            self.assertEqual((state['phase'], state['code'], state['stage']), ('error', 'connection', 2))
            self.assertNotIn('test-secret', json.dumps(state))
            self.assertNotIn('private@example.com', json.dumps(state))
            self.assertEqual(initial, {})
            self.assertFalse(package.exists())
            self.assertTrue(process.stdin.closed)
    def test_protected_storage_hides_values_and_paths(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(signing, 'DATA_DIR', Path(directory)), patch.object(signing, 'protect', side_effect=lambda data, decrypt=False: data[6:] if decrypt else b'cipher'+data):
            signing._storage('account', {'event':'store','key':'../../certificate','value':'private-key'})
            files=list(Path(directory).rglob('*.bin'))
            self.assertEqual(len(files),1)
            self.assertEqual(files[0].parent,Path(directory)/'signing'/'account')
            self.assertEqual(files[0].read_bytes(),b'cipherprivate-key')
            self.assertEqual(signing._storage('account',{'event':'retrieve','key':'../../certificate'}),{'value':'private-key'})
    def test_stale_prompt_and_unlisted_team_rejected(self):
        with patch.dict(signing._STATE, phase='prompt', prompt={'id':'current','kind':'team','choices':[{'id':'mine'}]}):
            with self.assertRaises(ValueError): signing.answer('old','mine')
            with self.assertRaises(ValueError): signing.answer('current','someone-else')
    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows DPAPI integration')
    def test_windows_encryption_round_trip(self):
        original=b'signing-secret'
        protected=signing.protect(original)
        self.assertNotIn(original,protected)
        self.assertEqual(signing.protect(protected,True),original)
