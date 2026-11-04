import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
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
        self.assertFalse(factory.call_args.kwargs['motion_idr'])
        self.assertTrue(factory.call_args.kwargs['rctl_enabled'])

    async def test_busy_display_leaves_a_disconnectable_audio_session(self):
        from handset import screen
        from pymobiledevice3.exceptions import CoreDeviceError
        rsd = SimpleNamespace(peer_info={'Services': {screen.DISPLAY_SERVICE: {}}},
                              get_value=AsyncMock(return_value={'DeviceName': 'My iPhone'}))
        tunnel = MagicMock()
        tunnel.__aenter__.return_value = rsd
        with patch.object(screen, '_open_tunnel', return_value=tunnel), \
             patch.object(screen, '_stream', side_effect=CoreDeviceError("Busy", code=9022)), \
             patch('handset.audio.manager.remember_identity') as remember:
            await screen._serve('phone', 'wifi')
            self.assertEqual(screen.screen_status()['phase'], 'audio-only')
            remember.assert_called_once_with('phone', {'DeviceName': 'My iPhone'})
            self.assertTrue(screen.stop_screen())
            self.assertEqual(screen.screen_status()['phase'], 'idle')
