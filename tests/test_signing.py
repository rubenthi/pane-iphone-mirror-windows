import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from handset import signing

class SigningTests(unittest.TestCase):
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
