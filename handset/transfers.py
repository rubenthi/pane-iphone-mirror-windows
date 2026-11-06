"""Bounded file staging and atomic, non-overwriting Downloads delivery."""
from __future__ import annotations

import base64
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


def safe_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Missing file name.')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', value).strip(' .')[:180].rstrip(' .')
    if not name:
        raise ValueError('Missing file name.')
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
        name = '_' + name
    return name


def digest_file(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


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
        for row in self.rows:
            if row.get('state') in {'queued', 'sending', 'receiving'}:
                row.update(state='failed', error='Pane restarted. Please send the file again.')
        # Only opaque IDs owned by this module; never paths supplied by the phone.
        for folder in ('staging', 'outbox'):
            directory = root / folder
            directory.mkdir(parents=True, exist_ok=True)
            for path in directory.iterdir():
                if re.fullmatch(r'[a-f0-9]{32}\.part', path.name):
                    path.unlink(missing_ok=True)

    def _save(self):
        # Keep all active rows, with a bounded completed history.
        active = [r for r in self.rows if r['state'] in {'queued', 'sending', 'receiving'}]
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
            active = [r for r in self.rows if r['state'] in {'queued', 'sending'}]
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

    def cancel(self, identifier):
        if not isinstance(identifier, str):
            raise ValueError('Invalid upload ID.')
        with self.lock:
            item = self.pending.pop(identifier, None)
            if item:
                item['path'].unlink(missing_ok=True)
            row = next((r for r in self.rows if r['id'] == identifier), None)
            if row and row['state'] == 'queued':
                row.update(state='cancelled')
                (self.root / 'outbox' / (identifier + '.part')).unlink(missing_ok=True)
                self._save()
            return {'ok': True}

    def next_outgoing(self):
        with self.lock:
            row = next((r for r in self.rows if r['state'] == 'queued'), None)
            if row:
                row['state'] = 'sending'
                return dict(row), self.root / 'outbox' / (row['id'] + '.part')

    def update(self, identifier, **values):
        with self.lock:
            row = next(r for r in self.rows if r['id'] == identifier)
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
            identifier = uuid.uuid4().hex
            self.rows.append(dict(id=identifier, remote=remote_key, name=name, size=remote['size'],
                                  done=0, direction='from-phone', state='receiving', time=time.time()))
            self._save()
            return identifier, self.root / 'staging' / (identifier + '.part')

    def deliver(self, identifier, part, expected_hash):
        with self.lock:
            row = next(r for r in self.rows if r['id'] == identifier)
            if part.stat().st_size != row['size'] or digest_file(part) != expected_hash:
                raise ValueError('File verification failed. Nothing was saved to Downloads.')
            folder = self.downloads or downloads_folder()
            folder.mkdir(parents=True, exist_ok=True)
            # Stage on the destination volume, then link exclusively. This avoids
            # overwrites, works across disks, and publishes only complete files.
            temporary = folder / ('.pane-' + identifier + '.part')
            try:
                with part.open('rb') as source, temporary.open('xb') as target:
                    import shutil
                    shutil.copyfileobj(source, target, CHUNK)
                    target.flush()
                    os.fsync(target.fileno())
                stem, suffix = Path(row['name']).stem, Path(row['name']).suffix
                for index in range(10000):
                    name = row['name'] if index == 0 else f'{stem} ({index}){suffix}'
                    destination = folder / name
                    try:
                        # Windows rename is exclusive; POSIX rename would overwrite.
                        if os.name == 'nt':
                            temporary.rename(destination)
                        else:
                            os.link(temporary, destination)
                        break
                    except FileExistsError:
                        continue
                else:
                    raise ValueError('Too many files with the same name in Downloads.')
                self.update(identifier, state='complete', done=row['size'], savedAs=name)
            finally:
                temporary.unlink(missing_ok=True)
                part.unlink(missing_ok=True)


_STORE = None
_STORE_LOCK = threading.Lock()


def store():
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = TransferStore()
        return _STORE
