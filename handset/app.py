"""Native WebView2 phone window with a browser fallback for missing runtimes."""

from __future__ import annotations

import logging
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
from handset import updater
from handset.screen import stop_screen

PORT = int(os.environ.get("PANE_PORT", PORT))
URL = f"http://{HOST}:{PORT}/"
DATA_DIR = Path(os.environ.get('PANE_DATA_DIR', str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pane")))

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


def main() -> None:
    _setup_logging()
    if _already_running():
        try:
            with urllib.request.urlopen(URL + 'api/auth', timeout=3) as response:
                token = json.load(response)['token']
            request = urllib.request.Request(URL + 'api/window', data=b'{"action":"focus"}', headers={'Content-Type':'application/json', 'X-Pane-Token':token})
            urllib.request.urlopen(request, timeout=3).close()
        except Exception:
            _open_window()
        return

    server = SingleServer((HOST, PORT), Handler)
    threading.Thread(target=server.serve_forever, name="pane-server", daemon=True).start()
    threading.Thread(target=updater.check, name="pane-update", daemon=True).start()
    logging.info("Pane listening on %s", URL)

    try:
        run_native_window()
    except Exception:
        logging.exception('Native WebView2 window unavailable; using browser fallback.')
        window = _open_window()
        if window is None:
            while True:
                time.sleep(3600)
        window.wait()
    server.shutdown()
    server.server_close()
    stop_screen()
    from handset.bluetooth import bridge
    bridge.close()
    updater.apply_on_exit()
    os._exit(0)


def run_native_window():
    import webview
    from handset.window import shell
    webview.settings['ALLOW_FILE_URLS'] = False
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    window = webview.create_window('Pane — iPhone', URL, width=388, height=760,
                                   frameless=True, easy_drag=False, resizable=False,
                                   background_color='#090c0d', text_select=True)
    def shown():
        if not shell.attach(os.getpid()):
            logging.error('Could not attach the native window region.')
    window.events.shown += shown
    webview.start(gui='edgechromium', private_mode=False, storage_path=str(DATA_DIR / 'webview'))


if __name__ == "__main__":
    main()
