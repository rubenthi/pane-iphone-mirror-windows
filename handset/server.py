"""Local device window. Binds to loopback only."""

from __future__ import annotations

import http.client
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from handset.device import read_handset, snapshot
from handset.mux import MuxError
from handset.screen import restart_screen, screen_status, start_screen, stop_screen
from handset.security import ACCESS_TOKEN, MAX_REQUEST_BODY, request_allowed
from handset.wifi import pair_for_wifi, wifi_paired_udids
from handset import updater, companion_update
from handset.window import shell
from handset import setup, signing, notifications
from handset.bluetooth import bluetooth
from handset.transfers import store
from handset.state import prepare_state, isolate_device_state, can_reset_development
from handset.edition import APP_NAME, PORT, STREAM_PORT

ROOT = Path(__file__).resolve().parent / "web"
HOST = "127.0.0.1"
MIRROR_PREFIX = "/mirror"
STREAM_HOST = "127.0.0.1"
_HOP_BY_HOP = frozenset(
    {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade"}
)
_CLIENT_GONE = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)


class Handler(BaseHTTPRequestHandler):
    def _authorize(self, *, token_required: bool) -> bool:
        if request_allowed(self.headers, self.server.server_port, token_required=token_required):
            return True
        self._json({"error": "Request denied."}, status=403)
        return False

    def _request_body_length(self) -> int | None:
        if self.headers.get("Transfer-Encoding"):
            self._json({"error": "Chunked request bodies are not supported."}, status=400)
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json({"error": "Invalid Content-Length."}, status=400)
            return None
        if length < 0 or length > MAX_REQUEST_BODY:
            self._json({"error": "Request body exceeds the size limit."}, status=413)
            return None
        return length

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        protected = path.startswith("/api/") and path != "/api/auth"
        protected = protected or path == MIRROR_PREFIX or path.startswith(f"{MIRROR_PREFIX}/")
        if not self._authorize(token_required=protected):
            return
        if path == "/api/auth":
            self._json({"token": ACCESS_TOKEN})
            return
        if path == MIRROR_PREFIX or path.startswith(f"{MIRROR_PREFIX}/"):
            self._proxy_mirror("GET", 0)
            return
        if path == "/api/status":
            payload = snapshot()
            payload["screen"] = screen_status()
            payload["wifi"] = {"paired": wifi_paired_udids()}
            payload["update"] = updater.status()
            self._json(payload)
            return
        if path == "/api/screen":
            self._json({**screen_status(), "update": updater.status(), "companion": notifications.status()})
            return
        if path == '/api/preferences':
            self._json({'preferences': notifications.preferences(), 'companion': notifications.status()})
            return
        if path == '/api/bluetooth/devices':
            self._json(notifications.devices())
            return
        if path == '/api/window':
            self._json(shell.status())
            return
        if path == '/api/signing':
            self._json(signing.status())
            return
        if path == '/api/companion-update':
            self._json(companion_update.check())
            return
        if path == '/api/setup':
            self._json(setup.status())
            return
        if path == '/api/uploads':
            self._json({**store().status(), 'bluetooth': bluetooth.status()})
            return
        if path.startswith("/api/devices/"):
            udid = unquote(path.removeprefix("/api/devices/")).strip("/")
            if not udid or "/" in udid:
                self._json({"error": "Missing device id."}, status=400)
                return
            self._device(udid)
            return
        self._file(path)

    def do_POST(self) -> None:
        if not self._authorize(token_required=True):
            return
        length = self._request_body_length()
        if length is None:
            return
        path = urlparse(self.path).path
        if path == MIRROR_PREFIX or path.startswith(f"{MIRROR_PREFIX}/"):
            self._proxy_mirror("POST", length)
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"error": "Invalid JSON body."}, status=400)
            return
        if not isinstance(payload, dict):
            self._json({"error": "Expected a JSON object."}, status=400)
            return
        if path == '/api/development/reset':
            reset = self.server.request_development_reset
            if not reset or not can_reset_development():
                self._json({'error': 'Reset is unavailable in this instance.'}, status=404)
            elif payload.get('confirm') is not True or len(payload) != 1:
                self._json({'error': 'Confirm the development reset first.'}, status=400)
            elif setup.status()['phase'] == 'working' or signing.status()['phase'] in {'working', 'prompt'}:
                self._json({'error': 'Finish the current setup or signing operation before resetting.'}, status=409)
            else:
                try:
                    reset()
                except (OSError, ValueError) as error:
                    self._json({'error': str(error)}, status=409)
                    return
                self._json({'restarting': True})
            return
        if path == '/api/window':
            try:
                self._json(shell.command(payload))
            except (ValueError, OSError) as error:
                self._json({'error': str(error)}, status=400)
            return
        if path in ('/api/preferences', '/api/bluetooth/settings'):
            try:
                if path == '/api/preferences':
                    self._json(notifications.save(payload))
                else:
                    notifications.open_bluetooth_settings()
                    self._json({'ok': True})
            except (ValueError, OSError) as error:
                self._json({'error': str(error)}, status=400)
            return
        if "udid" in payload and payload["udid"] is not None and not isinstance(payload["udid"], str):
            self._json({"error": "Invalid device id."}, status=400)
            return
        udid = payload.get("udid") if isinstance(payload.get("udid"), str) else None
        if path.startswith('/api/signing/') or path.startswith('/api/setup/') or path.startswith('/api/uploads/') or path.startswith('/api/bluetooth/'):
            try:
                self._json(self._companion_action(path, payload, udid))
            except (ValueError, OSError, MuxError) as error:
                self._json({'error': str(error)}, status=400)
            return
        if path == "/api/screen/stop":
            stop_screen()
            self._json(screen_status())
            return
        if path == "/api/screen/restart":
            self._json(restart_screen(udid))
            return
        if path == "/api/wifi/pair":
            if not udid:
                self._json({"ok": False, "error": "Plug in the iPhone first."}, status=400)
                return
            self._json(pair_for_wifi(udid))
            return
        if path != "/api/screen":
            self._json({"error": "Unknown action."}, status=404)
            return
        transport = payload.get("transport", "auto")
        if not isinstance(transport, str) or transport not in {"auto", "usb", "wifi"}:
            self._json({"error": "Invalid transport."}, status=400)
            return
        self._json(start_screen(udid, transport))

    def _companion_action(self, path, payload, udid):
        if path == '/api/signing/answer':
            return signing.answer(payload.get('promptId'), payload.get('value'), payload.get('confirmRevocation', False))
        if path == '/api/signing/cancel':
            return signing.cancel()
        if path == '/api/signing/start':
            setup.require_usb(udid)
            item = store().finish(payload.get('id'), 'ipa') if payload.get('id') else {'path': signing.stage_bundled()}
            try:
                return signing.start(udid, item['path'], payload.get('email'), payload.get('password'))
            except Exception:
                item['path'].unlink(missing_ok=True)
                raise
        if path.startswith('/api/setup/'):
            action = path.rsplit('/', 1)[-1]
            if action == 'install':
                setup.require_usb(udid)
                item = store().finish(payload.get('id'), 'ipa')
                try:
                    return setup.start(action, udid, item['path'])
                except Exception:
                    item['path'].unlink(missing_ok=True)
                    raise
            return setup.start(action, udid)
        if path == '/api/bluetooth/connect':
            return bluetooth.connect()
        if path == '/api/bluetooth/disconnect':
            return bluetooth.disconnect()
        if path == '/api/uploads/start':
            return store().begin(payload.get('name'), payload.get('size'), payload.get('kind', 'file'))
        if path == '/api/uploads/chunk':
            return store().append(payload.get('id'), payload.get('offset'), payload.get('data'))
        if path == '/api/uploads/finish':
            item = store().finish(payload.get('id'), 'file')
            return {'ok': True, 'id': item['id']}
        if path in {'/api/uploads/pause', '/api/uploads/resume'}:
            return store().control(payload.get('id'), path.rsplit('/', 1)[-1])
        if path == '/api/uploads/cancel':
            return store().cancel(payload.get('id'))
        raise ValueError('Unknown action.')

    def log_message(self, fmt: str, *args) -> None:
        return

    def _device(self, udid: str) -> None:
        try:
            self._json(read_handset(udid))
        except MuxError as error:
            self._json({"udid": udid, "paired": False, "error": str(error)}, status=409)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _mirror_upstream_path(self) -> str:
        path = unquote(urlparse(self.path).path)
        upstream = path.removeprefix(MIRROR_PREFIX) or "/"
        if not upstream.startswith("/"):
            upstream = f"/{upstream}"
        query = urlparse(self.path).query
        return upstream + (f"?{query}" if query else "")

    def _write_client(self, data: bytes) -> bool:
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except _CLIENT_GONE:
            return False
        return True

    def _proxy_mirror_stream(self, method: str, target: str) -> None:
        """Relay the live body de-chunked; this server speaks HTTP/1.0, so the
        response is delimited by closing the connection."""
        conn = http.client.HTTPConnection(STREAM_HOST, STREAM_PORT, timeout=600)
        started = False
        self.close_connection = True
        try:
            conn.request(method, target, headers={"Connection": "close", "Authorization": upstream_authorization()})
            response = conn.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() in _HOP_BY_HOP or key.lower() in {"transfer-encoding", "content-length"}:
                    continue
                self.send_header(key, value)
            self.end_headers()
            started = True
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                if not self._write_client(chunk):
                    return
        except (OSError, http.client.HTTPException) as error:
            if not started:
                self._json({"error": f"Screen stream is not running ({error})."}, status=503)
        finally:
            conn.close()

    def _proxy_mirror(self, method: str, length: int) -> None:
        target = self._mirror_upstream_path()
        upstream_path = target.split("?", 1)[0]
        allowed = {'GET': {'/codec', '/stream.bin', '/stats'},
                   'POST': {'/touch', '/key', '/button', '/restart', '/pli'}}
        if upstream_path not in allowed.get(method, set()):
            self._json({'error': 'Unknown screen action.'}, status=404)
            return
        is_live_stream = method == "GET" and upstream_path.endswith(".bin")
        if is_live_stream:
            self._proxy_mirror_stream(method, target)
            return

        body = self.rfile.read(length) if length and method in {"POST", "PUT"} else None

        headers: dict[str, str] = {"Authorization": upstream_authorization()}
        for name in ("Content-Type", "Accept"):
            value = self.headers.get(name)
            if value:
                headers[name] = value

        conn = http.client.HTTPConnection(STREAM_HOST, STREAM_PORT, timeout=120)
        started = False
        try:
            conn.request(method, target, body=body, headers=headers)
            response = conn.getresponse()
            payload = response.read()
            self.send_response(response.status)
            started = True
            for key, value in response.getheaders():
                if key.lower() in _HOP_BY_HOP or key.lower() in {"transfer-encoding", "content-length"}:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if payload:
                self._write_client(payload)
        except (OSError, http.client.HTTPException) as error:
            if not started:
                self._json({"error": f"Screen stream is not running ({error})."}, status=503)
        finally:
            conn.close()

    def _file(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        root = ROOT.resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._json({"error": "Not found."}, status=404)
            return
        if not target.is_file():
            self._json({"error": "Not found."}, status=404)
            return
        kind = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".woff2": "font/woff2",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        if target == root / "index.html":
            body = body.replace(b"{{pane_name}}", APP_NAME.encode())
            button = b'<button type="button" class="text-button" data-development-reset>Reset development app</button>'
            body = body.replace(b'<!-- development-reset -->', button if self.server.request_development_reset and can_reset_development() else b'')
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class SingleServer(ThreadingHTTPServer):
    request_development_reset = None
    # On Windows, address reuse lets a second copy bind the same port and steal requests.
    allow_reuse_address = False


def upstream_authorization():
    return 'Basic ' + base64.b64encode(f'pane:{ACCESS_TOKEN}'.encode()).decode()


def main() -> None:
    prepare_state()
    isolate_device_state()
    server = SingleServer((HOST, PORT), Handler)
    print(f"Handset listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
