"""Xcode's device screen, on Windows.

After Trust, iOS 17.4+ exposes CoreDeviceProxy over the USB service broker,
or RemotePairing over Wi-Fi once paired for it. Either tunnel carries a
display service. The phone then sends the screen as HEVC video. The browser
decodes it.
"""

from __future__ import annotations

import asyncio
import threading

from handset.device import developer_mode_enabled
from handset.mux import MuxError, list_devices
from handset.wifi import wifi_paired_udids, wifi_tunnel

DEVELOPER_MODE_MESSAGE = (
    "The picture stays black because Developer Mode is off. On the iPhone open Settings, "
    "Privacy & Security, Developer Mode, turn it on, and let the phone restart. After it boots, "
    "unlock it, tap Turn On, then press Show screen again."
)

VIEW_URL = "http://127.0.0.1:8766/"
_LOCK = threading.Lock()
_COMMAND_LOCK = threading.RLock()
_WORKER = None
_LOOP = None
_TASK = None
_READY = threading.Event()
_STATE = {"phase": "idle", "udid": None, "url": None, "error": None, "note": None, "transport": None}


def screen_status() -> dict:
    with _LOCK:
        return dict(_STATE)


def restart_screen(udid: str | None = None) -> dict:
    with _COMMAND_LOCK:
        return _restart_screen(udid)


def _restart_screen(udid: str | None = None) -> dict:
    """Nudge the device encoder and keep the HTTP stream on 8766 alive."""
    import http.client
    from handset.server import upstream_authorization

    state = screen_status()
    if state['phase'] in {'starting', 'running'} and udid and udid != state['udid']:
        return {**state, 'error': 'Select the active device before restarting its stream.'}
    chosen = (udid or "").strip() or state.get("udid") or _only_udid()
    nudged = False
    for path in ("/restart", "/pli"):
        conn = http.client.HTTPConnection("127.0.0.1", 8766, timeout=20)
        try:
            conn.request("POST", path, body=b"", headers={"Authorization": upstream_authorization()})
            response = conn.getresponse()
            response.read()
            nudged = 200 <= response.status < 300
            if nudged:
                break
        except (OSError, http.client.HTTPException):
            continue
        finally:
            conn.close()
    with _LOCK:
        running = _STATE.get("phase") == "running"
    if running:
        if not nudged:
            return _set(error="Restart failed: the stream did not accept the request.", note=None)
        return _set(error=None, note="Stream restart accepted.")
    if chosen:
        return start_screen(chosen, _STATE.get("transport") or "auto")
    return _set(error="Connect the iPhone first, then start mirroring.")


def start_screen(udid: str | None, transport: str = "auto") -> dict:
    with _COMMAND_LOCK:
        return _start_screen(udid, transport)


def _start_screen(udid: str | None, transport: str) -> dict:
    global _WORKER
    def rejected(message):
        if _WORKER is not None and _WORKER.is_alive():
            return {**screen_status(), 'error': message}
        return _set(phase='error', udid=None, url=None, error=message, note=None, transport=None)
    usb = _usb_udids()
    wifi = wifi_paired_udids()
    chosen = (udid or "").strip() or _only_udid(usb, wifi, transport)
    if not chosen:
        if transport == "wifi":
            return rejected("Set up Wi-Fi once with the cable plugged in.")
        return rejected("Connect the iPhone first.")

    if transport == "auto":
        transport = "usb" if chosen in usb else "wifi"
    if transport == "usb" and chosen not in usb:
        return rejected("The iPhone is not on the cable. Plug it in or choose Wi-Fi.")
    if transport == "wifi" and chosen not in wifi:
        return rejected("Set up Wi-Fi once with the cable plugged in.")
    if transport == "usb" and developer_mode_enabled(chosen) is False:
        return rejected(DEVELOPER_MODE_MESSAGE)

    state = screen_status()
    if _WORKER is not None and _WORKER.is_alive():
        if state["udid"] == chosen and state["transport"] == transport:
            return state
        if not stop_screen():
            return {**screen_status(), "error": "Previous stream is still closing. Try again shortly."}
    with _LOCK:
        note = "Looking for the iPhone on Wi-Fi…" if transport == "wifi" else None
        _STATE.update(phase="starting", udid=chosen, url=None, error=None, note=note, transport=transport)
    _READY.clear()
    _WORKER = threading.Thread(target=_run, args=(chosen, transport), name="handset-screen", daemon=True)
    _WORKER.start()
    return screen_status()


def stop_screen() -> bool:
    with _COMMAND_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _set(phase="idle", udid=None, url=None, error=None, note=None, transport=None)
            return True
        if not _READY.wait(5):
            return False
        try:
            _LOOP.call_soon_threadsafe(_TASK.cancel)
        except RuntimeError:
            pass  # The worker finished between the check and cancellation.
        _WORKER.join(10)
        return not _WORKER.is_alive()


def _run(udid: str, transport: str) -> None:
    async def run():
        global _LOOP, _TASK
        _LOOP = asyncio.get_running_loop()
        _TASK = asyncio.current_task()
        _READY.set()
        await _serve(udid, transport)

    try:
        asyncio.run(run())
        _set(phase="idle", udid=udid, url=None, error="The screen stream stopped.")
    except asyncio.CancelledError:
        _set(phase="idle", udid=None, url=None, error=None, note=None, transport=None)
    except Exception as error:
        _set(phase="error", udid=udid, url=None, error=_plain(error))


DISPLAY_SERVICE = "com.apple.coredevice.displayservice"


def _open_tunnel(udid: str, transport: str):
    if transport == "wifi":
        return wifi_tunnel(udid)
    from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel

    return PreferredRsdTunnel(serial=udid, autopair=True)


async def _serve(udid: str, transport: str) -> None:
    from pymobiledevice3.remote.core_device.screen_stream import ScreenStreamServer
    from pymobiledevice3.services.mobile_image_mounter import auto_mount

    for attempt in range(2):
        async with _open_tunnel(udid, transport) as rsd:
            if DISPLAY_SERVICE in (rsd.peer_info or {}).get("Services", {}):
                await _stream(rsd, udid, ScreenStreamServer)
                return
            if attempt:
                raise RuntimeError(
                    "The developer image mounted, but the iPhone still offers no display service. "
                    "Unplug it, plug it back in, and press Show screen again."
                )
            _set(note="Mounting the developer image on the iPhone. This downloads it the first time.")
            await auto_mount(rsd)


async def _stream(rsd, udid: str, ScreenStreamServer) -> None:
    from pymobiledevice3.remote.core_device.display_service import is_media_in_use_error
    from handset.security import ACCESS_TOKEN

    server = ScreenStreamServer(
        rsd,
        bind="127.0.0.1",
        http_port=8766,
        audio_default_on=False,
        password=ACCESS_TOKEN,
    )

    async def _eager_video_only() -> None:
        # Audio is intentionally disabled; keep this video-only so logs stay clean and
        # the display tunnel still comes up for /codec and /stream.bin.
        try:
            await server._ensure_fresh_stream(force=False)
        except Exception as error:
            if is_media_in_use_error(error):
                raise
            import logging

            logging.getLogger(__name__).warning(
                "eager video start failed (will retry on /codec)",
                exc_info=True,
            )

    server._eager_stream_start = _eager_video_only
    task = asyncio.create_task(server.serve())
    try:
        # serve() performs device preflight before binding; do not claim readiness early.
        for _ in range(300):
            if task.done():
                await task
                return
            try:
                reader, writer = await asyncio.open_connection('127.0.0.1', 8766)
                writer.close()
                await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(.1)
        else:
            raise TimeoutError('The stream server did not become ready.')
        # Preserve the user-selected phone volume; this stream is video-only.
        note = None
        _set(phase="running", udid=udid, url=VIEW_URL, error=None, note=note)
        await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _usb_udids() -> list[str]:
    try:
        return [device["udid"] for device in list_devices()]
    except MuxError:
        return []


def _only_udid(usb: list[str] | None = None, wifi: list[str] | None = None, transport: str = "auto") -> str | None:
    usb = _usb_udids() if usb is None else usb
    wifi = wifi_paired_udids() if wifi is None else wifi
    if transport != "wifi" and len(usb) == 1:
        return usb[0]
    if transport != "usb" and len(wifi) == 1:
        return wifi[0]
    return None


def _set(**values) -> dict:
    with _LOCK:
        _STATE.update(values)
        return dict(_STATE)


def _plain(error: Exception) -> str:
    text = str(error).strip() or type(error).__name__
    name = type(error).__name__
    if name == "WifiNotFoundError":
        return text
    if name in {"ConnectionFailedToUsbmuxdError", "MuxError"} or "27015" in text or "usbmux" in text.lower():
        return "Apple Mobile Device Service is not running. Install Apple Devices, reconnect the iPhone, and tap Trust."
    if name == "UserspaceTunnelUnavailableError":
        return "This phone did not open the display tunnel. It needs iOS 17.4 or later, Trust, and Developer Mode."
    if "CoreDeviceProxy" in text or name == "InvalidServiceError":
        return "The phone did not offer its display tunnel. Turn on Developer Mode, unlock the phone, and tap Trust."
    if name == "DeviceNotFoundError":
        return "The iPhone is not on the cable. Plug it in, unlock it, and press Show screen again."
    if name in {"DeveloperModeIsNotEnabledError", "DeveloperModeError"}:
        return DEVELOPER_MODE_MESSAGE
    if "PasswordProtected" in text or "locked" in text.lower():
        return "Unlock the iPhone and keep it unlocked, then press Show screen again."
    if "PairingDialog" in text or "Trust" in text:
        return "Unlock the iPhone and tap Trust, then show the screen again."
    return text
