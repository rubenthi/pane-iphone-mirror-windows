"""Encrypted BLE GATT file transfer to the USB-bound Pane companion."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import threading
import time

from handset.setup import COMMAND_UUID, RESPONSE_UUID
from handset.state import DATA_DIR, read_json, write_json
from handset.transfers import RECEIVE_ERROR, SEND_ERROR, store, digest_file

WIRE_CHUNK = 4096
MAX_FRAME = 65536
FAST_CHUNK = 32768
CONTROL_INTERVAL = 0.75


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
        self.receive_chunk_size = WIRE_CHUNK
        self.wifi_upload = False
        self.wifi_download = False

    def negotiate(self, capabilities):
        if not isinstance(capabilities, list):
            raise ValueError('Invalid iPhone capabilities.')
        self.controls = 'transfer-control-v1' in capabilities
        payload = max(20, self.client.mtu_size - 3)
        # Avoid turning a low-MTU legacy connection into thousands of response
        # writes per request. The same 45-second bound still applies per RPC.
        batch = WIRE_CHUNK if payload <= 64 else 16384 if payload <= 185 else FAST_CHUNK
        self.chunk_size = batch if 'chunk-32768' in capabilities else WIRE_CHUNK
        # Read requests contain only a range. The phone fragments the reply
        # using its own notification size/backpressure; Windows write MTU
        # must not restrict this application-level receive batch.
        self.receive_chunk_size = FAST_CHUNK if 'chunk-32768' in capabilities else WIRE_CHUNK
        self.wifi_upload = 'wifi-upload-v1' in capabilities
        self.wifi_download = 'wifi-download-v1' in capabilities

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
                    try:
                        await self.client.write_gatt_char(COMMAND_UUID, wire[offset:offset + size], response=True)
                    except Exception as error:
                        # Backends use different exception classes, and some include
                        # the entire write payload. Expose only the ATT error number.
                        att = re.search(r'Protocol Error 0x[0-9a-fA-F]{2}', str(error))
                        raise ConnectionError(att[0] if att else 'Bluetooth write disconnected.') from None
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
        self._control_rpc = None
        self._control_payload = None
        self._control_time = 0.0

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
            result = await rpc.call('hello', token=binding['token'], capabilities=['transfer-control-v1', 'chunk-32768', 'wifi-upload-v1', 'wifi-download-v1'])
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

    async def _sync_controls(self, rpc, *, force=True):
        if not getattr(rpc, 'controls', False):
            return
        rows = store().status()['transfers']
        payload = []
        for row in rows:
            if row['state'] in {'complete', 'failed'} or (row['state'] == 'cancelled' and not row.get('control')):
                continue
            keys = ('id', 'direction', 'state', 'control', 'remoteId') if row['state'] == 'cancelled' or row['direction'] == 'from-phone' else ('id', 'name', 'size', 'direction', 'state', 'control', 'remoteId')
            payload.append({key: row[key] for key in keys if key in row})
        # Acknowledged ATT writes make a full manifest expensive. Poll remote
        # actions periodically, but never delay a changed queue or local action.
        now = time.monotonic()
        if (not force and self._control_rpc is rpc and payload == self._control_payload
                and not any('control' in row for row in payload)
                and now - self._control_time < CONTROL_INTERVAL):
            return
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
                    if current['state'] in {'complete', 'failed', 'cancelled'} or current.get('control'):
                        continue  # A newer user action arrived while the RPC was in flight.
                    state = remote['state']
                    if state == 'cancelled':
                        store().cancel(row['id'])
                    elif state == 'paused':
                        store().update(row['id'], state=state)
                    elif current['state'] == 'paused':
                        store().update(row['id'], state='sending' if row['direction'] == 'to-phone' else 'receiving')
        self._control_rpc = rpc
        self._control_payload = payload
        self._control_time = time.monotonic()

    async def _checkpoint(self, rpc, identifier, *, force=False):
        await self._sync_controls(rpc, force=force)
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
        finishing = False
        try:
            await self._checkpoint(rpc, identifier)
            if not row.get('started'):
                reply = await rpc.call('begin', id=identifier, name=row['name'], size=row['size'], sha256=await asyncio.to_thread(digest_file, path))
                self._outgoing_control(identifier, reply)
                if getattr(rpc, 'wifi_download', False) and reply.get('completed') is True:
                    store().update(identifier, state='complete', done=row['size'])
                    return
                store().update(identifier, started=True)
            offset = row.get('done', 0)
            with path.open('rb') as stream:
                if getattr(rpc, 'wifi_download', False) and offset < row['size']:
                    offset = await self._send_fast(rpc, identifier, stream, offset, row['size'])
                stream.seek(offset)
                while True:
                    await self._checkpoint(rpc, identifier)
                    chunk = stream.read(getattr(rpc, 'chunk_size', WIRE_CHUNK))
                    if not chunk:
                        break
                    reply = await rpc.call('write', id=identifier, offset=offset, data=base64.b64encode(chunk).decode())
                    self._outgoing_control(identifier, reply)
                    offset += len(chunk)
                    if reply.get('offset') != offset:
                        raise ValueError('The iPhone did not acknowledge the file chunk.')
                    store().update(identifier, done=offset)
            await self._checkpoint(rpc, identifier, force=True)
            finishing = True
            reply = await rpc.call('finish', id=identifier)
            finishing = False
            self._outgoing_control(identifier, reply)
            store().update(identifier, state='complete', done=offset)
        except TransferPaused:
            retain = True
        except TransferCancelled:
            store().update(identifier, state='cancelled')
        except BaseException as error:
            link_lost = isinstance(error, (ConnectionError, TimeoutError, asyncio.CancelledError))
            if getattr(rpc, 'wifi_download', False) and (link_lost or finishing and isinstance(error, OSError)):
                # Reconnect with the same ID: begin resets a partial transfer or
                # reports a matching receipt when the final ACK went missing.
                storage = store()
                with storage.lock:
                    state = storage.row(identifier)['state']
                    if state != 'cancelled':
                        retain = True
                        storage.update(identifier, state='paused' if state == 'paused' else 'queued', started=False, done=0)
            # WinRT errors can contain an entire GATT write, including file data.
            if not retain:
                store().update(identifier, state='failed', error=SEND_ERROR)
            raise
        finally:
            if not retain:
                path.unlink(missing_ok=True)

    @staticmethod
    def _outgoing_control(identifier, reply):
        state = reply.get('state')
        if state in {'paused', 'cancelled'}:
            store().update(identifier, state=state)
            if state == 'paused':
                raise TransferPaused()
            raise TransferCancelled()

    async def _send_fast(self, rpc, identifier, stream, offset, size):
        from handset.bulk import BulkCancelled, BulkPaused, BulkSender, MAX_BLOCK

        channel = None
        reservation_possible = False
        try:
            try:
                channel = BulkSender(size)
                endpoint = await asyncio.to_thread(channel.start)
                # Once the request leaves Windows, even a lost BLE reply can
                # mean that the iPhone has reserved its incoming file for TLS.
                reservation_possible = True
                reply = await rpc.call('bulk-write', id=identifier, endpoint=endpoint)
                self._outgoing_control(identifier, reply)
                if reply.get('ok') is not True:
                    raise OSError('Fast transfer unavailable.')
                await self._accept_fast_sender(rpc, identifier, channel)
            except (OSError, ValueError, TimeoutError):
                if reservation_possible:
                    reservation_possible = False
                    channel.close()
                    return await self._release_fast_sender(rpc, identifier, offset, offset)
                store().update(identifier, transport='bluetooth')
                return offset
            if type(reply.get('offset')) is not int or reply['offset'] != offset:
                raise ValueError('The iPhone has a different file offset.')
            store().update(identifier, transport='wifi')
            stream.seek(offset)
            while offset < size:
                await self._checkpoint(rpc, identifier)
                chunk = stream.read(min(MAX_BLOCK, size - offset))
                if not chunk:
                    raise ValueError('Staged file is incomplete.')
                end = offset + len(chunk)
                try:
                    await channel.write(offset, chunk)
                except BulkPaused:
                    store().update(identifier, state='paused')
                    raise TransferPaused() from None
                except BulkCancelled:
                    raise TransferCancelled() from None
                except OSError:
                    # The iPhone may have appended this entire block before its
                    # ACK was lost. Fence the previous TLS writer on the phone
                    # before resuming BLE from the authoritative committed offset.
                    channel.close()
                    reservation_possible = False
                    return await self._release_fast_sender(rpc, identifier, offset, end)
                offset = end
                store().update(identifier, done=offset)
            return offset
        except TransferPaused:
            if reservation_possible:
                # After resume Windows might have no Wi-Fi address and use BLE
                # immediately. Release this session's reservation before yielding.
                channel.close()
                await self._release_fast_sender(rpc, identifier, offset, offset, paused=True)
            raise
        finally:
            if channel is not None:
                channel.close()

    async def _release_fast_sender(self, rpc, identifier, offset, end, *, paused=False):
        stopped = await rpc.call('bulk-write-stop', id=identifier)
        if stopped.get('state') == 'cancelled':
            raise TransferCancelled()
        confirmed = stopped.get('offset')
        if type(confirmed) is not int or confirmed not in (offset, end):
            raise ValueError('The iPhone could not confirm the transfer offset.')
        if not paused:
            store().update(identifier, done=confirmed, transport='bluetooth')
        self._outgoing_control(identifier, stopped)
        return confirmed

    async def _accept_fast_sender(self, rpc, identifier, channel):
        # The iPhone may try several LAN addresses. Service pause/cancel while
        # it connects instead of blocking the controls until the whole timeout.
        task = asyncio.create_task(channel.accept())
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=0.5)
                if not done:
                    await self._checkpoint(rpc, identifier)
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _receive(self, rpc, remote, peer):
        incoming = store().incoming(remote, peer)
        if incoming is None:
            await rpc.call('received', id=remote['id'])
            return
        identifier, path = incoming
        if store().row(identifier)['state'] == 'queued':
            store().update(identifier, state='receiving')
        retain = False
        bulk = None
        try:
            offset = path.stat().st_size if path.exists() else 0
            await self._checkpoint(rpc, identifier)
            if getattr(rpc, 'wifi_upload', False) and offset < remote['size']:
                from handset.bulk import BulkReceiver
                try:
                    bulk = BulkReceiver(remote['size'])
                    endpoint = await asyncio.to_thread(bulk.start)
                    result = await rpc.call('bulk-read', id=remote['id'], endpoint=endpoint)
                    if not result.get('ok'):
                        raise OSError('Wi-Fi transfer unavailable.')
                    await bulk.accept()
                    store().update(identifier, transport='wifi')
                except (OSError, ValueError, TimeoutError):
                    if bulk is not None:
                        bulk.close()
                        bulk = None
            with path.open('ab') as stream:
                while offset < remote['size']:
                    await self._checkpoint(rpc, identifier)
                    if bulk is not None:
                        from handset.bulk import BulkPaused, BulkCancelled
                        try:
                            data = await bulk.read(offset, min(256 * 1024, remote['size'] - offset))
                        except BulkPaused:
                            store().update(identifier, state='paused')
                            raise TransferPaused()
                        except BulkCancelled:
                            raise TransferCancelled()
                        except (OSError, ValueError, TimeoutError):
                            # Resume from the last locally written offset; final
                            # size/hash verification is unchanged on either path.
                            bulk.close()
                            bulk = None
                            store().update(identifier, transport='bluetooth')
                            continue
                        stream.write(data)
                        offset += len(data)
                        store().update(identifier, done=offset)
                        continue
                    length = min(getattr(rpc, 'receive_chunk_size', getattr(rpc, 'chunk_size', WIRE_CHUNK)), remote['size'] - offset)
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
            await self._checkpoint(rpc, identifier, force=True)
            delivered = await asyncio.to_thread(store().deliver, identifier, path, remote['sha256'])
            if delivered is None:
                raise TransferPaused()
            if not delivered:
                raise TransferCancelled()
        except TransferPaused:
            retain = True
            return
        except TransferCancelled:
            store().update(identifier, state='cancelled')
            return
        except BaseException:
            store().update(identifier, state='failed', error=RECEIVE_ERROR)
            raise
        finally:
            if bulk is not None:
                bulk.close()
            if not retain:
                path.unlink(missing_ok=True)
        # Completion is durable before acknowledging. A lost ACK cannot duplicate it.
        await rpc.call('received', id=remote['id'])


bluetooth = Bluetooth()
