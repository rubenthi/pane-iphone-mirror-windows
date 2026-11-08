"""Read-only companion update checks. Never pair, sign, install or alter bindings."""
from __future__ import annotations
import asyncio
import re
import threading
import time
import plistlib
import zipfile
from handset.companion_version import COMPANION_VERSION, validate_companion
from handset.signing import bundled_package
from handset.mux import list_devices
from handset.state import DATA_DIR, read_json, write_json

_LOCK = threading.Lock()
_LAST = {}
_RESULTS = {}
_INVALIDATED = set()
CACHE_SECONDS = 60
CHECK_SECONDS = 5


def version(value):
    if not isinstance(value, str) or len(value) > 40 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", value):
        return None
    parts = tuple(map(int, value.split('.')))
    return parts + (0,) * (4 - len(parts))


async def _read(udid, bundle):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    lockdown = await create_using_usbmux(serial=udid, connection_type='USB', autopair=False)
    try:
        async with InstallationProxyService(lockdown) as installer:
            apps = await installer.browse(options={'ApplicationType': 'User'})
        matches = [app for app in apps if app.get('CFBundleExecutable') == 'PaneFiles'
                   and app.get('CFBundleDisplayName') == 'Pane'
                   and (not bundle or app.get('CFBundleIdentifier') == bundle)]
        if len(matches) != 1 or not version(matches[0].get('CFBundleShortVersionString')):
            return None
        return {'version': matches[0]['CFBundleShortVersionString'],
                'bundle': matches[0]['CFBundleIdentifier']}
    finally:
        await lockdown.close()


def check():
    # Serialize concurrent requests and throttle even failed USB reads.
    with _LOCK:
        try:
            validate_companion(bundled_package())
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, plistlib.InvalidFileException):
            return {'availableVersion': None, 'installedVersion': None, 'updateAvailable': False,
                    'connected': False, 'cached': False, 'packageUnavailable': True}
        cache_path = DATA_DIR / 'companion-version.json'
        saved = read_json(cache_path, {})
        binding = read_json(DATA_DIR / 'binding.json', {})
        setup = read_json(DATA_DIR / 'setup.json', {})
        if not isinstance(saved, dict): saved = {}
        if not isinstance(binding, dict): binding = {}
        if not isinstance(setup, dict): setup = {}
        try:
            devices = [d['udid'] for d in list_devices() if d.get('connection') == 'USB']
        except Exception:
            devices = []
        udid = binding.get('udid') or setup.get('udid') or (devices[0] if len(devices) == 1 else saved.get('udid') if not devices else None)
        bundle = binding.get('bundle')
        record = saved if saved.get('udid') == udid and (not bundle or saved.get('bundle') == bundle) else {}
        if udid in _INVALIDATED:
            record = {}
        connected = bool(udid and udid in devices)
        key = (udid, bundle)
        if key in _RESULTS:
            record = _RESULTS[key]
        if connected and time.monotonic() - _LAST.get(key, -CACHE_SECONDS) >= CACHE_SECONDS:
            _LAST[key] = time.monotonic()
            try:
                found = asyncio.run(asyncio.wait_for(_read(udid, bundle), CHECK_SECONDS))
            except Exception:
                found = None
            # A failed/ambiguous current read must not claim this phone is outdated.
            record = dict(found or {}, udid=udid, checkedAt=time.time())
            _RESULTS[key] = record
            if found:
                _INVALIDATED.discard(udid)
            try:
                write_json(cache_path, record)
            except OSError:
                pass
        installed = record.get('version') if version(record.get('version')) else None
        newer = bool(installed and version(installed) < version(COMPANION_VERSION))
        return {'availableVersion': COMPANION_VERSION, 'installedVersion': installed,
                'updateAvailable': newer, 'connected': connected,
                'cached': bool(installed and not connected), 'checkedAt': record.get('checkedAt')}


def invalidate(udid):
    """Installation completed: forget the old version until verified over USB."""
    with _LOCK:
        _LAST.clear()
        _RESULTS.clear()
        _INVALIDATED.add(udid)
        path = DATA_DIR / 'companion-version.json'
        saved = read_json(path, {})
        if isinstance(saved, dict) and saved.get('udid') == udid:
            try:
                write_json(path, {'udid': udid})
            except OSError:
                # Optional version bookkeeping must not fail a completed install.
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
