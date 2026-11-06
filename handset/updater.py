"""Check this fork at startup; apply a verified update after normal app exit."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request

from handset.version import REPOSITORY, VERSION

BASE = f'https://github.com/{REPOSITORY}/releases'
MANIFEST_URL = f'{BASE}/latest/download/update.json'
_LOCK = threading.Lock()
_STATE = {'phase': 'idle', 'version': VERSION}
_STAGED = None
MAX_EXE_SIZE = 512 * 1024 * 1024


def status():
    with _LOCK:
        return dict(_STATE)


def _set(**values):
    with _LOCK:
        _STATE.update(values)


def validate_manifest(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid update manifest')
    version = data.get('version', '')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid update version')
    if data.get('url') != f'{BASE}/download/v{version}/Pane.exe':
        raise ValueError('Update URL must point to this fork and version')
    if not isinstance(data.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', data['sha256']):
        raise ValueError('Invalid update checksum')
    if type(data.get('size')) is not int or not 0 < data['size'] <= MAX_EXE_SIZE:
        raise ValueError('Invalid update size')
    return tuple(map(int, version.split('.'))) > tuple(map(int, VERSION.split('.')))


def monitor(stop=None):
    """Check at launch and keep retrying while Pane is open."""
    stop = stop or threading.Event()
    while not stop.is_set():
        check()
        phase = status()['phase']
        if phase in {'ready', 'source'}:
            return
        # Recover from offline startup without requiring a restart.
        if stop.wait(15 * 60 if phase == 'error' else 6 * 60 * 60):
            return


def check():
    global _STAGED
    if not getattr(sys, 'frozen', False) or os.name != 'nt':
        _set(phase='source', note='Automatic updates apply to the Windows executable.')
        return
    try:
        _set(phase='checking')
        with urllib.request.urlopen(MANIFEST_URL, timeout=20) as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError('Update manifest too large')
        data = json.loads(raw)
        if not validate_manifest(data):
            _set(phase='current')
            return
        directory = Path(tempfile.mkdtemp(prefix='Pane-update-'))
        exe = directory / 'Pane.exe'
        digest = hashlib.sha256()
        count = 0
        try:
            with urllib.request.urlopen(data['url'], timeout=30) as response, exe.open('wb') as out:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > data['size']:
                        raise ValueError('Update exceeds expected size')
                    digest.update(chunk)
                    out.write(chunk)
            if count != data['size'] or digest.hexdigest() != data['sha256']:
                raise ValueError('Update checksum or size mismatch')
            # Copy the bundled, reviewed helper out of PyInstaller's temporary folder.
            helper = directory / 'apply.ps1'
            source = Path(__file__).with_name('install_update.ps1').read_text(encoding='utf-8')
            helper.write_text(
                'param([string]$SourcePath,[string]$Destination,[string]$Sha256,[int]$WaitProcessId)\n'
                + source + '\ntry { Install-PaneExecutable @PSBoundParameters | Out-Null } '
                'catch { $_ | Out-File -LiteralPath (Join-Path $PSScriptRoot "update-error.log"); exit 1 }\n',
                encoding='utf-8-sig')
            _STAGED = (helper, exe, data['sha256'])
            _set(phase='ready', available_version=data['version'], note='Update verified; close Pane to install. Backup retained.')
        except Exception:
            exe.unlink(missing_ok=True)
            raise
    except Exception as error:
        logging.exception('Update check failed')
        _set(phase='error', note=f'Update unavailable: {error}')


def apply_on_exit():
    if _STAGED is None:
        return
    helper, exe, checksum = _STAGED
    # Do not inherit PowerShell 7's module search path into Windows PowerShell 5.
    # It can prevent Get-FileHash and other built-in cmdlets from loading.
    environment = os.environ.copy()
    for key in list(environment):
        if key.upper() == 'PSMODULEPATH':
            del environment[key]
    powershell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    with (helper.parent / 'update-helper.log').open('ab') as log:
        subprocess.Popen([
            powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(helper), '-SourcePath', str(exe), '-Destination', sys.executable,
            '-Sha256', checksum, '-WaitProcessId', str(os.getpid()),
        ], creationflags=subprocess.CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
           stdout=log, stderr=subprocess.STDOUT, close_fds=True, env=environment)
