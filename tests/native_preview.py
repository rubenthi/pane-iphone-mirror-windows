"""Disposable UI test instance, with no device operations and no release update checks."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from collections import deque

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
from native_desktop import input_desktop_name, visible_test_desktop
original_status = shell.status
resize_timings = []
resize_paints = []
resize_samples = []
sample_until = 0
original_command = shell.command
command_history = deque(maxlen=120)


def test_monitors():
    from System.Windows.Forms import Screen
    shell.u.MonitorFromRect.argtypes = [ctypes.POINTER(W.RECT), W.DWORD]
    shell.u.MonitorFromRect.restype = W.HANDLE
    shcore = ctypes.WinDLL('shcore')
    shcore.GetDpiForMonitor.argtypes = [W.HANDLE, ctypes.c_int, ctypes.POINTER(W.UINT), ctypes.POINTER(W.UINT)]
    shcore.GetDpiForMonitor.restype = ctypes.c_long
    rows = []
    for index, screen in enumerate(Screen.AllScreens):
        bounds = screen.Bounds
        rect = W.RECT(bounds.Left, bounds.Top, bounds.Right, bounds.Bottom)
        monitor = shell.u.MonitorFromRect(ctypes.byref(rect), 2)
        x, y = W.UINT(), W.UINT()
        result = shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(x), ctypes.byref(y))
        if result != 0:
            raise OSError('Could not read test monitor density.')
        rows.append({'index': index, 'name': screen.DeviceName, 'dpi': x.value})
    return rows


def timed_command(payload):
    global sample_until
    if shell._form is None or shell._form.InvokeRequired:
        command_history.append({'action': payload.get('action'),
                                'height': payload.get('height'),
                                'corner': payload.get('corner'),
                                'timestamp': round(time.monotonic(), 6)})
    if payload.get('action') == 'test-monitor':
        # This route exists only in the disposable fixture. It can move only
        # this fixture's own HWND and its known-color test backdrop.
        index = payload.get('index')
        if type(index) is not int:
            raise ValueError('Expected a test monitor index.')
        def move():
            from System.Windows.Forms import Screen
            screens = list(Screen.AllScreens)
            if not 0 <= index < len(screens):
                raise ValueError('Unknown test monitor.')
            screen = screens[index]
            shell._test_backdrop.Bounds = screen.Bounds
            work = screen.WorkingArea
            if not shell.u.SetWindowPos(shell.handle, 0, work.Left+48, work.Top+48, 0, 0, 0x0015):
                raise OSError('Could not move the test window.')
            shell._form.BringToFront()
            return {'requested_monitor': screen.DeviceName}
        return shell._on_ui(move)
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
    gdi.GetClipBox.argtypes = [W.HDC, ctypes.POINTER(W.RECT)]
    gdi.GetClipBox.restype = ctypes.c_int
    user.GetForegroundWindow.argtypes=[];user.GetForegroundWindow.restype=W.HWND
    user.GetSystemMetrics.argtypes=[ctypes.c_int];user.GetSystemMetrics.restype=ctypes.c_int
    user.GetThreadDpiAwarenessContext.argtypes=[];user.GetThreadDpiAwarenessContext.restype=W.HANDLE
    user.GetWindowDpiAwarenessContext.argtypes=[W.HWND];user.GetWindowDpiAwarenessContext.restype=W.HANDLE
    user.GetAwarenessFromDpiAwarenessContext.argtypes=[W.HANDLE];user.GetAwarenessFromDpiAwarenessContext.restype=ctypes.c_int
    while not shell._form.IsDisposed:
        if time.perf_counter() < sample_until and not user.IsIconic(shell.handle):
            bounds = W.RECT(); user.GetWindowRect(shell.handle, ctypes.byref(bounds))
            scale = (user.GetDpiForWindow(shell.handle) or 96) / 96
            width, height = bounds.right-bounds.left-round(60*scale), bounds.bottom-bounds.top
            dc = user.GetDC(None)
            try:
                colors = [int(gdi.GetPixel(dc, bounds.left+round(width*x), bounds.top+round(height*y)))
                          for x in (.2, .5, .8) for y in (.2, .5, .8)]
                white = sum(color != 0xffffffff and all((color >> shift & 255) > 245
                            for shift in (0, 8, 16)) for color in colors)
                resize_paints.append(white)
                clip = W.RECT()
                clip_type = gdi.GetClipBox(dc, ctypes.byref(clip))
                resize_samples.append({'rect':[bounds.left,bounds.top,bounds.right,bounds.bottom],
                    'clipType':clip_type,'clip':[clip.left,clip.top,clip.right,clip.bottom],
                    'inputDesktop':input_desktop_name() if 0xffffffff in colors else None,
                    'colors':colors,'dc':int(dc or 0),'foreground':int(user.GetForegroundWindow() or 0),
                    'window':int(shell.handle),'dpi':round(scale*96),
                    'virtualScreen':[user.GetSystemMetrics(i) for i in (76,77,78,79)],
                    'threadAwareness':user.GetAwarenessFromDpiAwarenessContext(user.GetThreadDpiAwarenessContext()),
                    'windowAwareness':user.GetAwarenessFromDpiAwarenessContext(user.GetWindowDpiAwarenessContext(shell.handle))})
            finally:
                user.ReleaseDC(None, dc)
        time.sleep(.01)

def checked_status():
    if not shell.handle:
        return original_status()
    def inspect():
        # Read geometry and its native region in the same UI-thread turn.
        state = original_status()
        state['windows_identity'] = getattr(shell, '_test_identity', None)
        state['resize_timings'] = resize_timings.copy()
        state['resize_paints'] = resize_paints.copy()
        samples = resize_samples.copy()
        invalid = [sample for sample in samples if 0xffffffff in sample['colors']]
        state['resize_samples'] = (invalid or samples)[-3:]
        state['resize_invalid_samples'] = len(invalid)
        state['menu_open'] = shell.menu_open
        state['command_history'] = list(command_history)
        origin, view = W.POINT(), W.RECT()
        shell.u.ClientToScreen(shell.handle, ctypes.byref(origin))
        shell.u.GetWindowRect(shell._form.webview.Handle.ToInt64(), ctypes.byref(view))
        state['web_offset'] = [view.left-origin.x, view.top-origin.y]
        state['minimized'] = bool(shell.u.IsIconic(shell.handle))
        bounds = W.RECT(); shell.u.GetWindowRect(shell.handle, ctypes.byref(bounds))
        state['native_rect'] = [bounds.left, bounds.top, bounds.right, bounds.bottom]
        from System.Windows.Forms import Screen
        state['monitor'] = Screen.FromHandle(shell._form.Handle).DeviceName
        state['monitors'] = test_monitors()
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
        from System.Drawing import Color, Icon
        from System.IO import MemoryStream
        from System.Windows.Forms import Form, FormBorderStyle, Screen, FormStartPosition
        shell32 = ctypes.WinDLL('shell32')
        shell32.GetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        shell32.GetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        ole32 = ctypes.WinDLL('ole32')
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        pointer = ctypes.c_void_p()
        result = shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(pointer))
        try:
            app_id = ctypes.wstring_at(pointer.value) if result == 0 else None
        finally:
            if pointer.value:
                ole32.CoTaskMemFree(pointer)
        def icon_bytes(icon):
            stream = MemoryStream()
            try:
                icon.Save(stream)
                return bytes(stream.ToArray())
            finally:
                stream.Dispose()
        expected_icon = Icon(str(app.APP_ICON))
        try:
            matches = icon_bytes(window.native.Icon) == icon_bytes(expected_icon)
        finally:
            expected_icon.Dispose()
        shell.u.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        shell.u.SendMessageW.restype = ctypes.c_ssize_t
        shell._test_identity = {'app_id': app_id, 'form_icon_matches': matches,
                                'small_icon': bool(shell.u.SendMessageW(shell.handle, 0x007f, 0, 0)),
                                'large_icon': bool(shell.u.SendMessageW(shell.handle, 0x007f, 1, 0))}
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
with visible_test_desktop():
    app.main()
