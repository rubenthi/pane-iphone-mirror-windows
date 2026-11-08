"""Encrypted BLE GATT file transfer to the USB-bound Pane companion."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import threading

from handset.setup import COMMAND_UUID, RESPONSE_UUID
from handset.state import DATA_DIR, read_json, write_json
from handset.transfers import store, digest_file

WIRE_CHUNK = 4096
MAX_FRAME = 65536
FAST_CHUNK = 32768


class TransferCancelled(Exception):
    pass


class TransferPaused(Exception):
    pass


class Rpc:
    def __init__(self, client):
        self.client = client
        self.buffer = bytearray()
        self.pending = None
        self.sequence = 0
        self.controls = False
        self.chunk_size = WIRE_CHUNK

    def negotiate(self, capabilities):
        if not isinstance(capabilities, list):
            raise ValueError('Invalid iPhone capabilities.')
        self.controls = 'transfer-control-v1' in capabilities
        payload = max(20, self.client.mtu_size - 3)
        # Avoid turning a low-MTU legacy connection into thousands of response
        # writes per request. The same 45-second bound still applies per RPC.
        batch = WIRE_CHUNK if payload <= 64 else 16384 if payload <= 185 else FAST_CHUNK
        self.chunk_size = batch if 'chunk-32768' in capabilities else WIRE_CHUNK

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
        if len(wire) > MAX_FRAME:
            self.pending = None
            raise ValueError('Bluetooth request exceeded its limit.')
        # ATT writes with response preserve ordering and backpressure, even at MTU 23.
        # Use the negotiated ATT payload, capped by the GATT 512-byte value
        # limit. Response writes and one in-flight RPC retain backpressure.
        size = min(512, max(20, self.client.mtu_size - 3))
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
        self._auto_stop = threading.Event()
        self._cancel_session = threading.Event()
        self._auto_paused = False
        self._auto_worker = None

    def start_auto(self):
        with self.lock:
            if self._auto_worker and self._auto_worker.is_alive():
                return
            self._auto_stop.clear()
            self._auto_worker = threading.Thread(target=self._auto_loop, daemon=True, name='pane-bluetooth-reconnect')
            self._auto_worker.start()

    def _auto_tick(self):
        binding = read_json(DATA_DIR / 'binding.json', {})
        if not binding.get('token') or not binding.get('service') or binding.get('onboardingComplete', True) is False:
            return
        self.connect(automatic=True)

    def _auto_loop(self):
        delay = 1
        while not self._auto_stop.wait(delay):
            try:
                self._auto_tick()
            except (ValueError, OSError):
                pass  # A binding may be changing during setup; retry without a popup.
            delay = min(30, max(5, delay * 2)) if self.status()['phase'] == 'error' else 5

    def stop_auto(self):
        self._auto_stop.set()
        self.disconnect(manual=False)
        # The launcher exits the process after this returns. Allow WinRT's
        # async context manager to release the GATT subscription first.
        for worker, timeout in ((self._auto_worker, 1), (self.worker, 5)):
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=timeout)

    def status(self):
        with self.lock:
            return dict(self.state)

    def _set(self, **fields):
        with self.lock:
            self.state.update(fields)

    def connect(self, *, automatic=False):
        binding = read_json(DATA_DIR / 'binding.json', {})
        if not binding.get('token'):
            raise ValueError('Bind your iPhone over USB in setup first.')
        with self.lock:
            if automatic and (self._auto_paused or self._auto_stop.is_set()):
                return dict(self.state)
            if not automatic:
                self._auto_paused = False
            if self.worker and self.worker.is_alive():
                return dict(self.state)
            self._cancel_session.clear()
            self.state.update(phase='connecting', error=None, note='Keep Pane open. Accept the Windows/iPhone Bluetooth pairing prompt if shown.')
            self.worker = threading.Thread(target=self._run, args=(binding,), daemon=True, name='pane-files')
            self.worker.start()
        return self.status()

    def disconnect(self, *, manual=True):
        with self.lock:
            if manual:
                self._auto_paused = True
            self._cancel_session.set()
            if self.loop and not self.loop.is_closed() and self.task and not self.task.done():
                self.loop.call_soon_threadsafe(self.task.cancel)
        return self.status()

    def _run(self, binding):
        try:
            asyncio.run(self._session(binding))
        except asyncio.CancelledError:
            self._set(phase='disconnected', note='Bluetooth disconnected.', error=None)
        except Exception as error:
            # WinRT may include the entire GATT write (including file bytes)
            # in its exception. Keep only the fixed protocol code for diagnosis.
            protocol = re.search(r'Protocol Error (0x[0-9a-fA-F]{2})', str(error))
            message = 'Bluetooth disconnected. Open Pane on your iPhone.'
            self._set(phase='error', error=message, note=message,
                      errorCode=protocol.group(1) if protocol else type(error).__name__)
        finally:
            self._reset_interrupted_outgoing()
            with self.lock:
                self.loop = self.task = None

    def _reset_interrupted_outgoing(self):
        # CoreBluetooth discards private inbound handles on disconnect. Retain
        # queued source files, but restart any suspended send from zero next link.
        with store().lock:
            for row in store().rows:
                if row['direction'] == 'to-phone' and row.get('started') and row['state'] in {'sending', 'paused'}:
                    row.update(started=False, done=0)
                    if row['state'] != 'paused':
                        row['state'] = 'queued'
            store()._save()

    async def _session(self, binding):
        from bleak import BleakClient, BleakScanner
        self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        if self._cancel_session.is_set():
            raise asyncio.CancelledError()
        # iOS can truncate/omit the local name in advertising. A per-binding
        # service UUID identifies the USB-bound app without name matching.
        service = binding['service'].lower()
        peer = await BleakScanner.find_device_by_filter(
            lambda device, ad: service in [s.lower() for s in ad.service_uuids],
            timeout=20, service_uuids=[service])
        if peer is None:
            raise ValueError('Bound iPhone not found. Open Pane, activate the USB link, allow Bluetooth, and keep it in the foreground.')
        # A reinstalled companion can recreate GATT handles. Discover only the
        # bound service afresh instead of reusing Windows' previous handle map.
        async with BleakClient(peer, pair=True, timeout=120, services=[service],
                               winrt={'use_cached_services': False}) as client:
            rpc = Rpc(client)
            await client.start_notify(RESPONSE_UUID, rpc.notified)
            result = await rpc.call('hello', token=binding['token'], capabilities=['transfer-control-v1', 'chunk-32768'])
            if result.get('version') != 1:
                raise ValueError('The companion uses an unsupported protocol version.')
            rpc.negotiate(result.get('capabilities', []))
            binding['onboardingComplete'] = True
            write_json(DATA_DIR / 'binding.json', binding)
            self._set(phase='connected', note='Bluetooth connected. Keep Pane open during transfers.', error=None)
            while client.is_connected:
                await self._sync_controls(rpc)
                outgoing = store().next_outgoing(preserve_legacy=not rpc.controls)
                if outgoing:
                    await self._send(rpc, *outgoing)
                listing = await rpc.call('list')
                files = listing.get('files', [])
                if not isinstance(files, list) or len(files) > 8:
                    raise ValueError('Invalid iPhone file list.')
                for remote in files:
                    if not isinstance(remote, dict):
                        raise ValueError('Invalid iPhone file metadata.')
                    store().incoming(remote, binding['peerName'])
                # Register the whole queue before starting a file so either end
                # can control files waiting behind the active transfer.
                for remote in files:
                    await self._receive(rpc, remote, binding['peerName'])
                await asyncio.sleep(1)
            raise ConnectionError('Bluetooth disconnected. Reconnect to continue transferring files.')

    async def _sync_controls(self, rpc):
        if not getattr(rpc, 'controls', False):
            return
        rows = store().status()['transfers']
        payload = []
        for row in rows:
            if row['state'] in {'complete', 'failed'} or (row['state'] == 'cancelled' and not row.get('control')):
                continue
            keys = ('id', 'direction', 'state', 'control', 'remoteId') if row['state'] == 'cancelled' else ('id', 'name', 'size', 'direction', 'state', 'control', 'remoteId')
            payload.append({key: row[key] for key in keys if key in row})
        reply = await rpc.call('controls', transfers=payload)
        states = reply.get('transfers', [])
        if not isinstance(states, list) or len(states) > 256:
            raise ValueError('Invalid iPhone transfer controls.')
        for sent in payload:
            with store().lock:
                row = next((r for r in store().rows if r['id'] == sent['id']), None)
                if row and row.get('control') == sent.get('control'):
                    row.pop('control', None)
        for remote in states:
            if not isinstance(remote, dict) or remote.get('state') not in {'queued', 'sending', 'receiving', 'paused', 'cancelled'}:
                raise ValueError('Invalid iPhone transfer state.')
            for row in rows:
                if remote.get('id') == row.get('remoteId', row['id']):
                    current = store().row(row['id'])
                    if current.get('control'):
                        continue  # A newer user action arrived while the RPC was in flight.
                    state = remote['state']
                    if state == 'cancelled':
                        store().cancel(row['id'])
                    elif state == 'paused':
                        store().update(row['id'], state=state)
                    elif current['state'] == 'paused':
                        store().update(row['id'], state='sending' if row['direction'] == 'to-phone' else 'receiving')

    async def _checkpoint(self, rpc, identifier):
        await self._sync_controls(rpc)
        state = store().row(identifier)['state']
        if state == 'cancelled':
            raise TransferCancelled()
        if state == 'paused':
            # Yield the serial RPC slot to the session scheduler. Partial data
            # remains private; the same offset resumes after an explicit action.
            raise TransferPaused()

    async def _send(self, rpc, row, path):
        identifier = row['id']
        retain = False
        try:
            await self._checkpoint(rpc, identifier)
            if not row.get('started'):
                await rpc.call('begin', id=identifier, name=row['name'], size=row['size'], sha256=await asyncio.to_thread(digest_file, path))
                store().update(identifier, started=True)
            offset = row.get('done', 0)
            with path.open('rb') as stream:
                stream.seek(offset)
                while True:
                    await self._checkpoint(rpc, identifier)
                    chunk = stream.read(getattr(rpc, 'chunk_size', WIRE_CHUNK))
                    if not chunk:
                        break
                    reply = await rpc.call('write', id=identifier, offset=offset, data=base64.b64encode(chunk).decode())
                    if reply.get('state') in {'paused', 'cancelled'}:
                        store().update(identifier, state=reply['state'])
                        stream.seek(offset)
                        continue
                    offset += len(chunk)
                    if reply.get('offset') != offset:
                        raise ValueError('The iPhone did not acknowledge the file chunk.')
                    store().update(identifier, done=offset)
            await self._checkpoint(rpc, identifier)
            reply = await rpc.call('finish', id=identifier)
            if reply.get('state') in {'paused', 'cancelled'}:
                store().update(identifier, state=reply['state'])
                if reply['state'] == 'cancelled':
                    raise TransferCancelled()
                raise TransferPaused()
            store().update(identifier, state='complete', done=offset)
        except TransferPaused:
            retain = True
        except TransferCancelled:
            store().update(identifier, state='cancelled')
        except BaseException as error:
            store().update(identifier, state='failed', error=str(error) or 'Transfer disconnected. Send the file again.')
            raise
        finally:
            if not retain:
                path.unlink(missing_ok=True)

    async def _receive(self, rpc, remote, peer):
        incoming = store().incoming(remote, peer)
        if incoming is None:
            await rpc.call('received', id=remote['id'])
            return
        identifier, path = incoming
        if store().row(identifier)['state'] == 'queued':
            store().update(identifier, state='receiving')
        retain = False
        try:
            offset = path.stat().st_size if path.exists() else 0
            with path.open('ab') as stream:
                while offset < remote['size']:
                    await self._checkpoint(rpc, identifier)
                    length = min(getattr(rpc, 'chunk_size', WIRE_CHUNK), remote['size'] - offset)
                    result = await rpc.call('read', id=remote['id'], offset=offset, length=length)
                    if result.get('state') in {'paused', 'cancelled'}:
                        store().update(identifier, state=result['state'])
                        continue
                    data = base64.b64decode(result.get('data', ''), validate=True)
                    if not data or len(data) > length or offset + len(data) > remote['size']:
                        raise ValueError('Incomplete or oversized iPhone file chunk.')
                    stream.write(data)
                    offset += len(data)
                    store().update(identifier, done=offset)
            await self._checkpoint(rpc, identifier)
            delivered = await asyncio.to_thread(store().deliver, identifier, path, remote['sha256'])
            if not delivered:
                raise TransferCancelled()
        except TransferPaused:
            retain = True
            return
        except TransferCancelled:
            store().update(identifier, state='cancelled')
            return
        except BaseException as error:
            store().update(identifier, state='failed', error=str(error) or 'Transfer disconnected. Reconnect to retry.')
            raise
        finally:
            if not retain:
                path.unlink(missing_ok=True)
        # Completion is durable before acknowledging. A lost ACK cannot duplicate it.
        await rpc.call('received', id=remote['id'])


bluetooth = Bluetooth()
