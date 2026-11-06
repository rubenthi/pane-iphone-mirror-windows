"""Encrypted BLE GATT file transfer to the USB-bound Pane companion."""
from __future__ import annotations

import asyncio
import base64
import json
import threading

from handset.setup import COMMAND_UUID, RESPONSE_UUID
from handset.state import DATA_DIR, read_json, write_json
from handset.transfers import store, digest_file

WIRE_CHUNK = 4096
MAX_FRAME = 65536


class Rpc:
    def __init__(self, client):
        self.client = client
        self.buffer = bytearray()
        self.pending = None
        self.sequence = 0

    def notified(self, sender, data):
        self.buffer.extend(data)
        if len(self.buffer) > MAX_FRAME:
            self.buffer.clear()
            if self.pending and not self.pending.done():
                self.pending.set_exception(ValueError('Bluetooth reply exceeded its limit.'))
            return
        while b'\n' in self.buffer:
            line, _, remaining = self.buffer.partition(b'\n')
            self.buffer = bytearray(remaining)
            try:
                reply = json.loads(line)
                if isinstance(reply, dict) and reply.get('request') == self.sequence and self.pending and not self.pending.done():
                    self.pending.set_result(reply)
            except (ValueError, UnicodeError):
                if self.pending and not self.pending.done():
                    self.pending.set_exception(ValueError('Invalid Bluetooth reply.'))

    async def call(self, op, **fields):
        self.sequence += 1
        self.pending = asyncio.get_running_loop().create_future()
        wire = (json.dumps({'request': self.sequence, 'op': op, **fields}, separators=(',', ':')) + '\n').encode()
        # ATT writes with response preserve ordering and backpressure, even at MTU 23.
        size = min(180, max(20, self.client.mtu_size - 3))
        try:
            async with asyncio.timeout(45):
                for offset in range(0, len(wire), size):
                    await self.client.write_gatt_char(COMMAND_UUID, wire[offset:offset + size], response=True)
                result = await self.pending
            if result.get('error'):
                raise ValueError(result['error'])
            return result
        finally:
            self.pending = None


class Bluetooth:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = {'phase': 'disconnected', 'note': 'Complete USB setup to bind your iPhone.'}
        self.worker = None
        self.loop = None
        self.task = None

    def status(self):
        with self.lock:
            return dict(self.state)

    def _set(self, **fields):
        with self.lock:
            self.state.update(fields)

    def connect(self):
        binding = read_json(DATA_DIR / 'binding.json', {})
        if not binding.get('token'):
            raise ValueError('Bind your iPhone over USB in setup first.')
        with self.lock:
            if self.worker and self.worker.is_alive():
                return dict(self.state)
            self.state.update(phase='connecting', error=None, note='Keep Pane open. Accept the Windows/iPhone Bluetooth pairing prompt if shown.')
            self.worker = threading.Thread(target=self._run, args=(binding,), daemon=True, name='pane-files')
            self.worker.start()
        return self.status()

    def disconnect(self):
        with self.lock:
            if self.loop and self.task and not self.task.done():
                self.loop.call_soon_threadsafe(self.task.cancel)
        return self.status()

    def _run(self, binding):
        try:
            asyncio.run(self._session(binding))
        except asyncio.CancelledError:
            self._set(phase='disconnected', note='Bluetooth disconnected.', error=None)
        except Exception as error:
            message = str(error) or type(error).__name__
            self._set(phase='error', error=message, note=message)

    async def _session(self, binding):
        from bleak import BleakClient, BleakScanner
        self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        # iOS can truncate/omit the local name in advertising. A per-binding
        # service UUID identifies the USB-bound app without name matching.
        service = binding['service'].lower()
        peer = await BleakScanner.find_device_by_filter(
            lambda device, ad: service in [s.lower() for s in ad.service_uuids],
            timeout=20, service_uuids=[service])
        if peer is None:
            raise ValueError('Bound iPhone not found. Open Pane, activate the USB link, allow Bluetooth, and keep it in the foreground.')
        async with BleakClient(peer, pair=True, timeout=120) as client:
            rpc = Rpc(client)
            await client.start_notify(RESPONSE_UUID, rpc.notified)
            result = await rpc.call('hello', token=binding['token'])
            if result.get('version') != 1:
                raise ValueError('The companion uses an unsupported protocol version.')
            binding['onboardingComplete'] = True
            write_json(DATA_DIR / 'binding.json', binding)
            self._set(phase='connected', note='Bluetooth connected. Keep Pane open during transfers.', error=None)
            while client.is_connected:
                outgoing = store().next_outgoing()
                if outgoing:
                    await self._send(rpc, *outgoing)
                listing = await rpc.call('list')
                files = listing.get('files', [])
                if not isinstance(files, list) or len(files) > 100:
                    raise ValueError('Invalid iPhone file list.')
                for remote in files:
                    if not isinstance(remote, dict):
                        raise ValueError('Invalid iPhone file metadata.')
                    await self._receive(rpc, remote, binding['peerName'])
                await asyncio.sleep(1)
            raise ConnectionError('Bluetooth disconnected. Reconnect to continue transferring files.')

    async def _send(self, rpc, row, path):
        identifier = row['id']
        try:
            await rpc.call('begin', id=identifier, name=row['name'], size=row['size'], sha256=await asyncio.to_thread(digest_file, path))
            offset = 0
            with path.open('rb') as stream:
                while chunk := stream.read(WIRE_CHUNK):
                    reply = await rpc.call('write', id=identifier, offset=offset, data=base64.b64encode(chunk).decode())
                    offset += len(chunk)
                    if reply.get('offset') != offset:
                        raise ValueError('The iPhone did not acknowledge the file chunk.')
                    store().update(identifier, done=offset)
            await rpc.call('finish', id=identifier)
            store().update(identifier, state='complete', done=offset)
        except BaseException as error:
            store().update(identifier, state='failed', error=str(error) or 'Transfer disconnected. Send the file again.')
            raise
        finally:
            path.unlink(missing_ok=True)

    async def _receive(self, rpc, remote, peer):
        incoming = store().incoming(remote, peer)
        if incoming is None:
            await rpc.call('received', id=remote['id'])
            return
        identifier, path = incoming
        try:
            offset = 0
            with path.open('xb') as stream:
                while offset < remote['size']:
                    result = await rpc.call('read', id=remote['id'], offset=offset, length=min(WIRE_CHUNK, remote['size'] - offset))
                    data = base64.b64decode(result.get('data', ''), validate=True)
                    if not data or len(data) > WIRE_CHUNK or offset + len(data) > remote['size']:
                        raise ValueError('Incomplete or oversized iPhone file chunk.')
                    stream.write(data)
                    offset += len(data)
                    store().update(identifier, done=offset)
            await asyncio.to_thread(store().deliver, identifier, path, remote['sha256'])
        except BaseException as error:
            store().update(identifier, state='failed', error=str(error) or 'Transfer disconnected. Reconnect to retry.')
            raise
        finally:
            path.unlink(missing_ok=True)
        # Completion is durable before acknowledging. A lost ACK cannot duplicate it.
        await rpc.call('received', id=remote['id'])


bluetooth = Bluetooth()
