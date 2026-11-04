"""Reconnect the selected paired iPhone to Windows' Bluetooth A2DP receiver."""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
from handset.audio_bridge import bridge


def choose_device(devices, preferred=None, name=None, address=None):
    def mac(value):
        return ''.join(c for c in str(value or '').lower() if c in '0123456789abcdef')
    if preferred:
        saved = next((d for d in devices if d['id'] == preferred), None)
        if saved and not (address and saved.get('address') and mac(address) != mac(saved['address'])):
            return preferred
        if not address: return None
    matches = [d for d in devices if address and mac(d.get('address')) == mac(address)]
    if not matches and name:
        matches = [d for d in devices if d.get('name', '').casefold() == name.casefold()
                   and not (address and d.get('address') and mac(d['address']) != mac(address))]
    return matches[0]['id'] if len(matches) == 1 else None


class AudioManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._config = {'enabled': True, 'phones': {}}
        self._state = {'phase': 'idle', 'note': 'Audio connects automatically after Bluetooth pairing and phone selection.', 'devices': []}
        self._active = None
        self._pair_prompted = False
        self._receiver = None
        self._retry_at = 0
        self._identity = {}
        self._path = Path(os.environ.get('PANE_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Pane'))) / 'audio.json'

    def start(self):
        try:
            data = json.loads(self._path.read_text())
            if isinstance(data.get('enabled'), bool) and isinstance(data.get('phones'), dict):
                self._config = data
        except (OSError, ValueError, TypeError): pass
        self._thread = threading.Thread(target=self._run, name='pane-audio', daemon=True)
        self._thread.start()

    def status(self):
        with self._lock:
            return {**self._state, 'enabled': self._config['enabled'], 'available': os.name == 'nt'}

    def _set(self, **values):
        with self._lock: self._state.update(values)

    def remember_identity(self, udid, values):
        with self._lock:
            self._identity[udid] = {key: values.get(key) for key in ('DeviceName', 'BluetoothAddress')}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._config), encoding='utf-8')
        temporary.replace(self._path)

    def command(self, payload):
        from handset.screen import screen_status
        action = payload.get('action')
        if not isinstance(action, str): raise ValueError('Invalid audio action.')
        if action == 'settings':
            if os.name != 'nt': raise ValueError('Bluetooth settings require Windows.')
            os.startfile('ms-settings:bluetooth')
        elif action == 'refresh':
            devices = bridge.command({'action': 'devices'})['devices']
            self._set(devices=devices)
        elif action in {'select', 'enable'}:
            with self._lock:
                if action == 'enable':
                    enabled = payload.get('enabled')
                    if type(enabled) is not bool: raise ValueError('Invalid audio preference.')
                    self._config['enabled'] = enabled
                else:
                    udid = screen_status().get('udid')
                    device = payload.get('device')
                    if not udid: raise ValueError('Connect the iPhone screen first, then select its paired audio device.')
                    if not isinstance(device, str) or device not in {d['id'] for d in self._state['devices']}:
                        raise ValueError('Refresh and choose a paired device.')
                    self._config['phones'][udid] = device
                    self._config['enabled'] = True
                self._save()
        elif action == 'retry': self._pair_prompted = False
        else: raise ValueError('Unknown audio action.')
        self._retry_at = 0
        self._wake.set()
        return self.status()

    def _tick(self, screen):
        with self._lock:
            enabled = self._config['enabled']
            preferred = self._config['phones'].get(screen.get('udid'))
        udid = screen.get('udid')
        session_ready = (screen.get('phase') in {'running', 'audio-only'} or
                         (screen.get('phase') == 'starting' and screen.get('audioReady')))
        if not enabled or not session_ready:
            if self._receiver or self._active:
                bridge.command({'action': 'audio.disconnect'})
            self._active = self._receiver = None
            self._pair_prompted = False
            self._retry_at = 0
            self._set(phase='idle' if enabled else 'off', note='Waiting for iPhone mirroring.' if enabled else 'Automatic laptop audio is off.')
            return
        if os.name != 'nt':
            self._set(phase='unavailable', note='Bluetooth audio reception requires Windows 10 2004+ or Windows 11.')
            return
        if self._receiver and (self._receiver[0] != udid or (preferred and preferred != self._receiver[1])):
            bridge.command({'action': 'audio.disconnect'}); self._active = self._receiver = None
            self._retry_at = 0
            self._set(phase='connecting', note='Connecting the selected iPhone audio…')
        if self._receiver or self._active:
            state = bridge.command({'action': 'status'})
            if state.get('state') == 'Opened':
                self._active = self._receiver
                self._set(phase='connected', note='Paired · audio connection open. Play media to check sound. If needed, choose this PC in the iPhone output picker.')
                return
            if self._active:
                self._active = None
                self._set(phase='connecting', note='Bluetooth audio disconnected. Retrying automatically…')
        if time.monotonic() < self._retry_at: return
        self._retry_at = time.monotonic() + 15
        self._set(phase='connecting', note='Connecting paired iPhone audio…')
        devices = bridge.command({'action': 'devices'})['devices']
        self._set(devices=devices)
        if udid not in self._identity:
            try:
                from handset.device import read_handset
                self._identity[udid] = read_handset(udid).get('info', {})
            except Exception: self._identity[udid] = {}
        identity = self._identity[udid]
        device = choose_device(devices, preferred, identity.get('DeviceName'), identity.get('BluetoothAddress'))
        if not device:
            address = identity.get('BluetoothAddress')
            if not self._pair_prompted and (address or not devices):
                self._pair_prompted = True
                if address:
                    self._set(phase='pairing', note='Keep Settings > Bluetooth open on the iPhone. Confirm matching codes when Windows asks.')
                    result = bridge.command({'action':'audio.pair', 'address':address})
                    if result['paired']:
                        self._retry_at = 0
                    else:
                        os.startfile('ms-settings:bluetooth')
                    note = result['note']
                    if not result['paired']:
                        note += ' In Windows choose Add device → Bluetooth, select your iPhone and confirm the code on both screens.'
                    self._set(phase='setup', note=note)
                    return
                os.startfile('ms-settings:bluetooth')
            self._set(phase='setup', note='Choose Add device in Windows Bluetooth settings, approve matching codes, then retry audio.')
            return
        self._set(phase='paired', note='Paired. Opening the Windows Bluetooth media receiver…')
        result = bridge.command({'action': 'audio.connect', 'device': device})
        self._receiver = (udid, device)
        # StartAsync enabled this exact endpoint. Remember it even when the
        # phone has not started sending media or OpenAsync asks us to wait.
        with self._lock:
            if preferred != device and self._config['phones'].get(udid) == preferred:
                self._config['phones'][udid] = device
                self._save()
        if result.get('state') != 'Opened':
            self._retry_at = time.monotonic() + 15
            self._set(phase='listening', note=result.get('note', 'Paired. Receiver ready. Waiting for the iPhone to open media audio.'))
            return
        self._active = (udid, device)
        self._set(phase='connected', note='Paired · audio connection open. Play media to check sound. If needed, choose this PC in the iPhone output picker.')

    def _run(self):
        from handset.screen import screen_status
        while not self._stop.is_set():
            try: self._tick(screen_status())
            except Exception as error:
                self._set(phase='error', note=str(error))
                self._retry_at = time.monotonic() + 15
            self._wake.wait(2); self._wake.clear()

    def close(self):
        self._stop.set(); self._wake.set()
        if self._thread: self._thread.join(2)
        bridge.close()


manager = AudioManager()
