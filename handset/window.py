"""A shaped Windows shell around Pane's own WebView2 window.

Only the process started by Pane is eligible. No global browser changes.
The region clips both drawing and hit testing outside the phone/drawer outline.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import math
import os
import threading

DRAWER = 416
TAB = 60
DEFAULT_ASPECT = 390 / 844
SCREEN_CHROME = 14  # CSS: symmetric 7px bezel on all four sides
PANEL_MIN_HEIGHT = 540


def _native_pointer(handle):
    # pythonnet otherwise selects IntPtr(Int32), which rejects GDI handles
    # with bit 31 set. Preserve the full native pointer width explicitly.
    from System import Int64, IntPtr
    return IntPtr(Int64(ctypes.c_ssize_t(handle).value))


def dimensions(aspect=DEFAULT_ASPECT, expanded=False, work_width=1920, work_height=1080, preferred_height=760):
    if type(expanded) is not bool or type(aspect) not in (float, int) or not math.isfinite(aspect) or not .35 <= aspect <= 2.5:
        raise ValueError('Invalid window layout.')
    extra = TAB
    preferred_height = max(PANEL_MIN_HEIGHT, preferred_height) if expanded else preferred_height
    height = max(120, min(preferred_height, work_height - 48, (work_width - extra - 48 - SCREEN_CHROME) / aspect + SCREEN_CHROME))
    # Derive width from the integer height Windows actually receives. Using
    # a fractional drag height here distorts wider displays after rounding.
    height = round(height)
    width = round((height - SCREEN_CHROME) * aspect) + SCREEN_CHROME
    # Reserve 158px for the three menu buttons and grip plus an 8px top gutter.
    rail_scale = min(1, max(.15, (height-174)/292))
    rail_top = max(166, (height-288*rail_scale)/2)
    return {'phone_width': width, 'height': round(height), 'width': width + extra, 'expanded': expanded,
            'rail_scale': rail_scale, 'rail_top': rail_top}


class FloatingWindow:
    def __init__(self):
        self.handle = None
        self._form = None
        self.expanded = False
        self.aspect = DEFAULT_ASPECT
        self.pinned = False
        self.preferred_height = 760
        self.menu_open = False
        self.maximized = False
        self._restore_height = self.preferred_height
        self._lock = threading.RLock()
        self._geometry = dimensions()
        self._clip_children = set()
        self._repair_queued = False
        if os.name != 'nt':
            return
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.g = ctypes.WinDLL('gdi32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = {
            'EnumChildWindows': ([W.HWND, self.callback, W.LPARAM], W.BOOL),
            'SetWindowRgn': ([W.HWND, W.HRGN, W.BOOL], ctypes.c_int),
            'GetWindowThreadProcessId': ([W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            'IsIconic': ([W.HWND], W.BOOL),
            'ClientToScreen': ([W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
            'IsWindowVisible': ([W.HWND], W.BOOL),
            'IsWindow': ([W.HWND], W.BOOL),
            'GetWindowLongPtrW': ([W.HWND, ctypes.c_int], ctypes.c_ssize_t),
            'SetWindowLongPtrW': ([W.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            'SetWindowPos': ([W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT], W.BOOL),
            'RedrawWindow': ([W.HWND, ctypes.c_void_p, W.HRGN, W.UINT], W.BOOL),
            'GetWindowRgn': ([W.HWND, W.HRGN], ctypes.c_int),
            'GetWindowRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            'GetDpiForWindow': ([W.HWND], W.UINT),
            'ShowWindow': ([W.HWND, ctypes.c_int], W.BOOL),
            'SetForegroundWindow': ([W.HWND], W.BOOL),
            'PostMessageW': ([W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            'GetCursorPos': ([ctypes.POINTER(W.POINT)], W.BOOL),
            'SystemParametersInfoW': ([W.UINT, W.UINT, ctypes.c_void_p, W.UINT], W.BOOL),
            'MonitorFromWindow': ([W.HWND, W.DWORD], W.HANDLE),
            'GetMonitorInfoW': ([W.HANDLE, ctypes.c_void_p], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.u, name); fn.argtypes = args; fn.restype = result
        self.g.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        self.g.CreateRoundRectRgn.restype = W.HRGN
        self.g.CombineRgn.argtypes = [W.HRGN, W.HRGN, W.HRGN, ctypes.c_int]
        self.g.CombineRgn.restype = ctypes.c_int
        self.g.EqualRgn.argtypes = [W.HRGN, W.HRGN]
        self.g.EqualRgn.restype = W.BOOL
        self.g.OffsetRgn.argtypes = [W.HRGN, ctypes.c_int, ctypes.c_int]
        self.g.OffsetRgn.restype = ctypes.c_int
        self.g.DeleteObject.argtypes = [W.HANDLE]
        self.g.DeleteObject.restype = W.BOOL

    def _on_ui(self, callback):
        # WinForms owns the HWND and Region. Change both on its UI thread so
        # framework layout/handle recreation cannot discard an unmanaged region.
        from System import Action
        result, errors = [], []
        def run():
            try:
                self.handle = self._form.Handle.ToInt64()
                result.append(callback())
            except Exception as error:
                errors.append(error)
        if self._form.InvokeRequired:
            self._form.Invoke(Action(run))
        else:
            run()
        if errors:
            raise errors[0]
        return result[0]

    def attach(self, window):
        if os.name != 'nt' or window.native is None:
            return False
        self._form = window.native
        def configure():
            pid = W.DWORD()
            self.u.GetWindowThreadProcessId(self.handle, ctypes.byref(pid))
            if pid.value != os.getpid():
                raise ValueError('The Pane window must belong to this process.')
            # Disable DWM's rectangular frame/shadow on the actual WebView form.
            dwm = ctypes.WinDLL('dwmapi')
            dwm.DwmSetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
            for attribute, value in ((2, 1), (33, 1), (34, 0xFFFFFFFE), (38, 1)):
                setting = W.DWORD(value)
                dwm.DwmSetWindowAttribute(self.handle, attribute, ctypes.byref(setting), ctypes.sizeof(setting))
            # pywebview enables Mica in dark mode. DWM paints that backdrop
            # even outside an otherwise correctly hit-tested window region.
            def disable_backdrop(*_):
                none = W.DWORD(1)  # DWMSBT_NONE
                dwm.DwmSetWindowAttribute(self.handle, 38, ctypes.byref(none), ctypes.sizeof(none))
            self._form.Activated += disable_backdrop
            from System.Drawing import Color
            from System.Windows.Forms import Timer
            # Newly exposed pixels should match Pane while WebView2 repaints.
            self._form.BackColor = Color.FromArgb(11, 21, 37)
            self._form.webview.DefaultBackgroundColor = Color.Transparent
            self.layout(False, DEFAULT_ASPECT)
            # Native WebView2 child bounds can trail the form resize. Repair
            # after its resize events instead of waiting for the watchdog.
            self._form.Resize += self._queue_region_repair
            self._form.webview.Resize += self._queue_region_repair
            self._form.webview.HandleCreated += self._queue_region_repair
            # WebView2 can recreate its child renderer after navigation, DPI or
            # GPU changes. Clip its native hosts as well as the WinForms parent.
            self._shape_timer = Timer()
            self._shape_timer.Interval = 400
            self._shape_timer.Tick += lambda *_: self._repair_regions()
            self._shape_timer.Start()
            self._form.FormClosed += lambda *_: self._shape_timer.Stop()
            return True
        return self._on_ui(configure)

    def _queue_region_repair(self, *_):
        if self._repair_queued or self._form.IsDisposed or not self._form.IsHandleCreated:
            return
        from System import Action
        self._repair_queued = True
        def repair():
            self._repair_queued = False
            if not self._form.IsDisposed:
                self._repair_regions()
        self._form.BeginInvoke(Action(repair))

    def status(self):
        return {**self._geometry, 'native': bool(self.handle), 'pinned': self.pinned, 'maximized': self.maximized}

    def layout(self, expanded, aspect, *, resize_corner=None):
        if self._form is not None and self._form.InvokeRequired:
            return self._on_ui(lambda: self.layout(expanded, aspect, resize_corner=resize_corner))
        with self._lock:
            if self.handle and self.u.IsIconic(self.handle):
                return self.status()
            geometry = dimensions(aspect, expanded, preferred_height=self.preferred_height)
            if self.handle:
                scale = (self.u.GetDpiForWindow(self.handle) or 96) / 96
                work = W.RECT()
                self.u.SystemParametersInfoW(48, 0, ctypes.byref(work), 0)
                class MonitorInfo(ctypes.Structure):
                    _fields_ = [('size', W.DWORD), ('monitor', W.RECT), ('work', W.RECT), ('flags', W.DWORD)]
                info = MonitorInfo(); info.size = ctypes.sizeof(info)
                if self.u.GetMonitorInfoW(self.u.MonitorFromWindow(self.handle, 2), ctypes.byref(info)):
                    work = info.work
                rect = W.RECT(); self.u.GetWindowRect(self.handle, ctypes.byref(rect))
                available_width, available_height = work.right-work.left, work.bottom-work.top
                if resize_corner:
                    available_width = rect.right-work.left if 'w' in resize_corner else work.right-rect.left
                    available_height = rect.bottom-work.top if 'n' in resize_corner else work.bottom-rect.top
                geometry = dimensions(aspect, expanded, available_width/scale, available_height/scale, self.preferred_height)
                width, height = round(geometry['width']*scale), round(geometry['height']*scale)
                if resize_corner:
                    x = rect.right-width if 'w' in resize_corner else rect.left
                    y = rect.bottom-height if 'n' in resize_corner else rect.top
                else:
                    x = min(max(rect.left, work.left), work.right-width)
                    y = min(max(rect.top, work.top), work.bottom-height)
                def rounded(left, top, right, bottom, radius):
                    return self.g.CreateRoundRectRgn(*(round(v*scale) for v in (left, top, right, bottom, radius*2, radius*2)))
                pw, h = geometry['phone_width'], geometry['height']
                region = rounded(0, 0, pw, h, 44)
                rail_top, rail_scale = geometry['rail_top'], geometry['rail_scale']
                parts = [rounded(pw-16, rail_top-50, pw+60, rail_top+292*rail_scale, 28)]
                if self.menu_open:
                    parts.append(rounded(pw+8, rail_top-152, pw+52, rail_top-10, 12))
                for part in parts:
                    self.g.CombineRgn(region, region, part, 2)
                    self.g.DeleteObject(part)
                from System.Drawing import Region
                try:
                    managed = Region.FromHrgn(_native_pointer(region))
                    previous = self._form.Region
                    self._form.Region = managed
                    previous_web = self._form.webview.Region
                    self._form.webview.Region = managed.Clone()
                    if previous_web is not None:
                        previous_web.Dispose()
                    if previous is not None:
                        previous.Dispose()
                finally:
                    self.g.DeleteObject(region)
                # Apply the new clipping before exposing resized pixels. Keep
                # parent and WebView bounds in one WinForms UI-thread operation;
                # never copy the old backing bitmap or recreate the DWM frame.
                if width != rect.right-rect.left or height != rect.bottom-rect.top:
                    self.u.SetWindowPos(self.handle, -1 if self.pinned else -2, x, y, width, height, 0x0110)
                    self._form.webview.SetBounds(0, 0, width, height)
                    # Queue paint after the browser receives its resize event.
                    # UPDATENOW paints the old browser surface at the new size.
                    self.u.RedrawWindow(self.handle, None, None, 0x0081)
                else:
                    self.u.SetWindowPos(self.handle, -1 if self.pinned else -2, 0, 0, 0, 0, 0x0013)
            self.aspect, self.expanded, self._geometry = aspect, expanded, geometry
            if self.handle: self._repair_regions()
            return self.status()

    def _repair_regions(self):
        """Restore clipping on the HWNDs actually used by WebView2 composition."""
        if self._form.IsDisposed or self._form.Region is None:
            return
        self.handle = self._form.Handle.ToInt64()
        if self.u.IsIconic(self.handle):
            return
        # The WebView is DockStyle.Fill. During minimize Windows parks the
        # form offscreen. On restore its child can retain that parking offset
        # even though WinForms still reports the correct managed bounds.
        view = self._form.webview.Handle.ToInt64()
        origin, bounds = W.POINT(), W.RECT()
        if self.u.ClientToScreen(self.handle, ctypes.byref(origin)) and self.u.GetWindowRect(view, ctypes.byref(bounds)):
            if bounds.left != origin.x or bounds.top != origin.y:
                self.u.SetWindowPos(view, 0, 0, 0, 0, 0, 0x0015)  # move only
        from System.Drawing import Graphics
        graphics = Graphics.FromHwnd(self._form.Handle)
        try:
            expected = self._form.Region.GetHrgn(graphics).ToInt64()
        finally:
            graphics.Dispose()
        parent = W.RECT(); self.u.GetWindowRect(self.handle, ctypes.byref(parent))
        def apply(hwnd, dx=0, dy=0):
            desired = self.g.CreateRoundRectRgn(0, 0, 1, 1, 0, 0)
            actual = self.g.CreateRoundRectRgn(0, 0, 1, 1, 0, 0)
            try:
                self.g.CombineRgn(desired, expected, expected, 5)  # RGN_COPY
                self.g.OffsetRgn(desired, -dx, -dy)
                matches = self.u.GetWindowRgn(hwnd, actual) and self.g.EqualRgn(desired, actual)
                if not matches:
                    if not self.u.SetWindowRgn(hwnd, desired, True):
                        raise OSError('Windows could not apply the Pane outline.')
                    desired = None  # Windows owns it after success.
            finally:
                if desired: self.g.DeleteObject(desired)
                self.g.DeleteObject(actual)
        try:
            apply(self.handle)
            seen = set()
            @self.callback
            def child(hwnd, _):
                rect = W.RECT(); self.u.GetWindowRect(hwnd, ctypes.byref(rect))
                seen.add(hwnd)
                # Only full-surface browser hosts, never small controls/popups.
                full_size = abs((rect.right-rect.left)-(parent.right-parent.left)) <= 2 and abs((rect.bottom-rect.top)-(parent.bottom-parent.top)) <= 2
                if full_size or hwnd in self._clip_children:
                    # A previously identified surface still needs the new clip
                    # while its asynchronous bounds lag behind the parent.
                    self._clip_children.add(hwnd)
                    apply(hwnd, rect.left-parent.left, rect.top-parent.top)
                return True
            self.u.EnumChildWindows(self.handle, child, 0)
            self._clip_children.intersection_update(seen)
        finally:
            self.g.DeleteObject(expected)

    def command(self, payload):
        if self._form is not None and self._form.InvokeRequired:
            return self._on_ui(lambda: self.command(payload))
        action = payload.get('action')
        if action == 'resize':
            height = payload.get('height')
            if type(height) not in (float, int) or not math.isfinite(height) or not 360 <= height <= 10000:
                raise ValueError('Invalid window height.')
            corner = payload.get('corner', 'se')
            if corner not in ('nw', 'ne', 'sw', 'se'):
                raise ValueError('Invalid resize corner.')
            self.preferred_height = max(PANEL_MIN_HEIGHT, height) if self.expanded else height
            self.maximized = False
            return self.layout(self.expanded, self.aspect, resize_corner=corner)
        if action == 'maximize':
            if not self.maximized:
                self._restore_height = self.preferred_height
            self.maximized = not self.maximized
            self.preferred_height = 10000 if self.maximized else self._restore_height
            return self.layout(self.expanded, self.aspect)
        if action == 'window-menu':
            self.menu_open = payload.get('open') is True
            return self.layout(self.expanded, self.aspect)
        if action == 'layout':
            return self.layout(payload.get('expanded', self.expanded), payload.get('aspect', self.aspect))
        if action not in ('drag', 'move', 'minimize', 'close', 'pin', 'focus'):
            raise ValueError('Unknown window action.')
        if not self.handle:
            raise ValueError('Native window controls are unavailable in browser mode.')
        if action == 'pin':
            self.pinned = not self.pinned
            return self.layout(self.expanded, self.aspect)
        if action == 'drag':
            rect = W.RECT(); self.u.GetWindowRect(self.handle, ctypes.byref(rect))
            self._drag_origin = (rect.left, rect.top)
        elif action == 'move':
            dx, dy = payload.get('dx'), payload.get('dy')
            if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000 for v in (dx, dy)):
                raise ValueError('Invalid drag offset.')
            if not hasattr(self, '_drag_origin'):
                raise ValueError('Start dragging before moving.')
            scale = (self.u.GetDpiForWindow(self.handle) or 96) / 96
            x, y = self._drag_origin
            self.u.SetWindowPos(self.handle, 0, round(x+dx*scale), round(y+dy*scale), 0, 0, 0x0015)
        elif action == 'minimize':
            self.u.ShowWindow(self.handle, 6)
        elif action == 'close':
            self.u.PostMessageW(self.handle, 0x0010, 0, 0)
        elif action == 'focus':
            self.u.ShowWindow(self.handle, 9)
            self.u.SetForegroundWindow(self.handle)
        return self.status()


shell = FloatingWindow()
