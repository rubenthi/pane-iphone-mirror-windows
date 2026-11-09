"""Desktop-to-phone pinned TLS, wrong or missing ACKs, and fallback over legacy BLE."""
import asyncio
import base64
import hashlib
from pathlib import Path
import socket
import ssl
import struct
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

from handset.bluetooth import Bluetooth, Rpc
from handset.bulk import BulkSender, MAX_BLOCK
from handset.transfers import CHUNK, TransferStore


def exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.recv(size - len(data))
        if not part:
            raise EOFError()
        data.extend(part)
    return bytes(data)


class Phone:
    wifi_download = True
    controls = False
    chunk_size = 32768

    def __init__(self, scenario='complete'):
        self.scenario = scenario
        self.data = bytearray()
        self.ble_offsets = []
        self.tls_blocks = []
        self.fenced = False
        self.reserved = False
        self.completed = False
        self.threads = []
        self.errors = []
        self.on_first_block = None

    def run_tls(self, endpoint):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection(('127.0.0.1', endpoint['port']), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname='Pane') as stream:
                    pin = hashlib.sha256(stream.getpeercert(binary_form=True)).hexdigest()
                    assert pin == endpoint['fingerprint']
                    stream.sendall(bytes.fromhex(endpoint['secret']))
                    while True:
                        offset, length = struct.unpack('!QI', exact(stream, 12))
                        assert offset == len(self.data) and 0 < length <= MAX_BLOCK
                        data = exact(stream, length)
                        self.tls_blocks.append(length)
                        if self.scenario in ('pause', 'cancel'):
                            stream.sendall(struct.pack('!BQ', 1 if self.scenario == 'pause' else 2, offset))
                            return
                        if self.scenario == 'drop-before':
                            return
                        self.data.extend(data)
                        if self.on_first_block and len(self.tls_blocks) == 1:
                            self.on_first_block()
                        if self.scenario in ('drop-after', 'invalid-fence'):
                            return
                        ack = struct.pack('!BQ', 0, len(self.data))
                        stream.sendall(ack[:2])
                        stream.sendall(ack[2:])
        except (EOFError, ConnectionError):
            pass
        except BaseException as error:
            self.errors.append(error)

    async def call(self, op, **fields):
        if op == 'begin':
            if self.completed:
                assert self.digest == fields['sha256']
                return {'ok':True, 'completed':True}
            self.data.clear()
            self.digest = fields['sha256']
        if op == 'bulk-write':
            self.reserved = True
            if self.scenario == 'unsupported':
                raise ValueError('Unavailable')
            if self.scenario == 'lost-setup-ack':
                raise TimeoutError('Setup reply lost')
            if self.scenario == 'accept-timeout':
                return {'ok':True, 'offset':len(self.data)}
            worker = threading.Thread(target=self.run_tls, args=(fields['endpoint'],), daemon=True)
            self.threads.append(worker)
            worker.start()
            return {'ok':True, 'offset':len(self.data)}
        if op == 'bulk-write-stop':
            self.fenced = True
            self.reserved = False
            return {'offset':len(self.data) + (1 if self.scenario == 'invalid-fence' else 0)}
        if op == 'write':
            if self.reserved:
                raise ValueError('TLS writer still owns this transfer.')
            if self.scenario.startswith('drop-'):
                assert self.fenced
            assert fields['offset'] == len(self.data)
            self.ble_offsets.append(fields['offset'])
            self.data.extend(base64.b64decode(fields['data'], validate=True))
            return {'offset':len(self.data)}
        if op == 'finish':
            assert hashlib.sha256(self.data).hexdigest() == self.digest
            self.completed = True
            if self.scenario == 'lost-finish':
                raise ConnectionError('Completion ACK lost')
        return {'ok':True}

    def join(self):
        for worker in self.threads:
            worker.join(4)
            assert not worker.is_alive()
        if self.errors:
            raise self.errors[0]


class FastDownloadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = TransferStore(Path(tmp.name))
        self.data = bytes(range(251)) * 3000
        self.ident = self.store.begin('data.bin', len(self.data))['id']
        for offset in range(0, len(self.data), CHUNK):
            self.store.append(self.ident, offset, base64.b64encode(self.data[offset:offset+CHUNK]))
        self.path = self.store.finish(self.ident, 'file')['path']
        self.enterContext(patch('handset.bluetooth.store', return_value=self.store))
        self.enterContext(patch('handset.bulk.BulkSender', side_effect=lambda size:BulkSender(
            size, hosts=['127.0.0.1'], bind_host='127.0.0.1', connect_timeout=3, io_timeout=3)))

    def send(self, peer):
        try:
            asyncio.run(Bluetooth()._send(peer, *self.store.next_outgoing()))
        finally:
            peer.join()

    def test_full_pinned_transfer_with_fragmented_ack(self):
        peer = Phone()
        self.send(peer)
        self.assertEqual(peer.data, self.data)
        self.assertEqual(peer.ble_offsets, [])
        self.assertEqual(peer.tls_blocks, [MAX_BLOCK, MAX_BLOCK, len(self.data)-2*MAX_BLOCK])
        self.assertEqual(self.store.row(self.ident)['transport'], 'wifi')
        self.assertFalse(self.path.exists())

    def test_ack_loss_after_append_reconciles_before_ble(self):
        peer = Phone('drop-after')
        self.send(peer)
        self.assertTrue(peer.fenced)
        self.assertEqual(peer.ble_offsets[0], MAX_BLOCK)
        self.assertEqual(peer.data, self.data)
        self.assertEqual(self.store.row(self.ident)['transport'], 'bluetooth')

    def test_disconnect_before_append_retries_same_range(self):
        peer = Phone('drop-before')
        self.send(peer)
        self.assertTrue(peer.fenced)
        self.assertEqual(peer.ble_offsets[0], 0)
        self.assertEqual(peer.data, self.data)

    def test_invalid_reconciled_offset_aborts(self):
        peer = Phone('invalid-fence')
        with self.assertRaisesRegex(ValueError, 'confirm'):
            self.send(peer)
        self.assertEqual(self.store.row(self.ident)['state'], 'failed')
        self.assertFalse(peer.completed)
        self.assertEqual(peer.ble_offsets, [])

    def test_phone_pause_resume(self):
        peer = Phone('pause')
        self.send(peer)
        self.assertTrue(self.path.exists())
        self.assertEqual(self.store.row(self.ident)['state'], 'paused')
        self.store.control(self.ident, 'resume')
        peer.scenario = 'complete'
        self.send(peer)
        self.assertEqual(peer.data, self.data)

    def test_phone_cancel(self):
        self.send(Phone('cancel'))
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.row(self.ident)['state'], 'cancelled')

    def test_desktop_pause_and_resume_after_an_acknowledged_wifi_block(self):
        peer = Phone()
        peer.on_first_block = lambda: self.store.control(self.ident, 'pause')
        self.send(peer)
        row = self.store.row(self.ident)
        self.assertEqual((row['state'], row['done']), ('paused', MAX_BLOCK))
        self.store.control(self.ident, 'resume')
        self.send(peer)
        self.assertEqual(peer.data, self.data)
        self.assertTrue(peer.completed)

    def test_desktop_cancel_does_not_publish_partial_wifi_transfer(self):
        peer = Phone()
        peer.on_first_block = lambda: self.store.cancel(self.ident)
        self.send(peer)
        self.assertEqual(self.store.row(self.ident)['state'], 'cancelled')
        self.assertFalse(peer.completed)
        self.assertFalse(self.path.exists())

    def test_desktop_pause_while_waiting_for_wifi(self):
        owner = self
        class WaitingPhone(Phone):
            async def call(self, op, **fields):
                if op == 'bulk-write':
                    owner.store.control(owner.ident, 'pause')
                    return {'ok': True, 'offset': 0}
                return await super().call(op, **fields)
        peer = WaitingPhone()
        self.send(peer)
        self.assertEqual(self.store.row(self.ident)['state'], 'paused')
        self.assertEqual(peer.ble_offsets, [])
        self.assertTrue(self.path.exists())

    def test_sender_rejects_invalid_range_before_socket_io(self):
        channel = BulkSender(4, hosts=['127.0.0.1'])
        for offset, block in ((-1, b'x'), (0, b''), (1, b'1234'), (True, b'x'), (0, b'x' * (MAX_BLOCK + 1))):
            with self.subTest(offset=offset, length=len(block)), self.assertRaises(ValueError):
                asyncio.run(channel.write(offset, block))

    def test_unavailable_wifi_falls_back_before_sending(self):
        peer = Phone('unsupported')
        self.send(peer)
        self.assertEqual(peer.data, self.data)
        self.assertEqual(peer.ble_offsets[0], 0)
        self.assertTrue(peer.fenced)

    def test_accept_timeout_releases_reserved_phone_writer_before_ble(self):
        peer = Phone('accept-timeout')
        with patch.object(BulkSender, 'accept', AsyncMock(side_effect=TimeoutError('LAN access denied'))):
            self.send(peer)
        self.assertTrue(peer.fenced)
        self.assertEqual(peer.ble_offsets[0], 0)
        self.assertEqual(peer.data, self.data)

    def test_lost_setup_ack_releases_reserved_phone_writer_before_ble(self):
        peer = Phone('lost-setup-ack')
        self.send(peer)
        self.assertTrue(peer.fenced)
        self.assertEqual(peer.ble_offsets[0], 0)
        self.assertEqual(peer.data, self.data)

    def test_local_start_failure_does_not_send_stop_before_setup(self):
        peer = Phone()
        with patch.object(BulkSender, 'start', side_effect=OSError('No LAN address')):
            self.send(peer)
        self.assertFalse(peer.fenced)
        self.assertEqual(peer.data, self.data)

    def test_resume_after_wifi_loss_uses_released_ble_writer(self):
        peer = Phone()
        peer.on_first_block = lambda: self.store.control(self.ident, 'pause')
        self.send(peer)
        self.assertFalse(peer.reserved)
        self.store.control(self.ident, 'resume')
        with patch.object(BulkSender, 'start', side_effect=OSError('No LAN address')):
            self.send(peer)
        self.assertEqual(peer.ble_offsets[0], MAX_BLOCK)
        self.assertEqual(peer.data, self.data)

    def test_legacy_peer_never_gets_fast_download_request(self):
        peer = Phone()
        peer.wifi_download = False
        self.send(peer)
        self.assertEqual(peer.tls_blocks, [])
        self.assertEqual(peer.data, self.data)
        rpc = Rpc(type('Client', (), {'mtu_size':185})())
        rpc.negotiate(['wifi-upload-v1'])
        self.assertTrue(rpc.wifi_upload)
        self.assertFalse(rpc.wifi_download)

    def test_lost_final_ack_reconnects_with_original_id_and_no_second_publication(self):
        peer = Phone('lost-finish')
        with self.assertRaises(ConnectionError):
            self.send(peer)
        self.assertTrue(self.path.exists())
        self.assertEqual(self.store.row(self.ident)['state'], 'queued')
        blocks = list(peer.tls_blocks)
        self.send(peer)
        self.assertEqual(peer.tls_blocks, blocks)
        self.assertEqual(self.store.row(self.ident)['state'], 'complete')
        self.assertFalse(self.path.exists())
