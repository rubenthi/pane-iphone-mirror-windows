import io
import json
import queue
import unittest
from unittest.mock import Mock, patch

from handset.bluetooth import BluetoothBridge, validate
import test_server_security as security_tests
from handset.security import ACCESS_TOKEN


class BluetoothValidationTests(unittest.TestCase):
    def test_cursor_limits_and_types(self):
        valid = dict(action='cursor.move', buttons=1, dx=-127, dy=127, wheel=0)
        self.assertEqual(validate(valid), valid)
        for key, value in [('buttons', 8), ('dx', 128), ('dy', -128), ('wheel', True), ('dx', 1.5)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate({**valid, key:value})

    def test_only_allowlisted_actions_and_device_ids(self):
        for value in [{}, {'action':'exec'}, {'action':[]}, {'action':'audio.connect', 'device':'a\0b'}]:
            with self.assertRaises(ValueError): validate(value)
        self.assertEqual(validate({'action':'cursor.start', 'shell':'ignored'}), {'action':'cursor.start'})

    def test_helper_errors_do_not_claim_success(self):
        bridge = BluetoothBridge()
        bridge._process = Mock(stdin=io.StringIO())
        bridge._process.poll.return_value = None
        bridge._responses = queue.Queue()
        bridge._responses.put({'ok':False, 'error':'Permission denied'})
        with self.assertRaisesRegex(ValueError, 'Permission denied'):
            bridge._request({'action':'audio.connect'})

    def test_timeout_kills_helper_instead_of_reusing_late_reply(self):
        bridge = BluetoothBridge()
        process = bridge._process = Mock(stdin=io.StringIO())
        process.poll.return_value = None
        bridge._responses = Mock()
        bridge._responses.get.side_effect = queue.Empty
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            bridge._request({'action':'status'})
        self.assertIsNone(bridge._process)
        process.wait.assert_called_once()


class BluetoothHttpTests(security_tests.ServerSecurityTests):
    def test_new_routes_require_authentication(self):
        for method, route in [('GET','/api/bluetooth'), ('POST','/api/bluetooth'),
                              ('POST','/api/bluetooth/settings'), ('POST','/api/screen/stop')]:
            self.assertEqual(self.request(method, route)[0], 403)

    def test_invalid_settings_target_rejected(self):
        code, _, _ = self.request('POST', '/api/bluetooth/settings', {'X-Pane-Token':ACCESS_TOKEN}, json.dumps({'target':'file:///secret'}))
        self.assertEqual(code, 400)

    def test_notifications_are_not_available_cross_origin(self):
        code, _, _ = self.request('GET','/api/bluetooth', {'X-Pane-Token':ACCESS_TOKEN,'Origin':'https://example.com'})
        self.assertEqual(code, 403)

    def test_command_failure_is_a_failed_http_response(self):
        with patch('handset.server.bluetooth.command', side_effect=RuntimeError('No adapter')):
            code, _, body = self.request('POST','/api/bluetooth', {'X-Pane-Token':ACCESS_TOKEN}, '{"action":"cursor.start"}')
        self.assertEqual(code, 400)
        self.assertEqual(json.loads(body)['error'], 'No adapter')
