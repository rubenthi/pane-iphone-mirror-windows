"""Private isideload worker bridge. Secrets only travel through anonymous pipes."""
from __future__ import annotations
import atexit
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import uuid
import subprocess
import sys
import threading
import time
import zipfile
import plistlib
from handset.companion_version import validate_companion
from handset.state import DATA_DIR

_LOCK = threading.RLock()
_STATE = {'phase': 'idle', 'note': 'Sign and install Pane with your Apple Account.'}
_PROCESS = None
_ANSWERS = queue.Queue()

def helper_path():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return root / 'signer' / ('pane-signer.exe' if os.name == 'nt' else 'pane-signer')

def bundled_package():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return root / 'ios' / 'Pane-unsigned.ipa'

def stage_bundled():
    source = bundled_package()
    if not source.is_file():
        raise ValueError('The bundled companion is missing. Choose the unsigned Pane IPA or install a complete Windows build.')
    destination = DATA_DIR / 'staging' / (uuid.uuid4().hex + '.part')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    try:
        validate_companion(destination)
    except (KeyError, ValueError, OSError, plistlib.InvalidFileException, zipfile.BadZipFile) as error:
        destination.unlink(missing_ok=True)
        raise ValueError('The bundled iPhone app is damaged or outdated. Restore the matching Pane IPA before signing.') from error
    return destination

def status():
    with _LOCK:
        return {**_STATE, 'available': helper_path().is_file() and os.name == 'nt', 'bundled': bundled_package().is_file()}

def _set(**values):
    with _LOCK:
        _STATE.update(values)

def protect(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('Integrated signing requires Windows.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Windows could not access protected signing data.')
    kernel = ctypes.WinDLL('kernel32')
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)

def _storage(account, event):
    key = event.get('key')
    if not isinstance(key, str) or len(key) > 4096:
        raise ValueError('Invalid storage key.')
    path = DATA_DIR / 'signing' / account / (hashlib.sha256(key.encode()).hexdigest() + '.bin')
    if event['event'] == 'retrieve':
        return {'value': protect(path.read_bytes(), True).decode() if path.exists() else None}
    value = event.get('value')
    if not isinstance(value, str) or len(value) > 1024 * 1024:
        raise ValueError('Invalid storage value.')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(protect(value.encode()))
    temp.replace(path)
    return {'ok': True}

def start(udid, package, email, password):
    global _PROCESS, _ANSWERS
    from handset import setup
    setup.require_usb(udid)
    setup.inspect_ipa(package, require_signed=False)
    if not isinstance(email, str) or '@' not in email or len(email) > 320 or not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise ValueError('Enter your Apple Account email and password.')
    if not status()['available']:
        raise ValueError('This build does not include the Windows signing helper.')
    with _LOCK:
        if _PROCESS is not None or _STATE['phase'] in {'working', 'prompt'}:
            raise ValueError('A signing session is already running.')
        if setup.status()['phase'] == 'working':
            raise ValueError('Wait for the current USB setup step to finish.')
        process = subprocess.Popen([str(helper_path())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        _PROCESS = process
        _ANSWERS = queue.Queue()
        _STATE.update(phase='working', note='Starting Apple signing…', prompt=None, code=None, stage=None)
        initial = {'email': email.strip(), 'password': password, 'udid': udid, 'ipa': str(package)}
        threading.Thread(target=_run, args=(process, package, initial), daemon=True, name='pane-signing').start()
    return status()

def answer(prompt_id, value):
    with _LOCK:
        prompt = _STATE.get('prompt')
        if _STATE['phase'] != 'prompt' or not prompt or prompt.get('id') != prompt_id:
            raise ValueError('This signing prompt is no longer active.')
        if not isinstance(value, str) or not 1 <= len(value) <= 256:
            raise ValueError('Enter a verification code or choose an option.')
        if prompt['kind'] == 'team' and value not in [c['id'] for c in prompt['choices']]:
            raise ValueError('Choose a listed developer team.')
        _STATE.update(phase='working', prompt=None, note='Continuing signing…')
        _ANSWERS.put({'value': value})
    return status()

def cancel():
    with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            _PROCESS.kill()
        _ANSWERS.put({'error': 'cancelled'})
        _STATE.update(phase='cancelled', prompt=None, note='Signing cancelled. You can retry.')
    return status()

atexit.register(cancel)

def _run(process, package, initial):
    global _PROCESS
    udid = initial.get('udid')
    def expire():
        process.kill()
        _ANSWERS.put({'error': 'timeout'})
    deadline = threading.Timer(600, expire)
    deadline.daemon = True
    deadline.start()
    def send(value):
        process.stdin.write(json.dumps(value) + '\n'); process.stdin.flush()
    try:
        account = hashlib.sha256(initial['email'].lower().encode()).hexdigest()
        send(initial)
        initial.clear()
        completed = False
        while True:
            line = process.stdout.readline(1024 * 1024 + 1)
            if not line:
                break
            if len(line) > 1024 * 1024:
                raise ValueError('Oversized helper response.')
            event = json.loads(line)
            kind = event.get('event')
            if kind in {'store', 'retrieve'}:
                send(_storage(account, event))
            elif kind == 'prompt':
                event['id'] = secrets.token_hex(16)
                _set(phase='prompt', prompt=event, note='Choose your developer team.' if event['kind'] == 'team' else 'Enter the Apple verification code.')
                send(_ANSWERS.get(timeout=300))
            elif kind == 'status':
                _set(note=event['note'])
            elif kind == 'complete':
                completed = True
            elif kind == 'error':
                _set(code=event.get('code'), stage=event.get('stage'))
                raise ValueError(event['note'])
        result = process.wait(timeout=10)
        if not completed or result != 0:
            raise ValueError('Signing stopped before installation completed. Reconnect USB and retry.')
        from handset import setup
        from handset.companion_update import invalidate
        invalidate(udid)
        already_bound = setup.status().get('boundUdid') == udid
        setup._set(phase='waiting', step='bluetooth' if already_bound else 'bind' if setup.status().get('developerEnabled') else 'developer', installed=True, note='Pane updated. Open it on your iPhone; your existing pairing is preserved.' if already_bound else 'Pane installed. Continue with USB and Wi-Fi binding.')
        _set(phase='complete', prompt=None, note=('Pane updated. Your existing pairing is preserved. Open Pane on your iPhone.' if setup.status().get('boundUdid') == udid else 'Pane installed. Complete Developer Mode and USB binding below. Use this same flow to renew before the app expires.'))
    except Exception as error:
        if status()['phase'] != 'cancelled':
            # Only our known messages are exposed; no subprocess output or credentials are logged.
            message = str(error) if isinstance(error, ValueError) else 'Signing could not finish. Check USB and network access, then retry.'
            _set(phase='error', prompt=None, note=message)
    finally:
        initial.clear()
        deadline.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdin.close(); process.stdout.close()
        package.unlink(missing_ok=True)
        with _LOCK:
            if _PROCESS is process:
                _PROCESS = None
