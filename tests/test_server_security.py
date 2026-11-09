"""HTTP-level checks that do not require a connected iPhone."""

import http.client
import json
import threading
import unittest

from handset.security import ACCESS_TOKEN, MAX_REQUEST_BODY
from handset.server import Handler, SingleServer
from unittest.mock import Mock, patch


class ServerSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = SingleServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def test_direct_navigation_still_works(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_development_reset_requires_token_safe_profile_and_confirmation(self):
        route = '/api/development/reset'
        headers = {'X-Pane-Token': ACCESS_TOKEN}
        restart = Mock()
        with patch.object(self.server, 'request_development_reset', restart):
            self.assertEqual(self.request('POST', route)[0], 403)
            with patch('handset.server.can_reset_development', return_value=False):
                self.assertEqual(self.request('POST', route, headers, b'{"confirm":true}')[0], 404)
            with patch('handset.server.can_reset_development', return_value=True):
                self.assertEqual(self.request('POST', route, headers, b'{"confirm":1}')[0], 400)
                with patch('handset.server.setup.status', return_value={'phase':'working'}):
                    self.assertEqual(self.request('POST', route, headers, b'{"confirm":true}')[0], 409)
                restart.assert_not_called()
                with patch('handset.server.setup.status', return_value={'phase':'idle'}), patch(
                    'handset.server.signing.status', return_value={'phase':'idle'}
                ):
                    self.assertEqual(self.request('POST', route, headers, b'{"confirm":true}')[0], 200)
                    restart.assert_called_once_with()

    def test_auth_token_is_available_to_same_origin(self):
        status, _, body = self.request("GET", "/api/auth")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["token"], ACCESS_TOKEN)

    def test_phone_metadata_requires_token(self):
        status, _, _ = self.request("GET", "/api/screen")
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/api/screen", {"X-Pane-Token": ACCESS_TOKEN})
        self.assertEqual(status, 200)

    def test_controls_and_video_proxy_require_token(self):
        for method, path in (("POST", "/api/screen"), ("POST", "/mirror/touch"), ("GET", "/mirror/stream.bin")):
            with self.subTest(method=method, path=path):
                status, _, _ = self.request(method, path)
                self.assertEqual(status, 403)

    def test_cross_origin_and_dns_rebinding(self):
        status, _, _ = self.request("GET", "/api/auth", {"Origin": "https://attacker.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/", {"Host": "attacker.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/", {"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    def test_large_post_rejected_before_reading_body(self):
        status, _, _ = self.request("POST", "/api/screen", {
            "X-Pane-Token": ACCESS_TOKEN,
            "Content-Length": str(MAX_REQUEST_BODY + 1),
        })
        self.assertEqual(status, 413)

    def test_audio_routes_are_not_exposed(self):
        for path in ('/mirror/audio.bin', '/mirror/audio', '/mirror/%61udio.bin'):
            for method in ('GET', 'POST'):
                status, _, _ = self.request(method, path, {'X-Pane-Token': ACCESS_TOKEN})
                self.assertEqual(status, 404)

    def test_companion_actions_require_auth_and_reject_bad_identifiers(self):
        for path in ('/api/signing/start', '/api/signing/answer', '/api/signing/cancel', '/api/setup/start', '/api/uploads/start', '/api/bluetooth/connect'):
            # Authorization is checked before the body. Sending a later body
            # packet can reset an already-closed HTTP/1.0 socket on Windows.
            self.assertEqual(self.request('POST', path)[0], 403)
        self.assertEqual(self.request('GET', '/api/setup')[0], 403)
        self.assertEqual(self.request('GET', '/api/signing')[0], 403)
        self.assertEqual(self.request('GET', '/api/uploads')[0], 403)

    def test_bluetooth_preferences_require_same_origin_token(self):
        for method, path in [('GET', '/api/preferences'), ('POST', '/api/preferences'),
                             ('GET', '/api/bluetooth/devices'), ('POST', '/api/bluetooth/settings'),
                             ('POST', '/api/notifications/settings')]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path)[0], 403)
        status, _, _ = self.request('POST', '/api/preferences', {
            'X-Pane-Token': ACCESS_TOKEN, 'Content-Type': 'application/json',
        }, b'{"background_enabled":"false"}')
        self.assertEqual(status, 400)

    def test_notification_settings_action_opens_only_the_fixed_settings_page(self):
        headers = {'X-Pane-Token': ACCESS_TOKEN, 'Content-Type': 'application/json'}
        with patch('handset.server.notifications.open_notification_settings') as launch:
            status, _, body = self.request('POST', '/api/notifications/settings', headers, b'{}')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {'ok': True})
            launch.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
