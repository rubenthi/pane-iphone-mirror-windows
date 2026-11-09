import asyncio
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import plistlib
import socketserver
import struct
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from handset import mux, screen, updater
from handset.security import ACCESS_TOKEN
import test_server_security


class ApiReliabilityTests(test_server_security.ServerSecurityTests):
    def test_usb_disconnect_and_reconnect_use_fresh_routing_records(self):
        records = []
        def route(connection, routing_id):
            return {'MessageType': 'Attached', 'DeviceID': routing_id,
                    'Properties': {'SerialNumber': 'fixture-phone', 'ConnectionType': connection}}

        class AppleService(socketserver.StreamRequestHandler):
            def handle(self):
                size, version, kind, tag = struct.unpack('<4I', self.rfile.read(16))
                request = plistlib.loads(self.rfile.read(size - 16))
                if request['MessageType'] != 'ListDevices':
                    raise AssertionError('Unexpected Apple service request')
                body = plistlib.dumps({'DeviceList': records.copy()})
                self.wfile.write(struct.pack('<4I', len(body) + 16, version, kind, tag) + body)

        starts = []
        async def display(phone, transport):
            starts.append((phone, transport))
            if len(starts) == 1:
                raise ConnectionError('Synthetic cable removal')
            await asyncio.Event().wait()

        def command(path):
            status, _, body = self.request('POST', path, {'X-Pane-Token': ACCESS_TOKEN},
                                          b'{"udid":"fixture-phone","transport":"usb"}')
            self.assertEqual(status, 200)
            return json.loads(body)

        with socketserver.TCPServer(('127.0.0.1', 0), AppleService) as apple:
            thread = threading.Thread(target=apple.serve_forever, daemon=True)
            thread.start()
            try:
                with (patch.object(screen, 'list_devices', lambda: mux.list_devices(apple.server_address)),
                      patch.object(screen, 'wifi_paired_udids', return_value=[]),
                      patch.object(screen, 'developer_mode_enabled', return_value=True),
                      patch.object(screen, '_serve', side_effect=display), patch('handset.notifications.session')):
                    records[:] = [route('USB', 7)]
                    command('/api/screen')
                    screen._WORKER.join(2)
                    self.assertEqual(screen.screen_status()['phase'], 'error')
                    records[:] = [route('Network', 8)]
                    self.assertIn('not on the cable', command('/api/screen')['error'])
                    records.append(route('USB', 27))
                    self.assertEqual(command('/api/screen')['phase'], 'starting')
                    self.assertEqual(command('/api/screen/stop')['phase'], 'idle')
                    self.assertEqual(starts, [('fixture-phone', 'usb')] * 2)
            finally:
                screen.stop_screen()
                apple.shutdown()
                thread.join(2)

    def test_volume_control_remains_available(self):
        received = []
        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self, *args): pass
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever); thread.start()
        try:
            with patch('handset.server.STREAM_PORT', upstream.server_port):
                body = b'{"name":"volume-up","state":"press"}'
                status, _, _ = self.request('POST', '/mirror/button', {'X-Pane-Token':ACCESS_TOKEN}, body)
                self.assertEqual(status, 200)
                self.assertEqual(received, [('/button', body)])
        finally:
            upstream.shutdown(); upstream.server_close(); thread.join()

    def test_invalid_requests_never_start_device(self):
        with patch('handset.server.start_screen') as start:
            for body in (b'{', b'\xff', b'[]', b'null', b'{"transport": []}', b'{"udid": 3}'):
                status, _, _ = self.request('POST', '/api/screen', {'X-Pane-Token': ACCESS_TOKEN}, body)
                self.assertEqual(status, 400, body)
            start.assert_not_called()

    def test_proxy_dechunks_and_reframes_body(self):
        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                self.wfile.write(b'5\r\nhello\r\n0\r\n\r\n')
            def log_message(self, *args): pass
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever)
        thread.start()
        try:
            with patch('handset.server.STREAM_PORT', upstream.server_port):
                for path in ('/mirror/codec', '/mirror/stream.bin'):
                    status, headers, body = self.request('GET', path, {'X-Pane-Token': ACCESS_TOKEN})
                    self.assertEqual((status, body), (200, b'hello'))
                    self.assertNotIn('Transfer-Encoding', headers)
                    if not path.endswith('.bin'):
                        self.assertEqual(headers['Content-Length'], '5')
        finally:
            upstream.shutdown(); upstream.server_close(); thread.join()


class ScreenTests(unittest.TestCase):
    def tearDown(self):
        screen.stop_screen()
        screen._set(phase='idle', udid=None, transport=None, error=None)

    def test_failed_restart_is_not_reported_as_success_and_closes(self):
        screen._set(phase='running', udid='phone', transport='usb')
        conn = MagicMock()
        conn.getresponse.return_value.status = 500
        with patch('http.client.HTTPConnection', return_value=conn):
            result = screen.restart_screen('phone')
        self.assertIn('Restart failed', result['error'])
        self.assertEqual(conn.close.call_count, 2)

    def test_switch_waits_for_cleanup_and_duplicate_starts_share_worker(self):
        events = []
        async def serve(udid, transport):
            events.append(('start', transport))
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(.03)
                events.append(('close', transport))
        with patch.object(screen, '_usb_udids', return_value=['phone']), patch.object(screen, 'wifi_paired_udids', return_value=['phone']), patch.object(screen, 'developer_mode_enabled', return_value=True), patch.object(screen, '_serve', side_effect=serve):
            screen.start_screen('phone', 'usb')
            self.assertTrue(screen._READY.wait(2))
            worker = screen._WORKER
            screen.start_screen('phone', 'usb')
            self.assertIs(screen._WORKER, worker)
            screen.start_screen('phone', 'wifi')
            self.assertTrue(screen._READY.wait(2))
            screen.stop_screen()
        self.assertEqual(events, [('start', 'usb'), ('close', 'usb'), ('start', 'wifi'), ('close', 'wifi')])


class UpdateTests(unittest.TestCase):
    def manifest(self, version=None):
        version = version or f'{int(updater.VERSION.split(".")[0]) + 1}.0.0'
        return dict(version=version, url=f'{updater.BASE}/download/v{version}/Pane.exe', sha256='a'*64, size=123)

    def test_only_newer_versions_are_selected(self):
        self.assertTrue(updater.validate_manifest(self.manifest()))
        self.assertFalse(updater.validate_manifest(self.manifest('1.0.0')))
        self.assertFalse(updater.validate_manifest(self.manifest(updater.VERSION)))

    def test_wrong_repo_bad_hash_version_and_size_rejected(self):
        for change in ({'url':'https://example.com/Pane.exe'}, {'sha256':'xyz'}, {'version':'v1.2.3'}, {'size':True}, {'size':0}, {'size':updater.MAX_EXE_SIZE+1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                updater.validate_manifest({**self.manifest(), **change})
