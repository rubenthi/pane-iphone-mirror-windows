import asyncio
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock
from handset import wifi
from pymobiledevice3 import bonjour

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
    def test_extra_discovered_services_are_closed(self):
        first,extra=MagicMock(),MagicMock();extra.close=AsyncMock()
        with patch.object(wifi,'_patch_bonjour'),patch('pymobiledevice3.remote.tunnel_service.get_remote_pairing_tunnel_services',AsyncMock(return_value=[first,extra])):
            result=asyncio.run(wifi._wifi_provider('test',False))
        self.assertIs(result[0],first);extra.close.assert_awaited_once()
