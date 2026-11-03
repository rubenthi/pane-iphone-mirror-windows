"""Starting video must not mute the independent Bluetooth audio route."""
import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from handset import screen


class StartVolumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_starts_without_volume_commands_and_cancels_server(self):
        ready = asyncio.Event()
        stopped = asyncio.Event()
        class Server:
            def __init__(self, *args, **kwargs):
                self._ensure_fresh_stream = AsyncMock()
                self._handle_button = AsyncMock(side_effect=AssertionError('Must not mute media'))
                instances.append(self)
            async def serve(self):
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
        instances = []
        def state(**values):
            if values.get('phase') == 'running':
                ready.set()
        writer = SimpleNamespace(close=lambda: None, wait_closed=AsyncMock())
        fake = SimpleNamespace(is_media_in_use_error=lambda error: False)
        with patch.dict(sys.modules, {'pymobiledevice3.remote.core_device.display_service': fake}), \
             patch('asyncio.open_connection', AsyncMock(return_value=(None, writer))), \
             patch.object(screen, '_set', side_effect=state):
            task = asyncio.create_task(screen._stream(None, 'phone', Server))
            try:
                await asyncio.wait_for(ready.wait(), 2)
                instances[0]._ensure_fresh_stream.assert_awaited_once()
                instances[0]._handle_button.assert_not_called()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(stopped.is_set())
