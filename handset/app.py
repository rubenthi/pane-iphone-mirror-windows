"""Native WebView2 phone window with a browser fallback for missing runtimes."""

from __future__ import annotations

import logging
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import json
import urllib.request
from pathlib import Path

from handset.server import HOST, PORT, Handler, SingleServer
from handset.edition import APP_NAME, DEVELOPMENT
from handset import updater, notifications, setup
from handset.screen import stop_screen
from handset.state import DATA_DIR, RESET_REQUEST, can_reset_development, prepare_state, isolate_device_state
from handset.bluetooth import bluetooth

URL = f"http://{HOST}:{PORT}/"
WINDOWS_APP_ID = 'Pane.Desktop.Development' if DEVELOPMENT else 'Pane.Desktop'
APP_ICON = Path(__file__).resolve().parents[1] / 'packaging' / 'pane.ico'


def _set_windows_identity():
    if os.name != 'nt':
        return
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    result = shell.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    if result < 0:
        raise OSError(f'Windows could not set the Pane application identity ({result:#x}).')

BROWSERS = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
)


def _setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(DATA_DIR / "pane.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # A windowed exe has no console, so print() and tracebacks would be lost.
    if sys.stdout is None or sys.stderr is None:
        log = open(DATA_DIR / "pane.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def _already_running() -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((HOST, PORT)) == 0


def _open_window() -> subprocess.Popen | None:
    for browser in BROWSERS:
        if browser.is_file():
            # A dedicated profile makes this its own process, so we can tell
            # when the user closes the window.
            return subprocess.Popen(
                [
                    str(browser),
                    f"--app={URL}",
                    f"--user-data-dir={DATA_DIR / 'window'}",
                    "--window-size=1100,860",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]
            )
    webbrowser.open(URL)
    return None


def _clear_profile():
    notifications.stop_for_reset()
    deadline = time.monotonic() + 20
    while True:
        try:
            prepare_state(force=True)
            break
        except PermissionError:
            # WebView2 can briefly retain file handles after the old window closes.
            if time.monotonic() >= deadline:
                raise
            time.sleep(.25)
    setup.reload_state()


def main() -> None:
    if _already_running():
        try:
            with urllib.request.urlopen(URL + 'api/auth', timeout=3) as response:
                token = json.load(response)['token']
            request = urllib.request.Request(URL + 'api/window', data=b'{"action":"focus"}', headers={'Content-Type':'application/json', 'X-Pane-Token':token})
            urllib.request.urlopen(request, timeout=3).close()
        except Exception:
            _open_window()
        return

    # Reserve the instance's port before changing any persistent state.
    server = SingleServer((HOST, PORT), Handler)
    marker = DATA_DIR / RESET_REQUEST
    pending_reset = can_reset_development() and marker.is_file()
    if pending_reset or '--reset' in sys.argv:
        try:
            _clear_profile()
            if pending_reset:
                marker.unlink()
        except OSError as error:
            server.server_close()
            if pending_reset and os.name == 'nt':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, f'Could not finish the reset. Reopen Pane (Development) to retry.\n\n{error}',
                                                 APP_NAME, 0x10)
            raise
    else:
        prepare_state()
    isolate_device_state()
    _setup_logging()
    notifications.session(desktop=True, mirroring=False)
    bluetooth.start_auto()

    fallback = None
    reset_lock = threading.Lock()

    def request_reset():
        from handset.window import shell
        with reset_lock:
            if not can_reset_development():
                raise ValueError('Reset requires the standard development profile.')
            if marker.exists():
                return
            marker.touch(exist_ok=False)
            try:
                if fallback is not None:
                    fallback.terminate()
                else:
                    shell.command({'action': 'close'})
            except Exception:
                marker.unlink(missing_ok=True)
                raise

    if can_reset_development():
        server.request_development_reset = request_reset
    threading.Thread(target=server.serve_forever, name="pane-server", daemon=True).start()
    threading.Thread(target=updater.monitor, name="pane-update", daemon=True).start()
    logging.info("Pane listening on %s", URL)

    try:
        run_native_window()
    except Exception:
        logging.exception('Native WebView2 window unavailable; using browser fallback.')
        fallback = _open_window()
        if fallback is None:
            server.request_development_reset = None
            while True:
                time.sleep(3600)
        fallback.wait()
    server.shutdown()
    stop_screen()
    bluetooth.stop_auto()
    notifications.session(desktop=False, mirroring=False)
    updater.apply_on_exit()
    server.server_close()
    if can_reset_development() and marker.exists():
        frozen = getattr(sys, 'frozen', False)
        command = [sys.executable, '--development'] if frozen else [sys.executable, '-m', 'handset.app']
        restart_folder = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[1]
        subprocess.Popen(command, cwd=restart_folder,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), close_fds=True)
    os._exit(0)


def run_native_window():
    import webview
    from handset.window import shell
    _set_windows_identity()
    webview.settings['ALLOW_FILE_URLS'] = False
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    class NativeBridge:
        def window_command(self, payload):
            try:
                if not isinstance(payload, dict):
                    raise ValueError('Invalid window action.')
                return shell.command(payload)
            except (ValueError, OSError) as error:
                return {'error': str(error)}

    window = webview.create_window(APP_NAME, URL, width=388, height=760,
                                   frameless=True, easy_drag=False, resizable=False, shadow=False, transparent=True,
                                   background_color='#122337', text_select=True, js_api=NativeBridge())
    def shown():
        if shell.handle:
            return
        if not shell.attach(window):
            logging.error('Could not attach the native window region.')
    window.events.shown += shown
    webview.start(gui='edgechromium', private_mode=False, storage_path=str(DATA_DIR / 'webview'), icon=str(APP_ICON))


if __name__ == "__main__":
    main()
