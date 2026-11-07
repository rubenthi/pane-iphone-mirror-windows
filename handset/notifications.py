"""Optional native Bluetooth worker. No phone notification content crosses HTTP.

The worker persists independently only with explicit background opt-in. It watches
settings changes and Bluetooth events; it does not run Python or WebView2.
"""
from __future__ import annotations
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

_LOCK = threading.RLock()
_PROCESS = None
_DESKTOP_ACTIVE = False
_MIRRORING = False
_CACHED_HELPER = None
_ERROR = None
_NEXT_START = 0.0
DEFAULTS = dict(background_enabled=False, notifications_enabled=False, show_previews=False,
                audio_enabled=True, audio_device_id='', notification_device_id='',
                categories=['calls', 'messages'], tour_complete=False)
CATEGORIES = {'calls', 'messages', 'mail', 'calendar', 'other'}


def data_dir():
    return Path(os.environ.get('PANE_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Pane')))


def _read(path, fallback):
    try:
        if path.stat().st_size > 32768:
            return fallback
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else fallback
    except (OSError, ValueError):
        return fallback


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


def validate(patch):
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError('Unknown preference.')
    for key, value in patch.items():
        if isinstance(DEFAULTS[key], bool) and type(value) is not bool:
            raise ValueError('Expected an on/off preference.')
        if key.endswith('_device_id') and (not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value)):
            raise ValueError('Invalid Bluetooth device.')
        if key == 'categories' and (not isinstance(value, list) or len(value) > 5 or any(not isinstance(x, str) or x not in CATEGORIES for x in value) or len(set(value)) != len(value)):
            raise ValueError('Invalid notification categories.')
    return patch


def preferences():
    raw = _read(data_dir() / 'preferences.json', {})
    valid = {}
    for key in DEFAULTS:
        if key in raw:
            try:
                valid.update(validate({key: raw[key]}))
            except ValueError:
                pass
    return {**DEFAULTS, **valid}


def save(patch):
    with _LOCK:
        value = {**preferences(), **validate(patch)}
        _write(data_dir() / 'preferences.json', value)
        _ensure_running(value)
        return {'preferences': value, 'companion': status()}


def _source_helper():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'native' / 'pane-companion.exe'
    return Path(__file__).resolve().parents[1] / 'native' / 'target' / 'release' / 'pane-companion.exe'


def _helper():
    global _CACHED_HELPER
    if _CACHED_HELPER and _CACHED_HELPER.is_file():
        return _CACHED_HELPER
    source = _source_helper()
    if os.name != 'nt' or not source.is_file():
        return None
    body = source.read_bytes()
    digest = hashlib.sha256(body).hexdigest()[:20]
    # PyInstaller removes its extraction directory when the UI closes. Keep the
    # worker in an immutable, content-addressed path so background mode survives.
    target = data_dir() / 'native' / digest / 'PaneCompanion.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(body).digest():
        tmp = target.with_suffix('.tmp'); tmp.write_bytes(body); os.replace(tmp, target)
    # Remove only obsolete files created by this helper. Windows refuses to
    # unlink a running executable, so a surviving background version is kept.
    for version in target.parent.parent.iterdir():
        if version == target.parent or version.is_symlink() or len(version.name) != 20 or any(c not in '0123456789abcdef' for c in version.name):
            continue
        try:
            (version / 'PaneCompanion.exe').unlink(missing_ok=True)
            version.rmdir()  # Never recursively remove unknown files.
        except OSError:
            pass
    _CACHED_HELPER = target
    return target


def _write_session(helper=None):
    _write(data_dir() / 'session.json', {
        'desktop_pid': os.getpid() if _DESKTOP_ACTIVE else 0,
        'mirroring': _MIRRORING,
        'desktop_executable': sys.executable if getattr(sys, 'frozen', False) else '',
        'helper_executable': str(helper or _CACHED_HELPER or ''),
    })


def _ensure_running(prefs=None):
    global _PROCESS, _ERROR, _NEXT_START
    prefs = prefs or preferences()
    needed = (prefs['notifications_enabled'] and (_DESKTOP_ACTIVE or prefs['background_enabled'])) or (prefs['audio_enabled'] and _MIRRORING)
    if not needed or (_PROCESS is not None and _PROCESS.poll() is None):
        return
    try:
        helper = _helper()
        if helper:
            # Publish the requested version before starting its replacement.
            # The old worker closes cooperatively without changing preferences.
            _write_session(helper)
            state = _read(data_dir() / 'companion-status.json', {})
            if state.get('helper_executable') == str(helper) and _alive(state.get('pid')):
                return
            if (_PROCESS is not None and _PROCESS.poll() != 0
                    and time.monotonic() < _NEXT_START):
                return
            _NEXT_START = time.monotonic() + 45
            _PROCESS = subprocess.Popen([str(helper), '--run', str(data_dir())], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        _ERROR = None
    except OSError:
        _ERROR = 'Bluetooth services could not start. Check the Pane installation and try again.'
        logging.exception('Optional Bluetooth worker could not start')


def session(*, desktop=None, mirroring=None):
    global _DESKTOP_ACTIVE, _MIRRORING, _ERROR
    with _LOCK:
        if desktop is not None:
            _DESKTOP_ACTIVE = desktop
        if mirroring is not None:
            _MIRRORING = mirroring
        try:
            _write_session()
            if not (data_dir() / 'preferences.json').exists():
                _write(data_dir() / 'preferences.json', preferences())
            _ensure_running()
        except OSError:
            # Optional audio/alerts must never break the existing mirror path.
            _ERROR = 'Bluetooth settings could not be saved. Check access to the Pane data folder.'
            logging.exception('Optional Bluetooth session could not be saved')


def stop_for_reset():
    """Ask only our worker to exit before an explicitly requested data reset."""
    pid = _read(data_dir() / 'companion-status.json', {}).get('pid')
    with _LOCK:
        _write(data_dir() / 'preferences.json', {**preferences(), 'notifications_enabled': False, 'audio_enabled': False, 'background_enabled': False})
        _write(data_dir() / 'session.json', {'desktop_pid': 0, 'mirroring': False})
    deadline = time.monotonic() + 35
    while _alive(pid):
        if time.monotonic() >= deadline:
            raise OSError('Pane Bluetooth services are still closing. Retry the reset in a moment.')
        time.sleep(.1)


def _alive(pid):
    if os.name != 'nt' or type(pid) is not int or pid <= 0:
        return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


def status():
    available = os.name == 'nt' and _source_helper().is_file()
    state = _read(data_dir() / 'companion-status.json', {})
    if not _alive(state.get('pid')):
        state = {}
    if _PROCESS is not None and _PROCESS.poll() not in (None, 0):
        state = {'audio': 'Bluetooth services could not restart. Close and reopen Pane to retry.',
                 'notifications': 'Bluetooth services could not restart. Close and reopen Pane to retry.'}
    if _ERROR:
        state = {'audio': _ERROR, 'notifications': _ERROR}
    return {'available': available, **state}


def devices():
    try:
        helper = _helper()
    except OSError:
        helper = None
    if not helper:
        return {'audio': [], 'notifications': [], 'error': 'Use the Windows release to connect Bluetooth audio and notifications.'}
    try:
        result = subprocess.run([str(helper), '--devices'], capture_output=True, timeout=20, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if len(result.stdout) > 262144:
            raise ValueError('Bluetooth device list is too large.')
        return json.loads(result.stdout.decode('utf-8'))
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'audio': [], 'notifications': [], 'error': 'Could not list Bluetooth devices. Turn on Bluetooth and pair your iPhone in Windows Settings.'}


def open_bluetooth_settings():
    if os.name != 'nt':
        raise ValueError('Bluetooth settings are available on Windows.')
    os.startfile('ms-settings:bluetooth')
