"""USB setup actions. Device prompts and Apple signing remain user controlled."""
from __future__ import annotations

import asyncio
import json
import plistlib
import secrets
import threading
import uuid
import zipfile

from handset.mux import list_devices
from handset.state import DATA_DIR, read_json, write_json
from handset.wifi import pair_for_wifi, wifi_paired_udids

COMMAND_UUID = '8a5d1001-7b44-4b1b-9bb6-a42e447a0001'
RESPONSE_UUID = '8a5d1002-7b44-4b1b-9bb6-a42e447a0001'
_LOCK = threading.RLock()
def initial_state():
    state = {'phase': 'idle', 'step': 'connect', 'note': 'Connect and unlock your iPhone, then tap Trust.'}
    saved = read_json(DATA_DIR / 'setup.json', {})
    if isinstance(saved, dict):
        state.update({k: v for k, v in saved.items() if k in {'step', 'udid', 'usbReady', 'revealed', 'developerEnabled', 'installed'}})
    return state


_STATE = initial_state()


def reload_state():
    with _LOCK:
        _STATE.clear()
        _STATE.update(initial_state())


def status():
    with _LOCK:
        result = dict(_STATE)
    binding = read_json(DATA_DIR / 'binding.json', {})
    result['boundUdid'] = binding.get('udid')
    result['peerName'] = binding.get('peerName')
    result['wifiBound'] = bool(binding.get('udid'))
    result['onboardingRequired'] = (binding.get('onboardingComplete', True) is False) if binding.get('udid') else not bool(wifi_paired_udids())
    return result


def _set(**values):
    with _LOCK:
        _STATE.update(values)
        write_json(DATA_DIR / 'setup.json', {k: v for k, v in _STATE.items() if k in {'step', 'udid', 'usbReady', 'revealed', 'developerEnabled', 'installed'}})


def require_usb(udid):
    if not isinstance(udid, str) or not any(d['udid'] == udid and d['connection'] == 'USB' for d in list_devices()):
        raise ValueError('Select your iPhone while it is connected by USB.')


def start(action, udid, package=None):
    if action not in {'start', 'developer', 'check', 'install', 'bind'}:
        raise ValueError('Unknown setup action.')
    require_usb(udid)
    from handset.signing import status as signing_status
    if signing_status()['phase'] in {'working', 'prompt'}:
        raise ValueError('Finish or cancel signing before another setup step.')
    if action == 'bind':
        from handset.bluetooth import bluetooth
        if bluetooth.status()['phase'] in {'connecting', 'connected'}:
            raise ValueError('Disconnect Bluetooth before binding a new USB link.')
    with _LOCK:
        if _STATE['phase'] == 'working':
            raise ValueError('A setup step is already running.')
        if _STATE.get('udid') != udid:
            for key in ('usbReady', 'revealed', 'developerEnabled', 'installed'):
                _STATE.pop(key, None)
        _STATE.update(phase='working', step=action, udid=udid, error=None,
                      note='Working with your iPhone. Keep it unlocked and connected.')
        threading.Thread(target=_run, args=(action, udid, package), daemon=True, name='pane-setup').start()
    return status()


def _run(action, udid, package):
    try:
        asyncio.run(asyncio.wait_for(_perform(action, udid, package), timeout=300))
    except Exception as error:
        message = str(error) or type(error).__name__
        _set(phase='error', error=message, note=message)
    finally:
        if package:
            package.unlink(missing_ok=True)


def inspect_ipa(path, require_signed=True):
    with zipfile.ZipFile(path) as archive:
        infos = [i for i in archive.infolist() if i.filename.startswith('Payload/')
                 and i.filename.count('/') == 2 and i.filename.endswith('.app/Info.plist')]
        if len(infos) != 1 or infos[0].file_size > 1024 * 1024:
            raise ValueError('Select the Pane companion IPA.')
        info = plistlib.loads(archive.read(infos[0]))
        if info.get('PaneProtocolVersion') != 1 or info.get('CFBundleExecutable') != 'PaneFiles':
            raise ValueError('This IPA is not the Pane companion.')
        root = infos[0].filename.rsplit('/', 1)[0]
        if require_signed and (root + '/embedded.mobileprovision' not in archive.namelist() or root + '/_CodeSignature/CodeResources' not in archive.namelist()):
            raise ValueError('This IPA is unsigned. Sign/install it with AltStore Classic, or export a development-signed IPA for this iPhone in Xcode.')
        return info['CFBundleIdentifier']


async def _companion(lockdown):
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    async with InstallationProxyService(lockdown) as installer:
        apps = await installer.browse(options={'ApplicationType': 'User'})
    matches = [app for app in apps if app.get('CFBundleExecutable') == 'PaneFiles'
               and app.get('CFBundleDisplayName') == 'Pane']
    if len(matches) != 1:
        raise ValueError('Install one copy of Pane, then check again. If using AltStore, finish signing and installation there first.')
    return matches[0]['CFBundleIdentifier']


async def _perform(action, udid, package):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.amfi import AmfiService
    from pymobiledevice3.services.house_arrest import HouseArrestService
    from pymobiledevice3.services.installation_proxy import InstallationProxyService

    lockdown = await create_using_usbmux(serial=udid, connection_type='USB')
    try:
        _set(usbReady=True)
        if action == 'start':
            await AmfiService(lockdown).reveal_developer_mode_option_in_ui()
            _set(phase='waiting', step='developer', revealed=True, note='Enable Developer Mode in iPhone Settings → Privacy & Security, restart the iPhone and confirm Turn On. Reconnect USB to continue.')
            return
        if action == 'install':
            if package is None:
                raise ValueError('Choose a signed Pane IPA first.')
            inspect_ipa(package)
            async with InstallationProxyService(lockdown) as installer:
                await installer.install_from_local(package, handler=lambda progress: _set(note=f'Installing Pane: {progress}%'))
            from handset.companion_update import invalidate
            invalidate(udid)
            already_bound = status().get('boundUdid') == udid
            _set(phase='waiting', step='bluetooth' if already_bound else 'developer', installed=True, note='Pane updated. Open it on your iPhone; your existing pairing is preserved.' if already_bound else 'Pane installed. Enable Developer Mode and trust your developer profile on the iPhone if prompted. Restart and confirm, then check again.')
            return
        enabled = await lockdown.get_developer_mode_status()
        if not enabled:
            _set(developerEnabled=False)
            if action in {'developer', 'check'}:
                # Retry the reveal here as well as during initial USB setup: a
                # phone can reach this step with the toggle still hidden.
                await AmfiService(lockdown).reveal_developer_mode_option_in_ui()
                _set(step='developer', revealed=True)
                raise ValueError('Developer Mode is not enabled yet. Pane asked the iPhone to reveal it in Settings → Privacy & Security. Open Settings again, switch it on, restart the iPhone and confirm Turn On. Device restrictions may prevent it from appearing.')
            raise ValueError('Developer Mode is not enabled yet. Switch it on, restart the iPhone and confirm Turn On.')
        if action == 'developer':
            _set(phase='ready', step='install', developerEnabled=True, note='Developer Mode is enabled. Sign and install Pane next.')
            return
        bundle = await _companion(lockdown)
        _set(installed=True, developerEnabled=True)
        if action == 'check':
            _set(phase='ready', step='bind', note='Developer Mode and Pane are ready. Bind USB and Wi-Fi next.')
            return
        # Wi-Fi pairing must succeed before saving a completed binding.
        wifi = await asyncio.to_thread(pair_for_wifi, udid)
        if not wifi.get('ok'):
            raise ValueError(wifi.get('error') or 'Wi-Fi pairing was not confirmed. Reconnect and retry.')
        binding = {'version': 1, 'onboardingComplete': False, 'udid': udid, 'bundle': bundle, 'token': secrets.token_hex(32),
                   'peerName': 'Pane-' + uuid.uuid4().hex[:4], 'service': str(uuid.uuid4())}
        afc = await HouseArrestService.create(lockdown, bundle, documents_only=True)
        try:
            prefix = '/Documents' if await afc.isdir('/Documents') else ''
            await afc.set_file_contents(prefix + '/pane-pairing.json', json.dumps(binding).encode())
        finally:
            await afc.close()
        write_json(DATA_DIR / 'binding.json', binding)
        _set(phase='waiting', step='bluetooth', note='USB and Wi-Fi paired. Open Pane on the iPhone, allow Bluetooth and leave the app open. Pane imports the USB link automatically.')
    finally:
        await lockdown.close()
