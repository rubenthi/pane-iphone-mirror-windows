"""Windows A2DP reception, independent of the video tunnel.

The pinned screen-stream decoder uses macOS AudioToolbox. Windows instead
owns Bluetooth decoding/playback; Pane keeps a native connection alive.
No microphone recording, clipboard monitoring, or audio transcoding.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


class LaptopAudio:
    def __init__(self):
        self._lock = threading.RLock()
        self._commands = threading.RLock()
        self._process = None
        self._devices = {}
        self._state = {'phase': 'idle', 'note': 'Pair the iPhone in Windows Bluetooth settings.'}

    @staticmethod
    def supported():
        return sys.platform == 'win32' and sys.getwindowsversion().build >= 19041

    def _args(self, mode):
        exe = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        return [str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                'Bypass', '-File', str(Path(__file__).with_name('audio.ps1')), '-Mode', mode]

    def status(self):
        with self._lock:
            return {**self._state, 'supported': self.supported(),
                    'devices': [{'id': key, 'name': value} for key, value in self._devices.items()]}

    def refresh(self):
        if not self.supported():
            return self._set(phase='unavailable', error='Laptop audio requires Windows 10 version 2004 or newer and Bluetooth.')
        with self._commands:
            result = subprocess.run(self._args('List'), capture_output=True, text=True,
                                    encoding='utf-8', timeout=20, creationflags=0x08000000)
            messages = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            data = messages[-1] if messages else {}
            if result.returncode or 'error' in data:
                raise ValueError(data.get('error', 'Windows Bluetooth device discovery failed.'))
            devices = data.get('devices', [])
            with self._lock:
                self._devices = {device['id']: device['name'] for device in devices}
            return self.status()

    def connect(self, device_id):
        if not self.supported():
            raise ValueError('Bluetooth audio reception is unavailable on this Windows version.')
        with self._commands:
            if not isinstance(device_id, str) or device_id not in self._devices:
                raise ValueError('Find paired devices and select your iPhone first.')
            self.stop()
            process = subprocess.Popen(self._args('Connect'), stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, encoding='utf-8', bufsize=1, creationflags=0x08000000)
            with self._lock:
                self._process = process
                self._state = {'phase': 'connecting', 'device': self._devices[device_id],
                               'note': 'Connecting Bluetooth audio…'}
            try:
                process.stdin.write(json.dumps({'id': device_id}) + '\n')
                process.stdin.flush()
            except OSError:
                self.stop()
                raise ValueError('Could not start the Windows audio helper.')
            threading.Thread(target=self._watch, args=(process,), daemon=True, name='pane-audio').start()
            return self.status()

    def _watch(self, process):
        def timeout():
            with self._lock:
                if self._process is process and self._state['phase'] == 'connecting':
                    self._state.update(phase='error', error='Bluetooth audio connection timed out.')
                    process.terminate()
        timer = threading.Timer(40, timeout)
        timer.daemon = True
        timer.start()
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if message.get('phase') not in ('connected', 'disconnected', 'error'):
                    continue
                timer.cancel()
                with self._lock:
                    if self._process is not process:
                        return
                    self._state.update(message)
            process.wait()
            with self._lock:
                if self._process is process:
                    self._process = None
                    if self._state['phase'] not in ('error', 'disconnected'):
                        self._state.update(phase='disconnected', note='Bluetooth audio helper stopped.')
        finally:
            timer.cancel()
            process.stdout.close()
            process.stdin.close()

    def probe(self):
        # Requested by the UI only while connecting/connected. No background scan.
        with self._commands:
            with self._lock:
                process = self._process
            if process and process.poll() is None:
                try:
                    process.stdin.write('status\n')
                    process.stdin.flush()
                except (OSError, ValueError):
                    pass
            return self.status()

    def stop(self):
        with self._commands:
            with self._lock:
                process, self._process = self._process, None
                self._state = {'phase': 'idle', 'note': 'Laptop audio disconnected.'}
            if process and process.poll() is None:
                try:
                    process.stdin.write('stop\n')
                    process.stdin.flush()
                    process.wait(timeout=3)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            return self.status()

    def _set(self, **values):
        with self._lock:
            self._state.update(values)
            return self.status()


audio = LaptopAudio()
atexit.register(audio.stop)
