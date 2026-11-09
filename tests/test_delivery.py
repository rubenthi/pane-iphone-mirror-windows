import errno
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from handset import transfers


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.downloads = self.root / 'Downloads'
        self.store = transfers.TransferStore(self.root / 'profile', self.downloads)
        self.data = bytes(range(256)) * 2049
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.id, self.part = self.store.incoming(
            {'id': '1' * 32, 'size': len(self.data), 'sha256': self.digest, 'name': 'example.bin'}, 'phone')
        self.part.write_bytes(self.data)

    def test_same_volume_keeps_file_identity(self):
        inode = self.part.stat().st_ino
        self.assertTrue(self.store.deliver(self.id, self.part, self.digest))
        final = self.downloads / 'example.bin'
        self.assertEqual(final.stat().st_ino, inode)
        self.assertEqual(final.read_bytes(), self.data)
        self.assertFalse(self.part.exists())

    def test_cross_volume_copies_exclusively_and_cleans_staging(self):
        self.downloads.mkdir()
        original = self.downloads / 'example.bin'
        original.write_bytes(b'keep')
        publish = self.store._publish

        def cross_volume(path, *args):
            if path == self.part:
                raise OSError(errno.EXDEV, 'cross-device')
            return publish(path, *args)

        with patch.object(self.store, '_publish', side_effect=cross_volume):
            self.assertTrue(self.store.deliver(self.id, self.part, self.digest))
        self.assertEqual(original.read_bytes(), b'keep')
        self.assertEqual((self.downloads / 'example (1).bin').read_bytes(), self.data)
        self.assertFalse(list(self.downloads.glob('*.part')))
        self.assertFalse(self.part.exists())

    def test_pause_during_verification_keeps_file_for_resume(self):
        hashing, release = threading.Event(), threading.Event()
        results = []

        def slow_hash(path, *, sync_to_disk):
            self.assertTrue(sync_to_disk)
            hashing.set()
            if not release.wait(3):
                raise RuntimeError('queued controls blocked by file verification')
            return self.digest

        with patch.object(transfers, 'digest_file', side_effect=slow_hash):
            thread = threading.Thread(target=lambda: results.append(self.store.deliver(self.id, self.part, self.digest)))
            thread.start()
            try:
                self.assertTrue(hashing.wait(2))
                self.store.control(self.id, 'pause')
            finally:
                release.set()
                thread.join(4)
        self.assertEqual(results, [None])
        self.assertTrue(self.part.exists())
        self.assertFalse((self.downloads / 'example.bin').exists())
        self.store.control(self.id, 'resume')
        self.assertTrue(self.store.deliver(self.id, self.part, self.digest))
