import asyncio
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        for name in ('CON .txt', 'LPT².log', 'COM³.dat', 'CONOUT$'):
            self.assertEqual(safe_name(name), '_' + name)

    def test_driver_payloads_stay_out_of_transfer_history(self):
        private = 'sensitive bytes from a GATT packet'
        class Peer:
            async def call(self, op, **fields):
                raise RuntimeError(private)
        self.stage(b'example')
        with patch('handset.bluetooth.store', return_value=self.store):
            with self.assertRaises(RuntimeError):
                asyncio.run(Bluetooth()._send(Peer(), *self.store.next_outgoing()))
            with self.assertRaises(RuntimeError):
                asyncio.run(Bluetooth()._receive(Peer(), self.remote(b'example'), 'phone'))
        self.assertNotIn(private, json.dumps(self.store.status()))
        history = self.store.root / 'transfers.json'
        self.assertNotIn(private, history.read_text())
        rows = json.loads(history.read_text())
        rows[0]['error'] = private
        history.write_text(json.dumps(rows))
        reopened = TransferStore(self.store.root, self.downloads)
        self.assertNotIn(private, json.dumps(reopened.status()))
        self.assertNotIn(private, history.read_text())
        self.assertEqual(len(reopened.rows), 2)

    def test_stale_remote_controls_cannot_resurrect_completed_transfer(self):
        item = self.stage(b'finished')
        self.store.update(item['id'], state='complete')
        class Peer:
            controls = True
            async def call(self, op, **fields):
                return {'transfers':[{'id':item['id'],'state':'paused'}]}
        with patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._sync_controls(Peer()))
        self.assertEqual(self.store.row(item['id'])['state'], 'complete')

    def test_repeated_resume_preserves_active_phase(self):
        item = self.stage(b'example')
        row, _ = self.store.next_outgoing()
        self.store.control(item['id'], 'pause')
        self.store.control(item['id'], 'resume')
        self.store.control(item['id'], 'resume')
        self.assertEqual(self.store.row(item['id'])['state'], row['state'])

    def test_destination_staging_collision_preserves_other_file(self):
        self.downloads.mkdir()
        remote = self.remote(b'good')
        identifier, part = self.store.incoming(remote, 'phone')
        part.write_bytes(b'good')
        unrelated = self.downloads / ('.pane-' + identifier + '.part')
        unrelated.write_bytes(b'existing')
        # Force the fallback path for a Downloads directory on another drive.
        import errno
        with patch.object(self.store, '_publish', side_effect=OSError(errno.EXDEV, 'cross-device')), self.assertRaises(FileExistsError):
            self.store.deliver(identifier, part, remote['sha256'])
        self.assertEqual(unrelated.read_bytes(), b'existing')

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

    def test_pause_yields_queue_and_resume_keeps_acknowledged_offset(self):
        first = self.stage(b'a' * 12000)
        second = self.stage(b'next')
        owner = self
        class Peer:
            chunk_size = 4096
            data = {}
            paused = False
            async def call(peer, op, **fields):
                identifier = fields.get('id')
                if op == 'begin': peer.data[identifier] = bytearray()
                if op == 'write':
                    owner.assertEqual(fields['offset'], len(peer.data[identifier]))
                    peer.data[identifier].extend(base64.b64decode(fields['data']))
                    if identifier == first['id'] and not peer.paused:
                        peer.paused = True
                        owner.store.control(identifier, 'pause')
                    return {'offset': len(peer.data[identifier])}
                return {'ok': True}
        peer = Peer()
        with patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._send(peer, *self.store.next_outgoing()))
            self.assertEqual(self.store.row(first['id'])['state'], 'paused')
            self.assertEqual(self.store.row(first['id'])['done'], 4096)
            self.assertTrue(first['path'].exists())
            row, path = self.store.next_outgoing()
            self.assertEqual(row['id'], second['id'])
            asyncio.run(Bluetooth()._send(peer, row, path))
            self.store.control(first['id'], 'resume')
            asyncio.run(Bluetooth()._send(peer, *self.store.next_outgoing()))
        self.assertEqual(peer.data[first['id']], b'a' * 12000)
        self.assertEqual(self.store.row(first['id'])['state'], 'complete')
        self.assertFalse(first['path'].exists())

    def test_pause_receive_then_resume_or_cancel_never_publishes_partial(self):
        data = b'a' * 9000
        remote = self.remote(data)
        owner = self
        class Peer:
            pause = True
            acked = False
            offsets = []
            async def call(peer, op, **fields):
                if op == 'read':
                    peer.offsets.append(fields['offset'])
                    if peer.pause:
                        peer.pause = False
                        owner.store.control(owner.store.rows[-1]['id'], 'pause')
                    return {'data': base64.b64encode(data[fields['offset']:fields['offset'] + fields['length']]).decode()}
                if op == 'received': peer.acked = True
                return {'ok': True}
        peer = Peer()
        with patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._receive(peer, remote, 'phone'))
            row = self.store.rows[-1]
            self.assertEqual(row['state'], 'paused')
            self.assertEqual(row['done'], 4096)
            self.assertFalse(self.downloads.exists())
            self.store.control(row['id'], 'resume')
            asyncio.run(Bluetooth()._receive(peer, remote, 'phone'))
            self.assertEqual(peer.offsets, [0, 4096, 8192])
            self.assertTrue(peer.acked)
            self.assertEqual((self.downloads / 'photo.jpg').read_bytes(), data)
            # A new transfer cancelled while a read is in flight gets no ACK.
            remote = {**remote, 'id': '2' * 32}
            class CancelPeer(Peer):
                acked = False
                async def call(peer, op, **fields):
                    if op == 'read': owner.store.cancel(owner.store.rows[-1]['id'])
                    return await super().call(op, **fields)
            cancelled = CancelPeer(); cancelled.pause = False
            asyncio.run(Bluetooth()._receive(cancelled, remote, 'phone'))
            self.assertFalse(cancelled.acked)
            self.assertEqual(self.store.rows[-1]['state'], 'cancelled')
            self.assertFalse(list((self.store.root / 'staging').glob('*.part')))
            self.assertEqual(len(list(self.downloads.iterdir())), 1)

    def test_remote_controls_cancel_queued_file_and_pause_does_not_drop_budget(self):
        item = self.stage(b'cancel')
        class Peer:
            controls = True
            async def call(peer, op, **fields):
                self.assertEqual(op, 'controls')
                return {'transfers': [{'id': item['id'], 'state': 'cancelled'}]}
        with patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._sync_controls(Peer()))
        self.assertEqual(self.store.row(item['id'])['state'], 'cancelled')
        self.assertFalse(item['path'].exists())
        for _ in range(8):
            item = self.stage(b'x')
            self.store.control(item['id'], 'pause')
        with self.assertRaises(ValueError): self.store.begin('overflow', 1)

    def test_legacy_pause_reserves_single_phone_inbound_slot(self):
        first = self.stage(b'first')
        second = self.stage(b'second')
        row, _ = self.store.next_outgoing(preserve_legacy=True)
        self.store.update(row['id'], started=True, done=2)
        self.store.control(row['id'], 'pause')
        self.assertIsNone(self.store.next_outgoing(preserve_legacy=True))
        self.store.control(row['id'], 'resume')
        resumed, _ = self.store.next_outgoing(preserve_legacy=True)
        self.assertEqual(resumed['id'], first['id'])
        self.assertEqual(resumed['done'], 2)
        self.store.cancel(first['id'])
        self.assertEqual(self.store.next_outgoing(preserve_legacy=True)[0]['id'], second['id'])

    def test_acknowledged_cancelled_history_is_not_retransmitted(self):
        self.store.rows = [dict(id=f'{index:032x}', name='x'*180, size=1, done=0,
                               direction='to-phone', state='cancelled') for index in range(220)]
        owner = self
        class Peer:
            controls = True
            async def call(peer, op, **fields):
                owner.assertEqual(fields['transfers'], [])
                return {'transfers': []}
        with patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._sync_controls(Peer()))

    def test_reconnect_restarts_phone_partial_without_losing_paused_source(self):
        item = self.stage(b'source')
        row, _ = self.store.next_outgoing()
        self.store.update(row['id'], started=True, done=3)
        self.store.control(row['id'], 'pause')
        with patch('handset.bluetooth.store', return_value=self.store):
            Bluetooth()._reset_interrupted_outgoing()
        row = self.store.row(row['id'])
        self.assertEqual((row['state'], row['done'], row['started']), ('paused', 0, False))
        self.assertTrue(item['path'].exists())

    def test_cancelled_before_delivery_does_not_publish_or_report_success(self):
        metadata = self.remote(b'complete bytes')
        identifier, part = self.store.incoming(metadata, 'phone')
        part.write_bytes(b'complete bytes')
        self.store.cancel(identifier)
        self.assertFalse(self.store.deliver(identifier, part, metadata['sha256']))
        self.assertFalse(self.downloads.exists())
        with self.assertRaises(ValueError): self.store.cancel('../../outside')

    def test_receive_batches_avoid_per_chunk_control_roundtrips(self):
        data = bytes(range(256)) * 4096
        owner = self
        class Peer:
            controls = True
            receive_chunk_size = 32768
            reads = []
            controls_count = 0
            acked = False
            async def call(peer, op, **fields):
                if op == 'controls':
                    peer.controls_count += 1
                    for row in fields['transfers']:
                        if row['direction'] == 'from-phone':
                            owner.assertNotIn('name', row)
                            owner.assertNotIn('size', row)
                    return {'transfers': []}
                if op == 'read':
                    peer.reads.append(fields['length'])
                    return {'data': base64.b64encode(data[fields['offset']:fields['offset'] + fields['length']]).decode()}
                if op == 'received': peer.acked = True
                return {'ok': True}
        peer = Peer()
        with patch('handset.bluetooth.store', return_value=self.store), patch('handset.bluetooth.time.monotonic', return_value=100):
            asyncio.run(Bluetooth()._receive(peer, self.remote(data), 'phone'))
        self.assertEqual(peer.reads, [32768] * 32)
        self.assertLessEqual(peer.controls_count, 2)
        self.assertTrue(peer.acked)
        self.assertEqual((self.downloads / 'photo.jpg').read_bytes(), data)

    def test_control_throttle_expires_and_local_actions_bypass_it(self):
        item = self.stage(b'source')
        class Peer:
            controls = True
            calls = []
            async def call(peer, op, **fields):
                peer.calls.append(fields['transfers'])
                return {'transfers': []}
        peer = Peer()
        async def exercise():
            bluetooth = Bluetooth()
            with patch('handset.bluetooth.time.monotonic', return_value=100):
                await bluetooth._sync_controls(peer, force=False)
                await bluetooth._sync_controls(peer, force=False)
                self.assertEqual(len(peer.calls), 1)
                self.store.control(item['id'], 'pause')
                await bluetooth._sync_controls(peer, force=False)
                self.assertEqual(len(peer.calls), 2)
                self.assertEqual(peer.calls[-1][0]['control'], 'paused')
                await bluetooth._sync_controls(peer, force=False)
                before = len(peer.calls)
            with patch('handset.bluetooth.time.monotonic', return_value=101):
                await bluetooth._sync_controls(peer, force=False)
                self.assertEqual(len(peer.calls), before + 1)
                await bluetooth._sync_controls(peer, force=True)
                self.assertEqual(len(peer.calls), before + 2)
        with patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(exercise())

    def test_new_queue_metadata_bypasses_control_throttle(self):
        first = self.stage(b'first')
        class Peer:
            controls = True
            calls = []
            async def call(peer, op, **fields):
                peer.calls.append(fields['transfers'])
                return {'transfers': []}
        peer = Peer()
        async def exercise():
            bluetooth = Bluetooth()
            await bluetooth._sync_controls(peer, force=False)
            second = self.stage(b'second')
            await bluetooth._sync_controls(peer, force=False)
            self.assertEqual(len(peer.calls), 2)
            self.assertEqual({row['id'] for row in peer.calls[-1]}, {first['id'], second['id']})
            self.assertTrue(all('name' in row and 'size' in row for row in peer.calls[-1]))
        with patch('handset.bluetooth.store', return_value=self.store), patch('handset.bluetooth.time.monotonic', return_value=100):
            asyncio.run(exercise())

    def test_final_forced_remote_cancel_prevents_publication(self):
        data = b'private complete data'
        remote = self.remote(data)
        class Peer:
            controls = True
            read_finished = False
            controls_count = 0
            async def call(peer, op, **fields):
                if op == 'controls':
                    peer.controls_count += 1
                    return {'transfers': [{'id': remote['id'], 'state': 'cancelled'}] if peer.read_finished else []}
                if op == 'read':
                    peer.read_finished = True
                    return {'data': base64.b64encode(data).decode()}
                if op == 'received':
                    raise AssertionError('Cancelled file must not be acknowledged')
                return {'ok': True}
        peer = Peer()
        with patch('handset.bluetooth.store', return_value=self.store), patch('handset.bluetooth.time.monotonic', return_value=100):
            asyncio.run(Bluetooth()._receive(peer, remote, 'phone'))
        self.assertEqual(peer.controls_count, 2)
        self.assertEqual(self.store.rows[-1]['state'], 'cancelled')
        self.assertFalse(self.downloads.exists())
        self.assertFalse(list((self.store.root / 'staging').glob('*.part')))

    def bulk_peer(self, data):
        class Peer:
            wifi_upload = True
            receive_chunk_size = 32768
            ble_offsets = []
            acked = False
            async def call(peer, op, **fields):
                if op == 'read':
                    peer.ble_offsets.append(fields['offset'])
                    return {'data': base64.b64encode(data[fields['offset']:fields['offset'] + fields['length']]).decode()}
                if op == 'received': peer.acked = True
                return {'ok': True}
        return Peer()

    def test_wifi_receive_delivers_verified_file_without_ble_reads(self):
        data = bytes(range(256)) * 3072
        peer = self.bulk_peer(data)
        receiver = MagicMock()
        receiver.accept = AsyncMock()
        receiver.read = AsyncMock(side_effect=[data[i:i + 262144] for i in range(0, len(data), 262144)])
        with patch('handset.bulk.BulkReceiver', return_value=receiver) as factory, patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._receive(peer, self.remote(data), 'phone'))
        factory.assert_called_once_with(len(data))
        receiver.accept.assert_awaited_once()
        self.assertEqual(receiver.read.await_count, 3)
        receiver.close.assert_called_once()
        self.assertEqual(peer.ble_offsets, [])
        self.assertTrue(peer.acked)
        self.assertEqual(self.store.rows[-1]['transport'], 'wifi')
        self.assertEqual((self.downloads / 'photo.jpg').read_bytes(), data)

    def test_wifi_connection_failure_falls_back_without_losing_bytes(self):
        data = b'fallback' * 11000
        for stage in ('start', 'accept'):
            with self.subTest(stage=stage):
                peer = self.bulk_peer(data)
                receiver = MagicMock()
                receiver.accept = AsyncMock(side_effect=OSError('unavailable') if stage == 'accept' else None)
                if stage == 'start': receiver.start.side_effect = OSError('unavailable')
                remote = {**self.remote(data), 'id': ('3' if stage == 'start' else '4') * 32, 'name': stage + '.dat'}
                with patch('handset.bulk.BulkReceiver', return_value=receiver), patch('handset.bluetooth.store', return_value=self.store):
                    asyncio.run(Bluetooth()._receive(peer, remote, 'phone'))
                receiver.close.assert_called_once()
                self.assertEqual(peer.ble_offsets[0], 0)
                self.assertTrue(peer.acked)
                self.assertEqual((self.downloads / remote['name']).read_bytes(), data)

    def test_wifi_partial_failure_resumes_ble_from_written_offset(self):
        data = bytes(range(256)) * 2400
        peer = self.bulk_peer(data)
        receiver = MagicMock()
        receiver.accept = AsyncMock()
        receiver.read = AsyncMock(side_effect=[data[:262144], OSError('link interrupted')])
        with patch('handset.bulk.BulkReceiver', return_value=receiver), patch('handset.bluetooth.store', return_value=self.store):
            asyncio.run(Bluetooth()._receive(peer, self.remote(data), 'phone'))
        self.assertEqual(peer.ble_offsets[0], 262144)
        receiver.close.assert_called_once()
        self.assertTrue(peer.acked)
        self.assertEqual(self.store.rows[-1]['transport'], 'bluetooth')
        self.assertEqual((self.downloads / 'photo.jpg').read_bytes(), data)

    def test_wifi_pause_retains_partial_and_cancel_removes_it_without_publish(self):
        from handset.bulk import BulkPaused, BulkCancelled
        data = b'x' * 524288
        for event, expected in ((BulkPaused, 'paused'), (BulkCancelled, 'cancelled')):
            with self.subTest(event=expected):
                peer = self.bulk_peer(data)
                receiver = MagicMock()
                receiver.accept = AsyncMock()
                receiver.read = AsyncMock(side_effect=[data[:262144], event()])
                remote = {**self.remote(data), 'id': ('5' if expected == 'paused' else '6') * 32}
                with patch('handset.bulk.BulkReceiver', return_value=receiver), patch('handset.bluetooth.store', return_value=self.store):
                    asyncio.run(Bluetooth()._receive(peer, remote, 'phone'))
                row = next(row for row in self.store.rows if row.get('remoteId') == remote['id'])
                receiver.close.assert_called_once()
                self.assertEqual(row['state'], expected)
                self.assertEqual(row['done'], 262144)
                self.assertFalse(peer.acked)
                self.assertEqual(peer.ble_offsets, [])
                self.assertFalse(self.downloads.exists())
                part = self.store.root / 'staging' / (row['id'] + '.part')
                self.assertEqual(part.exists(), expected == 'paused')
                if part.exists(): self.assertEqual(part.read_bytes(), data[:262144])


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

    async def test_negotiated_mtu_uses_more_than_legacy_180_byte_cap(self):
        class Client:
            mtu_size = 247
            writes = []
            async def write_gatt_char(client, characteristic, data, response):
                self.assertTrue(response)
                self.assertLessEqual(len(data), 244)
                client.writes.append(data)
                if data.endswith(b'\n'): rpc.notified(None, b'{"request":1,"ok":true}\n')
        client = Client(); rpc = Rpc(client)
        await rpc.call('begin', name='x' * 800)
        self.assertEqual(len(client.writes[0]), 244)

    async def test_fast_batch_is_bounded_by_negotiated_mtu_and_capability(self):
        from types import SimpleNamespace
        for mtu, expected in ((23, 4096), (67, 4096), (185, 16384), (247, 32768)):
            rpc = Rpc(SimpleNamespace(mtu_size=mtu))
            rpc.negotiate(['transfer-control-v1', 'chunk-32768'])
            self.assertEqual(rpc.chunk_size, expected)
            self.assertEqual(rpc.receive_chunk_size, 32768)
            self.assertTrue(rpc.controls)
            rpc.negotiate([])
            self.assertEqual(rpc.chunk_size, 4096)
            self.assertEqual(rpc.receive_chunk_size, 4096)
            self.assertFalse(rpc.controls)
