"""Status and identity reads for a plugged-in iPhone."""

from __future__ import annotations

import asyncio
import socket
import subprocess
from pathlib import Path

from handset.mux import MuxError, list_devices, usb_devices

INFO_KEYS = (
    "DeviceName",
    "DeviceClass",
    "ProductType",
    "ProductVersion",
    "BuildVersion",
    "HardwareModel",
    "ModelNumber",
    "UniqueDeviceID",
    "SerialNumber",
    "PasswordProtected",
    "ActivationState",
    "TelephonyCapability",
)

DRIVER_PATHS = (
    Path(r"C:\Program Files\Common Files\Apple\Mobile Device Support"),
    Path(r"C:\Program Files (x86)\Common Files\Apple\Mobile Device Support"),
)


def driver_status() -> dict:
    found = [str(path) for path in DRIVER_PATHS if path.exists()]
    service = _service_state("Apple Mobile Device Service")
    mux = _mux_listening()
    ready = bool(found) or service == "RUNNING" or mux
    if ready:
        detail = "Apple's USB service is running. Plug in the iPhone, unlock it, and tap Trust."
    else:
        detail = (
            "Windows has no Apple USB driver, so it cannot see an iPhone yet. "
            "Install Apple Devices from the Microsoft Store, then reconnect the phone and tap Trust."
        )
    return {"ready": ready, "paths": found, "service": service, "detail": detail}


def snapshot() -> dict:
    driver = driver_status()
    devices: list[dict] = []
    error = None
    try:
        devices = usb_devices(list_devices())
    except MuxError as exc:
        error = str(exc)
    developer_mode = developer_mode_enabled(devices[0]["udid"]) if len(devices) == 1 else None
    return {
        "library": {"ready": True, "version": "usbmux"},
        "driver": driver,
        "devices": devices,
        "developerMode": developer_mode,
        "error": error,
    }


def read_handset(udid: str) -> dict:
    matches = [device for device in list_devices() if device["udid"] == udid]
    if not matches:
        raise MuxError("That iPhone is not connected.")
    connection = (usb_devices(matches) or matches)[0]["connection"]
    try:
        return asyncio.run(_read_existing_session(udid, connection))
    except Exception as error:
        raise MuxError("Could not verify the iPhone session. Unlock it and reconnect.") from error


async def _read_existing_session(udid: str, connection: str) -> dict:
    from pymobiledevice3.lockdown import create_using_usbmux

    # Unpaired devices can answer QueryType and GetValue. The library's
    # paired flag is set only after validating the record and starting a session.
    async with asyncio.timeout(8):
        lockdown = await create_using_usbmux(serial=udid, connection_type=connection, autopair=False)
        try:
            if not lockdown.paired:
                return {"udid": udid, "paired": False, "info": {}, "error": _lockdown_error("InvalidHostID")}
            info = {key: lockdown.all_values[key] for key in INFO_KEYS if key in lockdown.all_values}
            return {"udid": udid, "paired": True, "info": info}
        finally:
            await lockdown.close()


def _lockdown_error(code: str) -> str:
    messages = {
        "InvalidHostID": "This PC is not paired with the iPhone. Unlock the phone and tap Trust.",
        "PairingDialogResponsePending": "Tap Trust on the iPhone.",
        "UserDeniedPairing": "Trust was declined on the iPhone.",
        "PasswordProtected": "Unlock the iPhone and try again.",
    }
    return messages.get(code, code)


def developer_mode_enabled(udid: str) -> bool | None:
    async def check() -> bool | None:
        from pymobiledevice3.lockdown import create_using_usbmux

        async with asyncio.timeout(8):
            lockdown = await create_using_usbmux(serial=udid, connection_type="USB", autopair=False)
            try:
                if not lockdown.paired:
                    return None
                value = await lockdown.get_value(domain="com.apple.security.mac.amfi", key="DeveloperModeStatus")
                return value if isinstance(value, bool) else None
            finally:
                await lockdown.close()

    try:
        return asyncio.run(check())
    except Exception:
        return None


def _mux_listening() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        sock.connect(("127.0.0.1", 27015))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _service_state(name: str) -> str | None:
    try:
        completed = subprocess.run(
            ["sc", "query", name],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in completed.stdout.splitlines():
        if "STATE" in line:
            parts = line.split()
            if parts:
                return parts[-1]
    return None
