"""Run on macOS with Xcode and the Python cryptography dependency installed."""
import asyncio
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from handset.bulk import BulkSender, LAN_NETWORKS, MAX_BLOCK


async def exercise(binary, work):
    phone = await asyncio.create_subprocess_exec(
        binary, work, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    file_id = "a" * 32
    # Exceeds 64 complete blocks and ends partway through the final block.
    data = bytes(range(251)) * 67001
    name = "interop sample.dat"

    async def control(operation, **values):
        phone.stdin.write((json.dumps({"op": operation, "id": file_id, **values}) + "\n").encode())
        await phone.stdin.drain()
        return json.loads(await asyncio.wait_for(phone.stdout.readline(), 10))

    try:
        await control("begin", name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        # Swift deliberately rejects loopback offers in production. Both peers
        # run on this Mac using one local private address and an ephemeral port.
        ifconfig = subprocess.check_output(["/sbin/ifconfig"], text=True)
        addresses = re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)\b", ifconfig)
        host = next((ip for ip in addresses if any(ipaddress.ip_address(ip) in net for net in LAN_NETWORKS)), None)
        if host is None:
            raise RuntimeError("Mac runner needs one private IPv4 address for the production endpoint policy")
        with BulkSender(len(data), hosts=[host], bind_host=host) as desktop:
            started = await control("bulk-write", endpoint=desktop.endpoint)
            assert started == {"ok": True, "offset": 0}, started
            await desktop.accept()
            start = time.perf_counter()
            for at in range(0, len(data), MAX_BLOCK):
                await desktop.write(at, data[at:at + MAX_BLOCK])
        stopped = await control("bulk-write-stop")
        assert stopped.get("offset") == len(data), stopped
        assert (await control("finish"))["ok"]
        assert (await control("finish"))["completed"]
        received = work / "Received"
        assert list(received.iterdir()) == [received / name]
        assert (received / name).read_bytes() == data
        elapsed = time.perf_counter() - start
        print(f"PASS: Python BulkSender to Swift Companion over pinned TLS, {len(data)} bytes, "
              f"{elapsed:.3f}s through durable finish verification ({len(data) / elapsed / 2**20:.2f} MiB/s), "
              f"SHA-256 {hashlib.sha256(data).hexdigest()}, duplicate finish verified")
    finally:
        phone.stdin.close()
        try:
            await asyncio.wait_for(phone.wait(), timeout=3)
        except TimeoutError:
            phone.kill()
            await phone.wait()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pane-interop-") as directory:
        work = Path(directory)
        binary = work / "bulk-companion"
        subprocess.run(["xcrun", "swiftc", "-D", "DEBUG",
                        ROOT / "ios/PaneFiles/BulkUpload.swift", ROOT / "ios/PaneFiles/Companion.swift",
                        ROOT / "tests/companion-interop/main.swift", "-o", binary], check=True)
        asyncio.run(exercise(binary, work))

