"""Bounded file staging and atomic, non-overwriting Downloads delivery."""
from __future__ import annotations

import base64
import errno
import hashlib
import os
from pathlib import Path
import re
import threading
import time
import uuid

from handset.state import DATA_DIR, downloads_folder, read_json, write_json

MAX_FILE = 2 * 1024**3
MAX_IPA = 128 * 1024**2
CHUNK = 256 * 1024
SEND_ERROR = 'Transfer interrupted. Send the file again.'
RECEIVE_ERROR = 'File could not be received or verified. Reconnect to retry.'
RESTART_ERROR = 'Pane restarted. Please send the file again.'


def safe_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Missing file name.')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', value).strip(' .')[:180].rstrip(' .')
    if not name:
        raise ValueError('Missing file name.')
    # Windows also reserves superscript port numbers and ignores spaces before an extension.
    stem = name.split('.')[0].rstrip(' ').upper().translate(str.maketrans('¹²³', '123'))
    if stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
        name = '_' + name
    return name


def digest_file(path: Path, *, sync_to_disk=False) -> str:
    with path.open('rb+' if sync_to_disk else 'rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if sync_to_disk:
            os.fsync(stream.fileno())
        return digest


def valid_size(size, limit=MAX_FILE):
    if type(size) is not int or not 0 <= size <= limit:
        raise ValueError(f'File size must be between 0 and {limit} bytes.')


class TransferStore:
    def __init__(self, root=DATA_DIR, downloads=None):
        self.root = root
        self.downloads = downloads
        self.lock = threading.RLock()
        self.pending = {}
        self.rows = read_json(root / 'transfers.json', [])
        if not isinstance(self.rows, list):
            self.rows = []
        self.rows = [r for r in self.rows if isinstance(r, dict)][-200:]
        history_changed = False
        for row in self.rows:
            if row.get('state') in {'queued', 'sending', 'receiving', 'paused'}:
                row.update(state='failed', error=RESTART_ERROR)
                history_changed = True
            elif row.get('error') and row['error'] not in (SEND_ERROR, RECEIVE_ERROR, RESTART_ERROR):
                # Older releases stored driver exceptions containing GATT payload bytes.
                row['error'] = SEND_ERROR if row.get('direction') == 'to-phone' else RECEIVE_ERROR
                history_changed = True
        if history_changed:
            write_json(root / 'transfers.json', self.rows)
        # Only opaque IDs owned by this module; never paths supplied by the phone.
        for folder in ('staging', 'outbox'):
            directory = root / folder
            directory.mkdir(parents=True, exist_ok=True)
            for path in directory.iterdir():
                if re.fullmatch(r'[a-f0-9]{32}\.part', path.name):
                    path.unlink(missing_ok=True)

    def _save(self):
        # Keep all active rows, with a bounded completed history.
        active = [r for r in self.rows if r['state'] in {'queued', 'sending', 'receiving', 'paused'}]
        history = [r for r in self.rows if r not in active][-200:]
        self.rows = history + active
        write_json(self.root / 'transfers.json', self.rows)

    def status(self):
        with self.lock:
            destination = self.downloads or downloads_folder()
            return {'destination': str(destination), 'transfers': [dict(r) for r in reversed(self.rows)]}

    def begin(self, name, size, kind='file'):
        if kind not in {'file', 'ipa'}:
            raise ValueError('Unknown upload type.')
        valid_size(size, MAX_IPA if kind == 'ipa' else MAX_FILE)
        name = safe_name(name)
        with self.lock:
            active = [r for r in self.rows if r['state'] in {'queued', 'sending', 'paused'}]
            if len(self.pending) + len(active) >= 8 or sum(p['size'] for p in self.pending.values()) + sum(r['size'] for r in active) + size > 4 * MAX_FILE:
                raise ValueError('Finish or cancel queued uploads first.')
            identifier = uuid.uuid4().hex
            path = self.root / 'staging' / (identifier + '.part')
            path.touch(exist_ok=False)
            self.pending[identifier] = dict(id=identifier, name=name, size=size, kind=kind, offset=0, path=path)
            return {'id': identifier}

    def append(self, identifier, offset, encoded):
        with self.lock:
            item = self._pending(identifier)
            if type(offset) is not int or offset != item['offset']:
                raise ValueError('Upload offset mismatch. Retry the file.')
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise ValueError('Invalid file chunk.') from None
            if not data or len(data) > CHUNK or offset + len(data) > item['size']:
                raise ValueError('File chunk exceeds its declared size.')
            with item['path'].open('ab') as stream:
                stream.write(data)
            item['offset'] += len(data)
            return {'offset': item['offset']}

    def _pending(self, identifier):
        if not isinstance(identifier, str) or identifier not in self.pending:
            raise ValueError('Upload not found.')
        return self.pending[identifier]

    def finish(self, identifier, kind):
        with self.lock:
            item = self._pending(identifier)
            if item['kind'] != kind or item['offset'] != item['size']:
                raise ValueError('Upload is incomplete or the wrong type.')
            if kind == 'file':
                target = self.root / 'outbox' / item['path'].name
                item['path'].replace(target)
                item['path'] = target
                self.rows.append(dict(id=identifier, name=item['name'], size=item['size'],
                                      done=0, direction='to-phone', state='queued', time=time.time()))
                self._save()
            del self.pending[identifier]
            return item

    def control(self, identifier, action):
        if action not in {'pause', 'resume', 'cancel'} or not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Invalid transfer control.')
        with self.lock:
            row = next((r for r in self.rows if r['id'] == identifier), None)
            if row and row['state'] not in {'complete', 'failed', 'cancelled'}:
                if action == 'pause':
                    row['beforePause'] = row['state'] if row['state'] != 'paused' else row.get('beforePause', 'queued')
                    row['state'] = 'paused'
                elif action == 'resume':
                    if row['state'] != 'paused':
                        return {'ok': True}
                    row['state'] = row.pop('beforePause', 'queued' if row['direction'] == 'to-phone' else 'receiving')
                else:
                    row['state'] = 'cancelled'
                row['control'] = row['state']
                self._save()
            return {'ok': True}

    def cancel(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Invalid upload ID.')
        with self.lock:
            item = self.pending.pop(identifier, None)
            if item:
                item['path'].unlink(missing_ok=True)
            self.control(identifier, 'cancel')
            # Active streams own their handles and remove their partial file at
            # the next acknowledged batch boundary (Windows cannot unlink it open).
            for folder in ('staging', 'outbox'):
                try:
                    (self.root / folder / (identifier + '.part')).unlink(missing_ok=True)
                except PermissionError:
                    pass
            return {'ok': True}

    def row(self, identifier):
        with self.lock:
            return dict(next(r for r in self.rows if r['id'] == identifier))

    def next_outgoing(self, *, preserve_legacy=False):
        with self.lock:
            if preserve_legacy and any(r['direction'] == 'to-phone' and r['state'] == 'paused' and r.get('started') for r in self.rows):
                return None
            row = next((r for r in self.rows if r['state'] in {'queued', 'sending'} and r['direction'] == 'to-phone'), None)
            if row:
                row['state'] = 'sending'
                return dict(row), self.root / 'outbox' / (row['id'] + '.part')

    def update(self, identifier, **values):
        with self.lock:
            row = next(r for r in self.rows if r['id'] == identifier)
            if row['state'] == 'cancelled' and values.get('state') != 'cancelled':
                return
            row.update(values)
            if row['state'] in {'complete', 'failed', 'cancelled'}:
                self._save()

    def incoming(self, remote, peer):
        name = safe_name(remote.get('name'))
        valid_size(remote.get('size'))
        if not re.fullmatch(r'[a-fA-F0-9-]{32,36}', remote.get('id', '')) or not re.fullmatch(r'[a-f0-9]{64}', remote.get('sha256', '')):
            raise ValueError('Invalid file metadata from iPhone.')
        remote_key = f"{peer}:{remote['id']}:{remote['sha256']}"
        with self.lock:
            if any(r.get('remote') == remote_key and r['state'] == 'complete' for r in self.rows):
                return None
            existing = next((r for r in self.rows if r.get('remote') == remote_key and r['state'] in {'queued', 'receiving', 'paused', 'cancelled'}), None)
            if existing:
                return existing['id'], self.root / 'staging' / (existing['id'] + '.part')
            identifier = uuid.uuid4().hex
            self.rows.append(dict(id=identifier, remoteId=remote['id'], remote=remote_key, name=name, size=remote['size'],
                                  done=0, direction='from-phone', state='queued', time=time.time()))
            self._save()
            return identifier, self.root / 'staging' / (identifier + '.part')

    @staticmethod
    def _publish(part, folder, name):
        """Publish an existing file on this volume without replacing any name."""
        stem, suffix = Path(name).stem, Path(name).suffix
        for index in range(10000):
            candidate = name if index == 0 else f'{stem} ({index}){suffix}'
            try:
                if os.name == 'nt':
                    part.rename(folder / candidate)
                else:
                    os.link(part, folder / candidate)
                return candidate
            except FileExistsError:
                continue
        raise ValueError('Too many files with the same name in Downloads.')

    def deliver(self, identifier, part, expected_hash):
        """Return True on delivery, False on cancel and None on pause."""
        row = self.row(identifier)
        if row['state'] == 'cancelled':
            part.unlink(missing_ok=True)
            return False
        if row['state'] == 'paused':
            return None
        # Do not hold the queue lock over disk I/O: controls and status should
        # remain responsive even while verifying a multi-gigabyte file.
        try:
            verified = part.stat().st_size == row['size'] and digest_file(part, sync_to_disk=True) == expected_hash
        except FileNotFoundError:
            if self.row(identifier)['state'] == 'cancelled':
                return False
            raise
        if not verified:
            raise ValueError('File verification failed. Nothing was saved to Downloads.')
        folder = self.downloads or downloads_folder()
        folder.mkdir(parents=True, exist_ok=True)

        def publish(path):
            with self.lock:
                state = self.row(identifier)['state']
                if state == 'paused':
                    return None
                if state == 'cancelled':
                    return False
                name = self._publish(path, folder, row['name'])
                self.update(identifier, state='complete', done=row['size'], savedAs=name)
                return True

        try:
            delivered = publish(part)
        except OSError as error:
            if error.errno != errno.EXDEV and getattr(error, 'winerror', None) != 17:
                raise
            # Downloads can be redirected to another drive. Stage on that
            # drive, and recheck the bytes actually copied before publication.
            temporary = folder / ('.pane-' + identifier + '.part')
            target = temporary.open('xb')
            try:
                with target, part.open('rb') as source:
                    copied = hashlib.sha256()
                    while block := source.read(CHUNK):
                        target.write(block)
                        copied.update(block)
                    target.flush()
                    os.fsync(target.fileno())
                if copied.hexdigest() != expected_hash:
                    raise ValueError('File verification failed. Nothing was saved to Downloads.')
                delivered = publish(temporary)
            finally:
                temporary.unlink(missing_ok=True)
        if delivered is not None:
            part.unlink(missing_ok=True)
        return delivered


_STORE = None
_STORE_LOCK = threading.Lock()


def store():
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = TransferStore()
        return _STORE
