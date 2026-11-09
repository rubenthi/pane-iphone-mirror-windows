"""Cable-free connection to the iPhone over the local network.

iOS 17+ announces a RemotePairing service over Bonjour on Wi-Fi. A host that
holds a RemotePairing record for the phone can open the same no-admin
userspace tunnel used for USB, just over the network. The record is created
once over USB, where the existing Trust makes it promptless.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import socket
import struct
from typing import Optional

BONJOUR_TIMEOUT = 8.0
WIFI_CONNECT_TIMEOUT = 5.0
WIFI_PROVIDER_TIMEOUT = 25.0
WIFI_CLOSE_TIMEOUT = 2.0
WIFI_TCP_TIMEOUT = 5.0
WIFI_STARTUP_TIMEOUT = 45.0
_MDNS_GROUP = "224.0.0.251"
_MDNS_PORT = 5353
_bonjour_patched = False


def scoped_address(ip: str, interface: str | None) -> str:
    if not interface or not ip.lower().startswith('fe80:'):
        return ip
    # Windows interface names are long GUID paths. Winsock requires the
    # numeric zone index; passing the name falls into IDNA hostname parsing.
    zone = interface
    if os.name == 'nt' and not interface.isdecimal():
        try:
            zone = socket.if_nametoindex(interface)
        except OSError:
            import ifaddr
            adapter = next((a for a in ifaddr.get_adapters() if interface in (a.name, a.nice_name)), None)
            if adapter is None or not adapter.index:
                raise OSError('Cannot resolve the network adapter for the iPhone IPv6 address.')
            zone = adapter.index
    return f'{ip}%{zone}'


def _local_ipv4(skip_interfaces: tuple[str, ...] = ()) -> list[str]:
    try:
        import ifaddr
    except ImportError:
        return []
    found = []
    for adapter in ifaddr.get_adapters():
        if str(adapter.name).startswith(skip_interfaces) or str(adapter.nice_name).startswith(skip_interfaces):
            continue
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and not ip.ip.startswith("127."):
                found.append(ip.ip)
    return found


def _patch_bonjour() -> None:
    """Browse mDNS on every IPv4 adapter, not just Windows' default one.

    pymobiledevice3 joins the mDNS group and sends its queries on the default
    interface only. With several adapters (Wi-Fi, Bluetooth, the iPhone's USB
    hotspot, virtual adapters) that is rarely the Wi-Fi, so the phone's
    announcement is never seen.
    """
    global _bonjour_patched
    if _bonjour_patched:
        return
    from pymobiledevice3 import bonjour

    original_bind = bonjour._bind_ipv4
    original_send = bonjour._send_query_all

    async def bind_ipv4(queue):
        transport, sock = await original_bind(queue)
        group = socket.inet_aton(_MDNS_GROUP)
        for ip in _local_ipv4():
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, struct.pack("=4s4s", group, socket.inet_aton(ip)))
        return transport, sock

    async def send_query_all(transports, pkt, skip_interfaces=()):
        sent = await original_send(transports, pkt, skip_interfaces)
        for _, sock in transports:
            if sock.family != socket.AF_INET:
                continue
            # Queries must leave from port 5353 so replies come back to the
            # listening socket; send synchronously so each one uses its own
            # egress interface.
            for ip in _local_ipv4(skip_interfaces):
                with contextlib.suppress(OSError):
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                    sock.sendto(pkt, (_MDNS_GROUP, _MDNS_PORT))
                    sent += 1
        return sent

    bonjour._bind_ipv4 = bind_ipv4
    bonjour._send_query_all = send_query_all
    bonjour.Address.full_ip = property(lambda address: scoped_address(address.ip, address.iface))
    _bonjour_patched = True


def wifi_paired_udids() -> list[str]:
    try:
        from pymobiledevice3.pair_records import iter_remote_paired_identifiers

        return sorted(set(iter_remote_paired_identifiers()))
    except Exception:
        return []


def pair_for_wifi(udid: str) -> dict:
    """Write the RemotePairing record over the trusted USB link."""

    async def pair() -> None:
        from pymobiledevice3.exceptions import RemotePairingCompletedError
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.remote.tunnel_service import RemotePairingLockdownService

        lockdown = await create_using_usbmux(serial=udid)
        try:
            service = await RemotePairingLockdownService.create(lockdown)
            try:
                await service.connect(autopair=True)
            except RemotePairingCompletedError:
                pass
            finally:
                await service.close()
        finally:
            await lockdown.close()

    try:
        asyncio.run(pair())
    except Exception as error:
        return {"ok": False, "error": f"Wi-Fi setup needs the cable once: {error}"}
    return {"ok": udid in wifi_paired_udids(), "paired": wifi_paired_udids()}


async def _wifi_provider(serial: Optional[str], autopair: bool, remotepairing_fallback: bool = True):
    from pymobiledevice3 import bonjour
    from pymobiledevice3.exceptions import ConnectionTerminatedError
    from pymobiledevice3.remote import tunnel_service

    _patch_bonjour()
    alt_irks = {}
    pairing_rejected = False
    for identifier, _, record in tunnel_service.iter_remote_pair_records_by_identifier():
        if serial is not None and identifier != serial:
            continue
        key = record.get(tunnel_service.PEER_ALT_IRK_KEY)
        if isinstance(key, bytes) and len(key) == 16:
            alt_irks[identifier] = key

    async def close_candidate(service):
        # The library's connect helper does not close when cancellation lands
        # during pair verification. Own the candidate until its whole handshake
        # succeeds, and never let a broken peer stall cleanup indefinitely.
        with contextlib.suppress(Exception):
            async with asyncio.timeout(WIFI_CLOSE_TIMEOUT):
                await service.close()

    if alt_irks:
        try:
            async with asyncio.timeout(WIFI_PROVIDER_TIMEOUT):
                # The iterator yields a service as soon as its first address
                # arrives, then never yields it again. Collect the bounded
                # browse window so a later IPv4 answer is not lost behind IPv6.
                answers = await bonjour.browse_remotepairing(timeout=BONJOUR_TIMEOUT)
                candidates, seen = [], set()
                for answer in answers:
                    identifier = tunnel_service._match_remote_pair_record(answer, alt_irks)
                    if identifier is None:
                        continue
                    for address in answer.addresses:
                        try:
                            host = address.full_ip
                        except OSError:
                            continue  # An adapter may have disappeared since discovery.
                        key = identifier, host, answer.port
                        if key not in seen:
                            seen.add(key)
                            candidates.append(key)
                candidates.sort(key=lambda candidate: ':' in candidate[1])
                for identifier, host, port in candidates:
                    service = tunnel_service.RemotePairingTunnelService(identifier, host, port)
                    original_validate = service._validate_pairing
                    async def validate_pairing(original=original_validate):
                        nonlocal pairing_rejected
                        valid = await original()
                        if valid is False:
                            pairing_rejected = True
                        return valid
                    # Keep the library's cryptographic validation unchanged;
                    # distinguish its explicit rejection from an interrupted
                    # connection, which raises the same exception downstream.
                    service._validate_pairing = validate_pairing
                    try:
                        # Bound pair verification too, not just the library's
                        # initial TCP dial. Return immediately on first success.
                        async with asyncio.timeout(WIFI_CONNECT_TIMEOUT):
                            await service.connect(autopair=False)
                    except BaseException as error:
                        await close_candidate(service)
                        if not isinstance(error, (ConnectionTerminatedError, asyncio.IncompleteReadError,
                                                  TimeoutError, OSError)):
                            raise
                    else:
                        return service, None
                    finally:
                        service._validate_pairing = original_validate
        except TimeoutError:
            pass
    if pairing_rejected:
        raise WifiPairingRejectedError('Wi-Fi pairing rejected. Reconnect USB once to repair Wi-Fi.')
    raise WifiNotFoundError(
        "The iPhone was not found on the network. Put the PC and the iPhone on the same Wi-Fi, "
        "keep the iPhone unlocked, and set that Wi-Fi to Private in Windows settings."
    )


class WifiNotFoundError(RuntimeError):
    pass


class WifiPairingRejectedError(RuntimeError):
    pass


def wifi_tunnel(udid: str):
    """An RSD tunnel to ``udid`` over Wi-Fi, used like ``PreferredRsdTunnel``."""
    from pymobiledevice3.remote import tunnel_service, userspace_tunnel

    class WifiRsdTunnel(userspace_tunnel.UserspaceRsdTunnel):
        # The base class always starts from USB (usbmux); swap in the network
        # provider for the duration of this tunnel's setup only.
        async def _aopen_locked(self):
            original = userspace_tunnel._create_no_root_tunnel_provider
            original_connection = tunnel_service.create_connection
            userspace_tunnel._create_no_root_tunnel_provider = _wifi_provider
            # The dependency makes one blocking socket dial during TCP tunnel
            # setup. Bound that call separately: an asyncio deadline cannot
            # interrupt a blocking OS connect on the event-loop thread.
            tunnel_service.create_connection = functools.partial(original_connection, timeout=WIFI_TCP_TIMEOUT)
            try:
                async with asyncio.timeout(WIFI_STARTUP_TIMEOUT):
                    return await super()._aopen_locked()
            finally:
                tunnel_service.create_connection = original_connection
                userspace_tunnel._create_no_root_tunnel_provider = original

    return WifiRsdTunnel(serial=udid, autopair=False)
