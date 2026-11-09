import asyncio
import base64
import socket
import unittest
import importlib.util
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock
from handset import wifi
HAS_DEVICE_DEPENDENCIES = importlib.util.find_spec('pymobiledevice3') is not None
if HAS_DEVICE_DEPENDENCIES:
    from pymobiledevice3 import bonjour

@unittest.skipUnless(HAS_DEVICE_DEPENDENCIES, 'Device dependency integration runs in the Windows release job')
class WifiCompatibilityTests(unittest.TestCase):
    def test_browse_wrapper_forwards_interface_filter(self):
        original_bind,original_send,original_address=bonjour._bind_ipv4,bonjour._send_query_all,bonjour.Address.full_ip
        was_patched=wifi._bonjour_patched
        send=AsyncMock(return_value=2)
        try:
            wifi._bonjour_patched=False
            with patch.object(bonjour,'_send_query_all',send),patch.object(wifi,'_local_ipv4',return_value=[]) as local:
                wifi._patch_bonjour()
                sock=SimpleNamespace(family=socket.AF_INET)
                result=asyncio.run(bonjour._send_query_all([(None,sock)],b'query',('utun',)))
                self.assertEqual(result,2)
                send.assert_awaited_once_with([(None,sock)],b'query',('utun',))
                local.assert_called_once_with(('utun',))
        finally:
            bonjour._bind_ipv4=original_bind;bonjour._send_query_all=original_send;bonjour.Address.full_ip=original_address;wifi._bonjour_patched=was_patched
    def test_windows_scope_uses_numeric_index_for_guid_or_friendly_name(self):
        adapter=SimpleNamespace(name='{guid}',nice_name='Wireless adapter',index=12)
        with patch.object(wifi.os,'name','nt'),patch.object(wifi.socket,'if_nametoindex',side_effect=OSError),patch('ifaddr.get_adapters',return_value=[adapter]):
            for name in ('{guid}','Wireless adapter','12'):
                self.assertEqual(wifi.scoped_address('fe80::123',name),'fe80::123%12')
            self.assertEqual(wifi.scoped_address('192.0.2.1','{guid}'),'192.0.2.1')


@unittest.skipUnless(HAS_DEVICE_DEPENDENCIES, 'Device dependency integration runs in the Windows release job')
class WifiProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from pymobiledevice3.remote import tunnel_service
        self.tunnel = tunnel_service
        self.key = bytes(range(16))
        records = [('test', None, {tunnel_service.PEER_ALT_IRK_KEY: self.key}),
                   ('other', None, {tunnel_service.PEER_ALT_IRK_KEY: b'z' * 16})]
        self.patchers = [
            patch.object(wifi, '_patch_bonjour'),
            patch.object(tunnel_service, 'iter_remote_pair_records_by_identifier', return_value=records),
            patch.object(bonjour, 'browse_remotepairing', new_callable=AsyncMock),
            patch.object(tunnel_service, 'RemotePairingTunnelService'),
        ]
        _, self.records, self.browse, self.factory = [p.start() for p in self.patchers]
        for patcher in self.patchers:
            self.addCleanup(patcher.stop)

    def answer(self, *hosts, key=None, port=1234):
        from pymobiledevice3.remote.siphash import compute_auth_tag
        identifier = 'opaque-advertisement'
        tag = base64.b64encode(compute_auth_tag(self.key if key is None else key, identifier)).decode()
        return SimpleNamespace(port=port, addresses=[SimpleNamespace(full_ip=host) for host in hosts],
                               properties={'identifier': identifier, 'authTag': tag})

    @staticmethod
    def service(*, error=None):
        return SimpleNamespace(connect=AsyncMock(side_effect=error), close=AsyncMock(),
                               _validate_pairing=AsyncMock(return_value=True))

    async def test_complete_browse_keeps_late_ipv4_and_first_success_stops_connecting(self):
        answer = self.answer('fe80::1%12')
        async def browse(timeout):
            # An incremental browser would already have yielded the IPv6-only
            # service before its A record arrived. Full browse retains both.
            await asyncio.sleep(0)
            answer.addresses.append(SimpleNamespace(full_ip='192.168.1.20'))
            return [answer, self.answer('192.168.1.20', 'fe80::2%12')]
        self.browse.side_effect = browse
        first = self.service()
        self.factory.return_value = first
        result = await wifi._wifi_provider('test', False)
        self.assertEqual(result, (first, None))
        self.browse.assert_awaited_once_with(timeout=wifi.BONJOUR_TIMEOUT)
        self.factory.assert_called_once_with('test', '192.168.1.20', 1234)
        first.connect.assert_awaited_once_with(autopair=False)
        first.close.assert_not_awaited()

    async def test_stale_ipv6_pair_verification_is_bounded_and_next_address_can_work(self):
        self.browse.return_value = [self.answer('fe80::1%12', 'fe80::2%12')]
        first, second = self.service(), self.service()
        async def never_reply(**kwargs):
            await asyncio.Event().wait()
        first.connect.side_effect = never_reply
        self.factory.side_effect = [first, second]
        with patch.object(wifi, 'WIFI_CONNECT_TIMEOUT', .02):
            result = await wifi._wifi_provider('test', False)
        self.assertEqual(result, (second, None))
        first.close.assert_awaited_once()
        second.close.assert_not_awaited()

    async def test_failed_duplicate_address_is_not_retried(self):
        self.browse.return_value = [self.answer('192.168.1.20'), self.answer('192.168.1.20', '192.168.1.21')]
        first, second = self.service(error=OSError('unreachable')), self.service()
        self.factory.side_effect = [first, second]
        self.assertEqual(await wifi._wifi_provider('test', False), (second, None))
        self.assertEqual(self.factory.call_count, 2)
        first.close.assert_awaited_once()

    async def test_cancellation_during_pair_verification_closes_candidate(self):
        self.browse.return_value = [self.answer('192.168.1.20')]
        service = self.service()
        entered = asyncio.Event()
        async def verify(**kwargs):
            entered.set()
            await asyncio.Event().wait()
        service.connect.side_effect = verify
        self.factory.return_value = service
        task = asyncio.create_task(wifi._wifi_provider('test', False))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        service.close.assert_awaited_once()

    async def test_unmatched_or_different_phone_advertisement_never_connects(self):
        self.browse.return_value = [self.answer('192.168.1.20', key=b'z' * 16),
                                   self.answer('192.168.1.21', key=b'x' * 16)]
        with self.assertRaises(wifi.WifiNotFoundError):
            await wifi._wifi_provider('test', False)
        self.factory.assert_not_called()

    async def test_missing_matching_pair_record_never_browses_or_connects(self):
        with self.assertRaises(wifi.WifiNotFoundError):
            await wifi._wifi_provider('missing', False)
        self.browse.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_overall_timeout_bounds_browse_and_cleanup_is_bounded(self):
        async def never_reply(*args, **kwargs):
            await asyncio.Event().wait()
        self.browse.side_effect = never_reply
        with patch.object(wifi, 'WIFI_PROVIDER_TIMEOUT', .02):
            with self.assertRaises(wifi.WifiNotFoundError):
                await wifi._wifi_provider('test', False)
        self.factory.assert_not_called()
        self.browse.side_effect = None
        self.browse.return_value = [self.answer('192.168.1.20')]
        service = self.service(error=OSError('unreachable'))
        service.close.side_effect = never_reply
        self.factory.return_value = service
        with patch.object(wifi, 'WIFI_CLOSE_TIMEOUT', .02):
            with self.assertRaises(wifi.WifiNotFoundError):
                await wifi._wifi_provider('test', False)
        service.close.assert_awaited_once()

    async def test_unexpected_programming_failure_is_not_swallowed(self):
        self.browse.return_value = [self.answer('192.168.1.20')]
        service = self.service(error=RuntimeError('unexpected'))
        self.factory.return_value = service
        with self.assertRaisesRegex(RuntimeError, 'unexpected'):
            await wifi._wifi_provider('test', False)
        service.close.assert_awaited_once()

    async def test_explicit_pairing_rejection_has_accurate_repair_message(self):
        self.browse.return_value = [self.answer('192.168.1.20', 'fe80::1%12')]
        first, second = self.service(), self.service(error=OSError('unreachable'))
        validation = first._validate_pairing
        validation.return_value = False
        async def reject(**kwargs):
            self.assertIs(await first._validate_pairing(), False)
            raise self.tunnel.ConnectionTerminatedError()
        first.connect.side_effect = reject
        self.factory.side_effect = [first, second]
        with self.assertRaisesRegex(wifi.WifiPairingRejectedError, 'Reconnect USB once to repair Wi-Fi'):
            await wifi._wifi_provider('test', False)
        first.close.assert_awaited_once()
        second.close.assert_awaited_once()
        self.assertIs(first._validate_pairing, validation)
        validation.assert_awaited_once()

    async def test_connection_termination_without_false_validation_is_not_pairing_rejection(self):
        self.browse.return_value = [self.answer('192.168.1.20')]
        service = self.service(error=self.tunnel.ConnectionTerminatedError())
        self.factory.return_value = service
        with self.assertRaises(wifi.WifiNotFoundError):
            await wifi._wifi_provider('test', False)
        service._validate_pairing.assert_not_awaited()
        service.close.assert_awaited_once()

    async def test_successful_other_address_supersedes_a_rejected_candidate(self):
        self.browse.return_value = [self.answer('192.168.1.20', '192.168.1.21')]
        first, second = self.service(), self.service()
        first._validate_pairing.return_value = False
        async def reject(**kwargs):
            await first._validate_pairing()
            raise self.tunnel.ConnectionTerminatedError()
        first.connect.side_effect = reject
        self.factory.side_effect = [first, second]
        self.assertEqual(await wifi._wifi_provider('test', False), (second, None))
        first.close.assert_awaited_once()
        second.close.assert_not_awaited()


@unittest.skipUnless(HAS_DEVICE_DEPENDENCIES, 'Device dependency integration runs in the Windows release job')
class WifiTunnelTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def run_tunnel(self, operation):
        from pymobiledevice3.remote import tunnel_service, userspace_tunnel
        original_provider = userspace_tunnel._create_no_root_tunnel_provider
        dial = MagicMock(return_value=object())
        async def opened(tunnel):
            self.assertIs(userspace_tunnel._create_no_root_tunnel_provider, wifi._wifi_provider)
            self.assertIsNot(tunnel_service.create_connection, dial)
            tunnel_service.create_connection(('192.168.1.20', 1234))
            dial.assert_called_with(('192.168.1.20', 1234), timeout=wifi.WIFI_TCP_TIMEOUT)
            tunnel_service.create_connection(('192.168.1.20', 1234), timeout=.25)
            dial.assert_called_with(('192.168.1.20', 1234), timeout=.25)
            return await operation()
        with patch.object(tunnel_service, 'create_connection', dial), \
             patch.object(userspace_tunnel.UserspaceRsdTunnel, '_aopen_locked', opened):
            try:
                return await wifi.wifi_tunnel('test').aopen()
            finally:
                self.assertIs(tunnel_service.create_connection, dial)
                self.assertIs(userspace_tunnel._create_no_root_tunnel_provider, original_provider)

    async def test_scoped_tcp_timeout_and_symbols_restored_after_success(self):
        result = object()
        async def succeed():
            return result
        self.assertIs(await self.run_tunnel(succeed), result)

    async def test_symbols_restored_after_failure(self):
        async def fail():
            raise RuntimeError('startup failed')
        with self.assertRaisesRegex(RuntimeError, 'startup failed'):
            await self.run_tunnel(fail)

    async def test_symbols_restored_after_cancellation(self):
        entered = asyncio.Event()
        async def wait():
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(self.run_tunnel(wait))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_entire_startup_has_a_deadline(self):
        async def never_reply():
            await asyncio.Event().wait()
        with patch.object(wifi, 'WIFI_STARTUP_TIMEOUT', .02):
            with self.assertRaises(TimeoutError):
                await self.run_tunnel(never_reply)
