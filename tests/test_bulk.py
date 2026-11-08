import asyncio
import hashlib
import socket
import ssl
import struct
import threading
import time
import unittest
from unittest.mock import patch

from handset.bulk import BulkReceiver, BulkUnavailable, BulkPaused, BulkCancelled, MAX_BLOCK


def exact(stream, count):
    data = bytearray()
    while len(data) < count:
        part = stream.recv(count - len(data))
        if not part:
            return None
        data.extend(part)
    return bytes(data)


class BulkTests(unittest.IsolatedAsyncioTestCase):
    def channel(self, data=b'hello', **options):
        receiver = BulkReceiver(len(data), hosts=['127.0.0.1'], bind_host='127.0.0.1', **options)
        self.addCleanup(receiver.close)
        endpoint = receiver.start()
        return receiver, endpoint

    def phone(self, endpoint, data, *, response=None, wrong_first=False):
        errors = []
        sockets = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        def connect(secret):
            stream = context.wrap_socket(socket.create_connection(('127.0.0.1', endpoint['port']), timeout=2), server_hostname='Pane')
            sockets.append(stream)
            self.assertEqual(hashlib.sha256(stream.getpeercert(binary_form=True)).hexdigest(), endpoint['fingerprint'])
            stream.sendall(secret)
            return stream
        def run():
            try:
                if wrong_first:
                    with connect(b'x' * 32) as rejected:
                        self.assertEqual(rejected.recv(1), b'')
                with connect(bytes.fromhex(endpoint['secret'])) as stream:
                    while header := exact(stream, 12):
                        offset, length = struct.unpack('!QI', header)
                        block = data[offset:offset + length]
                        if response is not None:
                            stream.sendall(response)
                            return
                        frame = struct.pack('!BI', 0, len(block)) + block
                        # Fragment both the response header and payload to
                        # exercise exact reads, rather than socket boundaries.
                        stream.sendall(frame[:2])
                        stream.sendall(frame[2:])
            except (ConnectionError, OSError):
                pass  # Closing the receiver terminates a waiting test peer.
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        def cleanup():
            for stream in sockets:
                try: stream.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                stream.close()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            if errors: raise errors[0]
        self.addCleanup(cleanup)
        return errors

    async def test_pinned_tls_ranges_and_maximum_binary_block(self):
        data = bytes(range(256)) * 2048
        receiver, endpoint = self.channel(data)
        self.phone(endpoint, data)
        await receiver.accept()
        self.assertEqual(await receiver.read(17, MAX_BLOCK), data[17:17 + MAX_BLOCK])
        self.assertEqual(await receiver.read(len(data) - 3, 3), data[-3:])
        receiver.close()
        self.assertIsNone(receiver._peer)
        with self.assertRaises(BulkUnavailable): await receiver.read(0, 1)

    async def test_wrong_secret_does_not_admit_peer_or_block_next_peer(self):
        receiver, endpoint = self.channel()
        self.phone(endpoint, b'hello', wrong_first=True)
        await receiver.accept()
        self.assertEqual(await receiver.read(0, 5), b'hello')

    async def test_eight_mib_roundtrip_with_checksum_and_host_timing(self):
        data = bytes(range(256)) * 32768
        receiver, endpoint = self.channel(data)
        self.phone(endpoint, data)
        await receiver.accept()
        digest = hashlib.sha256()
        started = time.perf_counter()
        for offset in range(0, len(data), MAX_BLOCK):
            digest.update(await receiver.read(offset, MAX_BLOCK))
        elapsed = time.perf_counter() - started
        self.assertEqual(digest.digest(), hashlib.sha256(data).digest())
        # Record an observation only. A loopback benchmark is not an iPhone
        # Wi-Fi result, and has no flaky timing acceptance threshold.
        print(f'TLS loopback: 8 MiB in {elapsed:.4f}s ({8 / elapsed:.2f} MiB/s); not a radio measurement')

    async def test_range_bounds_checked_before_socket_access(self):
        receiver, _ = self.channel()
        for offset, length in ((-1, 1), (0, 0), (0, MAX_BLOCK + 1), (4, 2), (True, 1), (0, True)):
            with self.assertRaises(ValueError): await receiver.read(offset, length)

    async def test_controls_never_carry_file_data(self):
        for state, exception in ((1, BulkPaused), (2, BulkCancelled), (3, BulkUnavailable), (4, BulkUnavailable)):
            with self.subTest(state=state):
                receiver, endpoint = self.channel()
                self.phone(endpoint, b'hello', response=struct.pack('!BI', state, 0))
                await receiver.accept()
                with self.assertRaises(exception): await receiver.read(0, 5)
                receiver.close()

    async def test_oversized_or_empty_reply_is_rejected_without_allocation(self):
        for state, length in ((0, MAX_BLOCK + 1), (0, 0), (1, 1)):
            receiver, endpoint = self.channel()
            self.phone(endpoint, b'hello', response=struct.pack('!BI', state, length))
            await receiver.accept()
            with self.assertRaises(BulkUnavailable): await receiver.read(0, 5)
            self.assertIsNone(receiver._peer)

    async def test_no_peer_deadline_and_listener_cleanup(self):
        receiver, _ = self.channel(connect_timeout=0.1)
        started = time.monotonic()
        with self.assertRaises(BulkUnavailable): await receiver.accept()
        self.assertLess(time.monotonic() - started, 1)
        receiver.close()
        self.assertIsNone(receiver._listener)

    async def test_cancelling_accept_closes_listener(self):
        receiver, _ = self.channel()
        task = asyncio.create_task(receiver.accept())
        await asyncio.sleep(0.03)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertIsNone(receiver._listener)

    def test_no_public_or_wildcard_advertisement(self):
        for hosts in ([], ['0.0.0.0'], ['8.8.8.8'], ['224.0.0.1'], ['198.18.0.1'], ['100.64.0.1']):
            with self.assertRaises((ValueError, BulkUnavailable)):
                BulkReceiver(1, hosts=hosts)

    def test_close_during_certificate_generation_cannot_publish_listener(self):
        receiver = BulkReceiver(1, hosts=['127.0.0.1'], bind_host='127.0.0.1')
        entered, release = threading.Event(), threading.Event()
        errors, sockets = [], []
        original_socket = socket.socket
        def certificate():
            entered.set()
            if not release.wait(3): raise AssertionError('Test failed to release certificate generation')
            return object(), '0' * 64
        def make_socket(*args, **kwargs):
            value = original_socket(*args, **kwargs)
            sockets.append(value)
            return value
        def start():
            try: receiver.start()
            except BaseException as error: errors.append(error)
        with patch('handset.bulk._tls_context', side_effect=certificate), patch('handset.bulk.socket.socket', side_effect=make_socket):
            thread = threading.Thread(target=start, daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                receiver.close()
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], BulkUnavailable)
        self.assertIsNone(receiver._listener)
        self.assertIsNone(receiver._context)
        self.assertTrue(all(stream.fileno() == -1 for stream in sockets))
