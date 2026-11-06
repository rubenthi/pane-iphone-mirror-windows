import asyncio
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from handset.bluetooth import Bluetooth, Rpc
from handset.transfers import TransferStore, safe_name, CHUNK, MAX_FILE


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.downloads = self.root / 'Downloads'
        self.store = TransferStore(self.root / 'Pane', self.downloads)

    def stage(self, data, name='file.txt'):
        identifier = self.store.begin(name, len(data))['id']
        for pos in range(0, len(data), CHUNK):
            self.store.append(identifier, pos, base64.b64encode(data[pos:pos+CHUNK]).decode())
        return self.store.finish(identifier, 'file')

    def test_malicious_names_cannot_escape_downloads_or_create_device_files(self):
        for name in ('../../escape.txt', 'C:\\Windows\\test', 'CON', 'LPT1.txt', 'nul.', 'a\x00b'):
            safe = safe_name(name)
            self.assertEqual(Path(safe).name, safe)
            self.assertNotIn(':', safe)
            self.assertNotIn('\\', safe)
            self.assertNotIn('\x00', safe)
        self.assertEqual(safe_name('CON.txt'), '_CON.txt')

    def test_chunk_order_limits_and_empty_files(self):
        identifier = self.store.begin('x', 3)['id']
        for offset, data in ((1, b'a'), (0, b'abcd')):
            with self.assertRaises(ValueError):
                self.store.append(identifier, offset, base64.b64encode(data).decode())
        with self.assertRaises(ValueError): self.store.finish(identifier, 'file')
        self.store.append(identifier, 0, 'YWJj')
        result = self.store.finish(identifier, 'file')
        self.assertEqual(result['path'].read_bytes(), b'abc')
        self.assertEqual(self.stage(b'')['path'].stat().st_size, 0)
        for size in (-1, True, MAX_FILE+1):
            with self.assertRaises(ValueError): self.store.begin('x', size)

    def test_queued_files_count_towards_disk_budget(self):
        for _ in range(8): self.stage(b'x')
        with self.assertRaises(ValueError): self.store.begin('overflow', 1)

    def test_cancel_and_restart_cleanup_only_owned_files(self):
        item = self.stage(b'private')
        self.store.cancel(item['id'])
        self.assertFalse(item['path'].exists())
        item = self.stage(b'pending')
        unrelated = self.store.root / 'staging' / 'personal.txt'
        unrelated.write_text('preserve')
        reopened = TransferStore(self.store.root, self.downloads)
        self.assertEqual(reopened.rows[-1]['state'], 'failed')
        self.assertFalse(item['path'].exists())
        self.assertTrue(unrelated.exists())

    def remote(self, data, name='photo.jpg'):
        return {'id': '1'*32, 'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def test_atomic_delivery_never_overwrites_and_lost_ack_is_deduplicated(self):
        self.downloads.mkdir()
        (self.downloads / 'photo.jpg').write_bytes(b'original')
        metadata = self.remote(b'new')
        identifier, part = self.store.incoming(metadata, 'phone')
        part.write_bytes(b'new')
        self.store.deliver(identifier, part, metadata['sha256'])
        self.assertEqual((self.downloads / 'photo.jpg').read_bytes(), b'original')
        self.assertEqual((self.downloads / 'photo (1).jpg').read_bytes(), b'new')
        self.assertIsNone(self.store.incoming(metadata, 'phone'))
        self.assertFalse(list(self.downloads.glob('*.part')))

    def test_checksum_failure_does_not_publish(self):
        metadata = self.remote(b'valid')
        identifier, part = self.store.incoming(metadata, 'phone')
        part.write_bytes(b'wrong')
        with self.assertRaises(ValueError): self.store.deliver(identifier, part, metadata['sha256'])
        self.assertFalse(self.downloads.exists())

    def test_both_directions_over_rpc_with_progress_and_integrity(self):
        data = bytes(range(256)) * 40
        self.stage(data)
        row, path = self.store.next_outgoing()
        remote = self.remote(data)
        class Peer:
            received = bytearray()
            acked = False
            async def call(peer, op, **fields):
                if op == 'begin': self.assertEqual(fields['sha256'], hashlib.sha256(data).hexdigest())
                if op == 'write':
                    self.assertEqual(fields['offset'], len(peer.received))
                    peer.received.extend(base64.b64decode(fields['data']))
                    return {'offset': len(peer.received)}
                if op == 'read':
                    return {'data': base64.b64encode(data[fields['offset']:fields['offset']+fields['length']]).decode()}
                if op == 'received': peer.acked = True
                return {'ok': True}
        peer = Peer()
        with patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._send(peer, row, path))
            asyncio.run(Bluetooth()._receive(peer, remote, 'phone'))
        self.assertEqual(peer.received, data)
        self.assertTrue(peer.acked)
        self.assertEqual((self.downloads / 'photo.jpg').read_bytes(), data)
        self.assertTrue(all(r['state'] == 'complete' and r['done'] == len(data) for r in self.store.rows))

    def test_disconnect_discards_partial_and_never_acknowledges(self):
        class Peer:
            async def call(peer, op, **fields):
                if op == 'received': self.fail('Must not acknowledge an incomplete file')
                raise ConnectionError('Disconnected')
        with patch('handset.bluetooth.store', return_value=self.store), self.assertRaises(ConnectionError):
            asyncio.run(Bluetooth()._receive(Peer(), self.remote(b'123'), 'phone'))
        self.assertEqual(self.store.rows[-1]['state'], 'failed')
        self.assertFalse(list((self.store.root / 'staging').glob('*.part')))
        self.assertFalse(self.downloads.exists())


class RpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_finds_bound_service_when_ios_omits_its_name(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        service = '12345678-1234-1234-1234-123456789abc'
        scanner = MagicMock(find_device_by_filter=AsyncMock(return_value=None))
        with patch.dict('sys.modules', {'bleak': SimpleNamespace(BleakScanner=scanner, BleakClient=MagicMock())}):
            with self.assertRaisesRegex(ValueError, 'not found'):
                await Bluetooth()._session({'service': service, 'peerName': 'Pane-test', 'token': 'a'*64})
        predicate = scanner.find_device_by_filter.call_args.args[0]
        self.assertTrue(predicate(None, SimpleNamespace(local_name=None, service_uuids=[service.upper()])))
        self.assertFalse(predicate(None, SimpleNamespace(local_name='Pane-test', service_uuids=[])))

    async def test_fragmented_notifications_wrong_request_and_backpressure(self):
        class Client:
            mtu_size = 23
            writes = []
            async def write_gatt_char(client, characteristic, data, response):
                self.assertTrue(response)
                self.assertLessEqual(len(data), 20)
                client.writes.append(data)
                if data.endswith(b'\n'):
                    rpc.notified(None, b'{"request":999,"ok":false}\n{"requ')
                    rpc.notified(None, b'est":1,"ok":true}\n')
        client = Client(); rpc = Rpc(client)
        result = await rpc.call('hello', token='a'*64)
        self.assertTrue(result['ok'])
        self.assertGreater(len(client.writes), 1)
