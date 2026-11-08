"""Disposable UI test instance, with no device operations and no release update checks."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['PANE_PORT'] = '18776'
os.environ['PANE_DATA_DIR'] = tempfile.mkdtemp(prefix='Pane-ui-test-')
import webview
webview.settings['REMOTE_DEBUGGING_PORT'] = 18777
from handset.state import DATA_DIR, write_json
write_json(DATA_DIR / 'binding.json', {'udid': 'saved-phone', 'token': 'test'})
from handset import server, app, companion_update
app.bluetooth.start_auto = lambda: None
app.bluetooth.stop_auto = lambda: None
companion_update.list_devices = lambda: []
server.snapshot = lambda: {'driver': {'ready': True}, 'library': {'ready': True}, 'devices': [], 'developerMode': None, 'error': None}
server.wifi_paired_udids = lambda: []
# Query the real HWND region, not just CSS or our intended geometry.
from handset.window import shell
import ctypes
from ctypes import wintypes as W
original_status = shell.status
resize_timings = []
resize_paints = []
sample_until = 0
original_command = shell.command


def timed_command(payload):
    global sample_until
    # Only instrument outer bridge calls; command marshals itself to the UI thread.
    outer = payload.get('action') == 'resize' and shell._form is not None and shell._form.InvokeRequired
    started = time.perf_counter()
    if outer:
        sample_until = started + 1
    try:
        return original_command(payload)
    finally:
        if outer:
            resize_timings.append(round((time.perf_counter()-started)*1000, 2))
            sample_until = time.perf_counter() + .15


shell.command = timed_command


def sample_resize_paints():
    # Sample DWM pixels independently of the UI thread. A UI-thread-only test
    # misses white frames painted while a synchronous resize is still running.
    user, gdi = shell.u, shell.g
    user.GetDC.argtypes = [W.HWND]; user.GetDC.restype = W.HDC
    user.ReleaseDC.argtypes = [W.HWND, W.HDC]
    gdi.GetPixel.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
    gdi.GetPixel.restype = W.DWORD
    while not shell._form.IsDisposed:
        if time.perf_counter() < sample_until and not user.IsIconic(shell.handle):
            bounds = W.RECT(); user.GetWindowRect(shell.handle, ctypes.byref(bounds))
            scale = (user.GetDpiForWindow(shell.handle) or 96) / 96
            width, height = bounds.right-bounds.left-round(60*scale), bounds.bottom-bounds.top
            dc = user.GetDC(None)
            try:
                colors = [int(gdi.GetPixel(dc, bounds.left+round(width*x), bounds.top+round(height*y)))
                          for x in (.2, .5, .8) for y in (.2, .5, .8)]
                white = sum(all((color >> shift & 255) > 245 for shift in (0, 8, 16)) for color in colors)
                resize_paints.append(white)
            finally:
                user.ReleaseDC(None, dc)
        time.sleep(.01)

def checked_status():
    if not shell.handle:
        return original_status()
    def inspect():
        # Read geometry and its native region in the same UI-thread turn.
        state = original_status()
        state['resize_timings'] = resize_timings.copy()
        state['resize_paints'] = resize_paints.copy()
        state['menu_open'] = shell.menu_open
        origin, view = W.POINT(), W.RECT()
        shell.u.ClientToScreen(shell.handle, ctypes.byref(origin))
        shell.u.GetWindowRect(shell._form.webview.Handle.ToInt64(), ctypes.byref(view))
        state['web_offset'] = [view.left-origin.x, view.top-origin.y]
        state['minimized'] = bool(shell.u.IsIconic(shell.handle))
        bounds = W.RECT(); shell.u.GetWindowRect(shell.handle, ctypes.byref(bounds))
        state['native_rect'] = [bounds.left, bounds.top, bounds.right, bounds.bottom]
        scale = (shell.u.GetDpiForWindow(shell.handle) or 96) / 96
        region = shell.g.CreateRoundRectRgn(0, 0, 1, 1, 0, 0)
        shell.g.PtInRegion.argtypes = [W.HRGN, ctypes.c_int, ctypes.c_int]
        shell.g.PtInRegion.restype = W.BOOL
        try:
            kind = shell.u.GetWindowRgn(shell.handle, region)
            pw, h, top = state['phone_width'], state['height'], state['rail_top']
            def inside(x, y):
                return bool(shell.g.PtInRegion(region, round(x*scale), round(y*scale)))
            state['region_test'] = {'kind': kind, 'phone': inside(pw/2, h/2),
                    'corner': inside(0, 0), 'above_rail': inside(pw+30, 2),
                    'below_rail': inside(pw+30, h-2), 'rail': inside(pw+30, top+50),
                    'menu': inside(pw+30, top-103),
                    'exact_handle': shell.handle == shell._form.Handle.ToInt64(),
                    'managed_region': shell._form.Region is not None}
            shell.u.GetDC.argtypes = [W.HWND]; shell.u.GetDC.restype = W.HDC
            shell.u.ReleaseDC.argtypes = [W.HWND, W.HDC]
            shell.g.GetPixel.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
            shell.g.GetPixel.restype = W.DWORD
            rect = W.RECT(); shell.u.GetWindowRect(shell.handle, ctypes.byref(rect))
            dc = shell.u.GetDC(None)
            try:
                def pixel(x,y):
                    return int(shell.g.GetPixel(dc, rect.left+round(x*scale),rect.top+round(y*scale)))
                state['pixels'] = {'corner':pixel(1,1), 'above':pixel(pw+30,2), 'below':pixel(pw+30,h-2), 'phone':pixel(pw/2,h/2)}
                state['backdrop_color'] = 35 | (190 << 8) | (90 << 16)
            finally: shell.u.ReleaseDC(None,dc)
            return state
        finally:
            shell.g.DeleteObject(region)
    return shell._on_ui(inspect)

# Put a known color behind Pane so tests inspect actual DWM-composited pixels.
original_attach = shell.attach

def attach_with_backdrop(window):
    result = original_attach(window)
    def create_backdrop():
        from System.Drawing import Color
        from System.Windows.Forms import Form, FormBorderStyle, Screen, FormStartPosition
        backdrop = Form()
        backdrop.FormBorderStyle = getattr(FormBorderStyle, 'None')
        backdrop.StartPosition = FormStartPosition.Manual
        backdrop.BackColor = Color.FromArgb(35, 190, 90)
        backdrop.ShowInTaskbar = False
        backdrop.Bounds = Screen.FromHandle(window.native.Handle).Bounds
        backdrop.Show()
        window.native.BringToFront()
        window.native.FormClosed += lambda *_: backdrop.Close()
        shell._test_backdrop = backdrop
    shell._on_ui(create_backdrop)
    threading.Thread(target=sample_resize_paints, daemon=True).start()
    return result

shell.attach = attach_with_backdrop
shell.status = checked_status
app.main()
