"""Own the Windows Bluetooth helper. No network listener or arbitrary commands."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading

ACTIONS = frozenset({'devices', 'audio.connect', 'audio.disconnect', 'audio.pair', 'notification.devices', 'notification.probe', 'status'})
def validate(payload):
    action = payload.get('action')
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError('Unknown audio action.')
    result = {'action': action}
    if action == 'audio.pair':
        address = payload.get('address')
        if not isinstance(address, str) or not re.fullmatch(r'(?:[a-fA-F0-9]{2}:){5}[a-fA-F0-9]{2}', address):
            raise ValueError('Invalid Bluetooth address.')
        result['address'] = address
    if action in {'audio.connect', 'notification.probe'}:
        device = payload.get('device')
        if not isinstance(device, str) or not device or len(device) > 4096 or '\0' in device:
            raise ValueError('Select a paired audio device.')
        result['device'] = device
    return result


class AudioBridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._responses = None

    @staticmethod
    def executable() -> Path:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        return root / "native" / "Pane.Audio.exe"

    def status(self) -> dict:
        with self._lock:
            if os.name != "nt":
                return {"available": False, "error": "Bluetooth features require Windows 10 2004+ or Windows 11."}
            if self._process is None:
                exists = self.executable().is_file()
                return {"available": exists, "started": False, "error": "" if exists else "Build the native Bluetooth helper with packaging/build-audio.ps1 first."}
            try:
                return self._request({"action": "status"})
            except (ValueError, OSError, RuntimeError) as error:
                return {"available": False, "error": str(error)}

    def command(self, payload: dict) -> dict:
        command = validate(payload)
        with self._lock:
            if os.name != "nt":
                raise RuntimeError("Bluetooth features require Windows 10 2004+ or Windows 11.")
            if self._process is None:
                self._start()
            return self._request(command)

    def _start(self):
        exe = self.executable()
        if not exe.is_file():
            raise RuntimeError("Native Bluetooth helper missing. Run packaging/build-audio.ps1.")
        try:
            self._process = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            if getattr(error, 'winerror', None) == 4551:
                raise RuntimeError("Windows Application Control blocked the Bluetooth receiver. "
                                   "Your administrator can review Pane.Audio.exe in the Code Integrity log.") from error
            raise
        responses = self._responses = queue.Queue(maxsize=2)
        process = self._process

        def read():
            try:
                while line := process.stdout.readline(8388609):
                    if len(line) > 8388608:
                        raise RuntimeError("Bluetooth helper response exceeded the size limit.")
                    responses.put_nowait(json.loads(line))
            except Exception:
                pass
            finally:
                try:
                    responses.put_nowait(None)
                except queue.Full:
                    pass
        threading.Thread(target=read, name="pane-bluetooth-reader", daemon=True).start()

    def _request(self, command):
        try:
            if self._process.poll() is not None:
                raise RuntimeError("Bluetooth helper stopped. Refresh devices to retry.")
            self._process.stdin.write(json.dumps(command) + "\n")
            self._process.stdin.flush()
            response = self._responses.get(timeout=90 if command['action'] == 'audio.pair' else 40)
            if not isinstance(response, dict):
                raise RuntimeError("Bluetooth helper disconnected.")
            if not response.get("ok"):
                raise ValueError(response.get("error", "Bluetooth operation failed."))
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Invalid Bluetooth helper response.")
            return result
        except queue.Empty as error:
            self._stop()
            raise RuntimeError("Bluetooth operation timed out; connections were closed. Unlock the phone and retry.") from error
        except (OSError, RuntimeError):
            self._stop()
            raise

    def _stop(self):
        process, self._process = self._process, None
        self._responses = None
        if process is not None:
            try:
                process.stdin.close()  # EOF makes the helper dispose all Bluetooth sessions.
                process.wait(timeout=4)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=4)
            finally:
                process.stdout.close()

    def close(self):
        with self._lock:
            self._stop()


bridge = AudioBridge()
atexit.register(bridge.close)
