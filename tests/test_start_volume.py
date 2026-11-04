import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from handset.screen import _stream


class StartVolumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_start_preserves_phone_media_volume(self):
        stopped = asyncio.Event()
        server = SimpleNamespace(_handle_button=AsyncMock(), _ensure_fresh_stream=AsyncMock())
        async def serve():
            await server._eager_stream_start()
            await stopped.wait()
        server.serve = serve
        writer = Mock(wait_closed=AsyncMock())
        factory = Mock(return_value=server)
        def state(**values):
            if values.get('phase') == 'running': stopped.set()
        module = SimpleNamespace(is_media_in_use_error=lambda _:False)
        with patch.dict(sys.modules, {'pymobiledevice3.remote.core_device.display_service':module}), \
             patch('handset.screen.asyncio.open_connection', AsyncMock(return_value=(None, writer))), \
             patch('handset.screen._set', side_effect=state):
            await _stream(None, 'phone', factory)
        server._handle_button.assert_not_awaited()
        self.assertFalse(factory.call_args.kwargs['audio_default_on'])
