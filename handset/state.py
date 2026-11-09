"""Pane-owned state. Updates preserve data; resets require an explicit request."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from handset.edition import DEVELOPMENT, data_dir

DATA_DIR = data_dir()
SCHEMA = 2
RESET_REQUEST = 'development-reset.request'
# Never erase arbitrary PANE_DATA_DIR contents or shared Apple trust records.
OWNED = ('signing', 'window', 'webview', 'device', 'staging', 'outbox', 'settings.json',
         'preferences.json', 'session.json', 'companion-status.json', 'native', 'companion.lock',
         'companion-version.json', 'binding.json', 'setup.json', 'transfers.json', 'pane.log', 'state-version.json')


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def can_reset_development():
    base = os.environ.get('LOCALAPPDATA')
    return bool(DEVELOPMENT and base and
                DATA_DIR.resolve() == Path(base).resolve() / 'Pane (Development)' and
                not DATA_DIR.is_symlink() and not (hasattr(DATA_DIR, 'is_junction') and DATA_DIR.is_junction()))


def prepare_state(root: Path = DATA_DIR, *, force: bool = False) -> bool:
    """Preserve all state at startup. Only an explicit force=True request resets it."""
    if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise ValueError('Pane data directory must not be a link.')
    root.mkdir(parents=True, exist_ok=True)
    marker = read_json(root / 'state-version.json', {})
    if not force:
        # Missing/old markers are migrations, never permission to erase user data.
        if not isinstance(marker, dict) or marker.get('schema') != SCHEMA:
            write_json(root / 'state-version.json', {'schema': SCHEMA, 'legacyPairingPending': not DEVELOPMENT})
        return False
    for name in OWNED:
        item = root / name
        if item.is_symlink():
            item.unlink()
        elif hasattr(item, 'is_junction') and item.is_junction():
            item.rmdir()
        elif item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)
    write_json(root / 'state-version.json', {'schema': SCHEMA})
    return True


def isolate_device_state() -> None:
    # Preserve pre-2.x wireless records when moving to Pane's private store.
    # Explicit resets and existing 2.x migrations never re-import shared records.
    try:
        from pymobiledevice3 import common
        marker = read_json(DATA_DIR / 'state-version.json', {})
        if marker.get('legacyPairingPending'):
            legacy = common._HOMEFOLDER
            destination = DATA_DIR / 'device'
            destination.mkdir(parents=True, exist_ok=True)
            if legacy != destination:
                for source in legacy.glob('remote_*.plist'):
                    target = destination / source.name
                    if source.is_file() and not source.is_symlink() and not target.exists():
                        shutil.copy2(source, target)
            marker.pop('legacyPairingPending', None)
            write_json(DATA_DIR / 'state-version.json', marker)
        common._HOMEFOLDER = DATA_DIR / 'device'
    except ImportError:
        pass


def downloads_folder() -> Path:
    if os.name == 'nt':
        import ctypes
        import uuid
        from ctypes import wintypes
        # FOLDERID_Downloads: honors a relocated Windows Downloads directory.
        folder_id = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID('374de290-123f-4565-9164-39c4925e467b').bytes_le)
        result = ctypes.c_wchar_p()
        shell = ctypes.windll.shell32.SHGetKnownFolderPath
        shell.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        shell.restype = ctypes.c_long
        if shell(ctypes.byref(folder_id), 0, None, ctypes.byref(result)) != 0:
            raise OSError('Windows could not locate your Downloads folder.')
        try:
            return Path(result.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))
    return Path.home() / 'Downloads'
