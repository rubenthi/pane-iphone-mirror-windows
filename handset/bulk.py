"""Short-lived, paired TLS bulk upload channel; Bluetooth conveys its pin.

The laptop requests ranges over a TLS connection initiated by the iPhone.
Only an ephemeral per-channel secret (sent inside TLS) admits a peer. No
filesystem names or paths cross this channel, and callers still verify the
complete file hash before publishing it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
from pathlib import Path
import secrets
import socket
import ssl
import struct
import tempfile
import threading
import time

MAX_BLOCK = 256 * 1024
MAX_FILE = 2 * 1024 ** 3
LAN_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                     ('192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12', '169.254.0.0/16'))


class BulkUnavailable(ConnectionError):
    pass


class BulkPaused(Exception):
    pass


class BulkCancelled(Exception):
    pass


def local_addresses():
    """Bounded LAN candidates only; never advertise wildcard/public addresses."""
    values = []
    try:
        records = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        records = []
    for record in records:
        value = record[4][0]
        address = ipaddress.ip_address(value)
        if any(address in network for network in LAN_NETWORKS) and value not in values:
            values.append(value)
    # Home Wi-Fi addresses first, link-local last; do not advertise public,
    # VPN carrier-NAT, documentation or benchmarking ranges as LAN endpoints.
    values.sort(key=lambda value: next(index for index, network in enumerate(LAN_NETWORKS)
                                      if ipaddress.ip_address(value) in network))
    return values[:8]


def _tls_context():
    # Generate a certificate for this channel only. Its DER SHA-256 fingerprint
    # is authenticated by the already encrypted, USB-bound BLE exchange.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Pane local transfer')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=1))
                   .not_valid_after(now + timedelta(hours=1))
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .sign(key, hashes.SHA256()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with tempfile.TemporaryDirectory(prefix='pane-tls-') as directory:
        certificate_path = Path(directory) / 'certificate.pem'
        key_path = Path(directory) / 'key.pem'
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context.load_cert_chain(certificate_path, key_path)
    return context, hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()


def _exact(stream, count, deadline):
    data = bytearray()
    while len(data) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BulkUnavailable('Fast transfer timed out.')
        stream.settimeout(remaining)
        block = stream.recv(count - len(data))
        if not block:
            raise BulkUnavailable('The fast transfer connection closed.')
        data.extend(block)
    return bytes(data)


class BulkReceiver:
    def __init__(self, size, *, hosts=None, bind_host='0.0.0.0', connect_timeout=30, io_timeout=10):
        if type(size) is not int or not 0 <= size <= MAX_FILE:
            raise ValueError('Invalid file size.')
        if not 0 < connect_timeout <= 60 or not 0 < io_timeout <= 60:
            raise ValueError('Invalid transfer timeout.')
        self.size = size
        self.hosts = list(hosts) if hosts is not None else local_addresses()
        if not 1 <= len(self.hosts) <= 8:
            raise BulkUnavailable('No local network address is available.')
        for host in self.hosts:
            address = ipaddress.ip_address(host)
            if address.version != 4 or not (address.is_loopback or any(address in network for network in LAN_NETWORKS)):
                raise ValueError('Invalid local transfer address.')
        self.bind_host = bind_host
        self.connect_timeout = connect_timeout
        self.io_timeout = io_timeout
        self._secret = secrets.token_bytes(32)
        self._listener = self._candidate = self._peer = None
        self._context = None
        self._closed = threading.Event()
        self._operation = threading.Lock()
        self._lifecycle = threading.Lock()
        self._started = False
        self.endpoint = None

    def start(self):
        with self._lifecycle:
            if self._closed.is_set() or self._started:
                raise BulkUnavailable('The fast transfer channel cannot restart.')
            self._started = True
        context, fingerprint = _tls_context()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind((self.bind_host, 0))
            listener.listen(4)
            listener.settimeout(0.25)
            with self._lifecycle:
                if self._closed.is_set():
                    raise BulkUnavailable('The fast transfer listener is closed.')
                self._listener, self._context = listener, context
                self.endpoint = dict(hosts=self.hosts, port=listener.getsockname()[1],
                                     fingerprint=fingerprint, secret=self._secret.hex())
                return dict(self.endpoint)
        except BaseException:
            listener.close()
            raise

    async def accept(self):
        try:
            await asyncio.to_thread(self._accept)
        except asyncio.CancelledError:
            self.close()
            raise

    def _accept(self):
        with self._operation:
            with self._lifecycle:
                if self._listener is None or self._closed.is_set():
                    raise BulkUnavailable('The fast transfer listener is closed.')
                listener, context = self._listener, self._context
            deadline = time.monotonic() + self.connect_timeout
            attempts = 0
            while attempts < 8 and not self._closed.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                candidate = None
                try:
                    try:
                        candidate, _ = listener.accept()
                    except socket.timeout:
                        continue
                    attempts += 1
                    with self._lifecycle:
                        if self._closed.is_set():
                            raise BulkUnavailable('The fast transfer listener is closed.')
                        self._candidate = candidate
                    candidate.settimeout(min(remaining, 2))
                    candidate = context.wrap_socket(candidate, server_side=True, do_handshake_on_connect=False)
                    with self._lifecycle:
                        if self._closed.is_set():
                            raise BulkUnavailable('The fast transfer listener is closed.')
                        self._candidate = candidate
                    candidate.do_handshake()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BulkUnavailable('Fast transfer connection timed out.')
                    candidate.settimeout(min(remaining, 2))
                    if not secrets.compare_digest(_exact(candidate, 32, min(deadline, time.monotonic() + 2)), self._secret):
                        raise BulkUnavailable('Fast transfer authentication failed.')
                    candidate.settimeout(self.io_timeout)
                    candidate.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    with self._lifecycle:
                        if self._closed.is_set():
                            raise BulkUnavailable('The fast transfer listener is closed.')
                        self._peer, self._candidate = candidate, None
                        candidate = None
                        listener.close()
                        self._listener = None
                    return
                except (OSError, BulkUnavailable):
                    pass
                finally:
                    if candidate is not None:
                        candidate.close()
                    self._candidate = None
            raise BulkUnavailable('Fast transfer connection timed out.')

    async def read(self, offset, length):
        if (type(offset) is not int or type(length) is not int or offset < 0
                or not 0 < length <= MAX_BLOCK or offset > self.size or length > self.size - offset):
            raise ValueError('Invalid fast transfer range.')
        try:
            return await asyncio.to_thread(self._read, offset, length)
        except asyncio.CancelledError:
            self.close()
            raise

    def _read(self, offset, length):
        with self._operation:
            stream = self._peer
            if stream is None or self._closed.is_set():
                raise BulkUnavailable('The fast transfer connection is closed.')
            try:
                deadline = time.monotonic() + self.io_timeout
                stream.sendall(struct.pack('!QI', offset, length))
                state, count = struct.unpack('!BI', _exact(stream, 5, deadline))
                if state != 0:
                    if count != 0:
                        raise BulkUnavailable('Invalid fast transfer control frame.')
                    if state == 1:
                        raise BulkPaused()
                    if state == 2:
                        raise BulkCancelled()
                    raise BulkUnavailable('The file is unavailable over Wi-Fi.')
                if not 0 < count <= length:
                    raise BulkUnavailable('Invalid fast transfer block size.')
                return _exact(stream, count, deadline)
            except (OSError, BulkUnavailable) as error:
                self.close()
                raise BulkUnavailable('Fast transfer interrupted. Use Bluetooth to continue.') from error

    def close(self):
        with self._lifecycle:
            self._closed.set()
            streams = [self._listener, self._candidate, self._peer]
            self._listener = self._candidate = self._peer = None
            self._context = None
        for stream in streams:
            if stream is not None:
                try:
                    stream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                stream.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.close()
