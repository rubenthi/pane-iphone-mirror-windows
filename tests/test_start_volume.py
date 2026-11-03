import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from handset.screen import _silence_phone


class StartVolumeTests(unittest.TestCase):
    def test_every_new_session_lowers_volume_sequentially(self):
        button = AsyncMock(return_value=(200, b'ok'))
        server = SimpleNamespace(_handle_button=button)
        asyncio.run(_silence_phone(server))
        self.assertEqual(button.await_count, 20)
        self.assertTrue(all(c.args == (b'{"name":"volume-down","state":"press"}',) for c in button.await_args_list))
        asyncio.run(_silence_phone(server))
        self.assertEqual(button.await_count, 40)

    def test_rejection_stops_and_reports_failure(self):
        button = AsyncMock(return_value=(503, b'not ready'))
        with self.assertRaises(RuntimeError):
            asyncio.run(_silence_phone(SimpleNamespace(_handle_button=button)))
        self.assertEqual(button.await_count, 1)
