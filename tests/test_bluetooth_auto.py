import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handset.bluetooth import Bluetooth


class AutomaticBluetoothTests(unittest.TestCase):
    def test_write_failures_never_expose_file_contents(self):
        link = Bluetooth()
        error = RuntimeError('Could not write value private-file-bytes: Protocol Error 0xF2: Unknown')
        with patch.object(link, '_session', new=AsyncMock(side_effect=error)), patch('handset.bluetooth.store') as fake_store:
            fake_store.return_value.rows = []
            link._run({})
        self.assertEqual(link.status()['errorCode'], '0xF2')
        self.assertNotIn('private-file-bytes', json.dumps(link.status()))
    def test_only_a_completed_saved_binding_is_reconnected(self):
        link = Bluetooth()
        for binding in ({}, {'token':'saved'}, {'token':'saved','service':'uuid','onboardingComplete':False}):
            with patch('handset.bluetooth.read_json', return_value=binding), patch.object(link, 'connect') as connect:
                link._auto_tick()
                connect.assert_not_called()
        with patch('handset.bluetooth.read_json', return_value={'token':'saved','service':'uuid'}), patch.object(link, 'connect') as connect:
            link._auto_tick()
            connect.assert_called_once_with(automatic=True)

    def test_manual_disconnect_pauses_reconnect_until_explicit_connect(self):
        link = Bluetooth()
        link.disconnect()
        with patch('handset.bluetooth.read_json', return_value={'token':'saved','service':'uuid'}), patch('handset.bluetooth.threading.Thread') as worker:
            link.connect(automatic=True)
            worker.assert_not_called()
            link.connect()
            worker.return_value.start.assert_called_once()
            self.assertFalse(link._auto_paused)

    def test_shutdown_prevents_new_connections(self):
        link = Bluetooth()
        link.stop_auto()
        with patch('handset.bluetooth.read_json', return_value={'token':'saved','service':'uuid'}), patch('handset.bluetooth.threading.Thread') as worker:
            link.connect(automatic=True)
            worker.assert_not_called()

    def test_shutdown_waits_for_subscription_cleanup_before_process_exit(self):
        link = Bluetooth()
        link.worker = MagicMock()
        link._auto_worker = MagicMock()
        link.stop_auto()
        link.worker.join.assert_called_once_with(timeout=5)
        link._auto_worker.join.assert_called_once_with(timeout=1)

    def test_disconnect_before_session_start_never_scans(self):
        link = Bluetooth()
        link.disconnect()
        scanner = MagicMock(find_device_by_filter=AsyncMock())
        with patch.dict('sys.modules', {'bleak':MagicMock(BleakScanner=scanner)}):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(link._session({'token':'saved','service':'uuid'}))
        scanner.find_device_by_filter.assert_not_awaited()

    def test_reconnect_discovers_only_the_bound_service_without_stale_handles(self):
        link = Bluetooth()
        peer = object()
        scanner = MagicMock(find_device_by_filter=AsyncMock(return_value=peer))
        client = MagicMock(is_connected=False)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=context)
        client.start_notify = AsyncMock()
        rpc = MagicMock(call=AsyncMock(return_value={'version':1}))
        with patch.dict('sys.modules', {'bleak':MagicMock(BleakScanner=scanner, BleakClient=factory)}), patch('handset.bluetooth.Rpc', return_value=rpc), patch('handset.bluetooth.write_json'):
            with self.assertRaises(ConnectionError):
                asyncio.run(link._session({'token':'test-token','service':'BOUND-SERVICE','peerName':'test'}))
        factory.assert_called_once_with(peer, pair=True, timeout=120, services=['bound-service'], winrt={'use_cached_services':False})
