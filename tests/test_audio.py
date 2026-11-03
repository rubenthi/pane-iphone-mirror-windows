import io
import json
import unittest
from unittest.mock import MagicMock, patch
from handset.audio import LaptopAudio
from handset.security import ACCESS_TOKEN
from test_server_security import ServerSecurityTests


class AudioTests(unittest.TestCase):
    def test_unsupported_platform_does_not_spawn(self):
        audio = LaptopAudio()
        with patch.object(audio, 'supported', return_value=False), patch('subprocess.run') as run:
            self.assertEqual(audio.refresh()['phase'], 'unavailable')
            with self.assertRaises(ValueError):
                audio.connect('anything')
            run.assert_not_called()

    def test_only_discovered_devices_can_start_and_errors_surface(self):
        audio = LaptopAudio()
        with patch.object(audio, 'supported', return_value=True), patch('subprocess.Popen') as spawn:
            with self.assertRaises(ValueError):
                audio.connect('untrusted-id')
            spawn.assert_not_called()
        result = MagicMock(returncode=1, stdout='{"phase":"error","error":"Bluetooth is off"}\n')
        with patch.object(audio, 'supported', return_value=True), patch('subprocess.run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'Bluetooth is off'):
                audio.refresh()

    def test_native_disconnect_updates_state_and_releases_pipes(self):
        audio = LaptopAudio()
        process = MagicMock()
        process.stdout = io.StringIO('{"phase":"connected"}\n{"phase":"disconnected","note":"Lost link"}\n')
        process.stdin = io.StringIO()
        audio._process = process
        audio._watch(process)
        self.assertEqual(audio.status()['phase'], 'disconnected')
        self.assertIsNone(audio._process)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stdin.closed)


class AudioApiTests(ServerSecurityTests):
    def test_audio_requires_token_and_valid_action(self):
        for method in ('GET', 'POST'):
            self.assertEqual(self.request(method, '/api/audio')[0], 403)
        self.assertEqual(self.request('POST', '/api/audio', {'X-Pane-Token':ACCESS_TOKEN}, b'{"action":"bad"}')[0], 400)

    def test_audio_commands_reach_controller(self):
        with patch('handset.server.audio.connect', return_value={'phase':'connecting'}) as connect:
            status, _, body = self.request('POST', '/api/audio', {'X-Pane-Token':ACCESS_TOKEN}, b'{"action":"connect","id":"phone"}')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['phase'], 'connecting')
            connect.assert_called_once_with('phone')
