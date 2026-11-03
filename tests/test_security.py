"""Run with: python -m unittest discover -s tests -v"""

import unittest

from handset.security import ACCESS_TOKEN, request_allowed


class RequestGuardTests(unittest.TestCase):
    def setUp(self):
        self.headers = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "Sec-Fetch-Site": "same-origin",
            "X-Pane-Token": ACCESS_TOKEN,
        }

    def check(self, headers, *, token_required=True):
        return request_allowed(headers, 8765, token_required=token_required)

    def test_same_origin_request_with_token_is_allowed(self):
        self.assertTrue(self.check(self.headers))

    def test_api_requires_token(self):
        self.assertFalse(self.check({k: v for k, v in self.headers.items() if k != "X-Pane-Token"}))
        self.assertFalse(self.check({**self.headers, "X-Pane-Token": "invalid"}))

    def test_other_host_is_blocked_even_with_valid_token(self):
        for host in ("attacker.example:8765", "localhost:8765", "127.0.0.1:8766", "127.0.0.1:8765.attacker.example"):
            with self.subTest(host=host):
                self.assertFalse(self.check({**self.headers, "Host": host}))

    def test_cross_origin_and_null_origin_blocked(self):
        for origin in ("null", "https://attacker.example", "http://127.0.0.1:8766"):
            with self.subTest(origin=origin):
                self.assertFalse(self.check({**self.headers, "Origin": origin}))

    def test_browser_cross_site_blocked_even_without_origin(self):
        headers = {k: v for k, v in self.headers.items() if k != "Origin"}
        headers["Sec-Fetch-Site"] = "cross-site"
        self.assertFalse(self.check(headers))
        headers["Sec-Fetch-Site"] = "same-site"
        self.assertFalse(self.check(headers))

    def test_navigation_and_auth_endpoint_allowed_without_token(self):
        headers = {"Host": "127.0.0.1:8765", "Sec-Fetch-Site": "none"}
        self.assertTrue(self.check(headers, token_required=False))
        self.assertFalse(self.check(headers, token_required=True))

    def test_custom_local_port(self):
        self.assertTrue(request_allowed({"Host": "127.0.0.1:9123"}, 9123, token_required=False))
        self.assertFalse(request_allowed({"Host": "127.0.0.1:8765"}, 9123, token_required=False))


if __name__ == "__main__":
    unittest.main()
