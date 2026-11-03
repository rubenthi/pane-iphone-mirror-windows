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
import time

DRAWER = 60  # The drawer overlays the phone; native bounds never expand.
TAB = 60
DEFAULT_ASPECT = 390 / 844


def dimensions(aspect=DEFAULT_ASPECT, expanded=False, work_width=1920, work_height=1080, preferred_height=760):
    if type(expanded) is not bool or type(aspect) not in (float, int) or not math.isfinite(aspect) or not .35 <= aspect <= 2.5:
        raise ValueError('Invalid window layout.')
    extra = TAB
    height = max(120, min(preferred_height, work_height - 48, (work_width - extra - 48 - 6) / aspect + 6))
    width = round((height - 6) * aspect) + 6
    rail_scale = min(1, max(.15, (height-112)/288))
    rail_top = max(52, (height-288*rail_scale)/2)
    return {'phone_width': width, 'height': round(height), 'width': width + extra, 'expanded': expanded,
            'rail_scale': rail_scale, 'rail_top': rail_top}


class FloatingWindow:
    def __init__(self):
        self.handle = None
        self.expanded = False
        self.aspect = DEFAULT_ASPECT
        self.pinned = False
        self.preferred_height = 760
        self.menu_open = False
        self.maximized = False
        self._lock = threading.RLock()
        self._geometry = dimensions()
        if os.name != 'nt':
            return
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.g = ctypes.WinDLL('gdi32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = {
            'EnumWindows': ([self.callback, W.LPARAM], W.BOOL),
            'GetWindowThreadProcessId': ([W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            'IsWindowVisible': ([W.HWND], W.BOOL),
            'IsWindow': ([W.HWND], W.BOOL),
            'GetWindowLongPtrW': ([W.HWND, ctypes.c_int], ctypes.c_ssize_t),
            'SetWindowLongPtrW': ([W.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            'SetWindowPos': ([W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT], W.BOOL),
            'SetWindowRgn': ([W.HWND, W.HRGN, W.BOOL], ctypes.c_int),
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
        self.g.DeleteObject.argtypes = [W.HANDLE]
        self.g.DeleteObject.restype = W.BOOL

    def attach(self, process_id, timeout=15):
        if os.name != 'nt':
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = []
            @self.callback
            def visit(hwnd, _):
                pid = W.DWORD()
                self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == process_id and self.u.IsWindowVisible(hwnd):
                    matches.append(hwnd)
                return True
            self.u.EnumWindows(visit, 0)
            if matches:
                self.handle = matches[0]
                style = self.u.GetWindowLongPtrW(self.handle, -16)
                self.u.SetWindowLongPtrW(self.handle, -16, style & ~0x00CF0000)  # caption, sizing frame, min/max/system menu
                # Remove the separate DWM frame/shadow: the region below is
                # the actual hit-test boundary of the phone and control rail.
                dwm = ctypes.WinDLL('dwmapi')
                dwm.DwmSetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
                for attribute, value in ((2, 1), (33, 1), (34, 0xFFFFFFFE)):
                    setting = W.DWORD(value)
                    dwm.DwmSetWindowAttribute(self.handle, attribute, ctypes.byref(setting), ctypes.sizeof(setting))
                self.layout(False, DEFAULT_ASPECT)
                return True
            time.sleep(.1)
        return False

    def status(self):
        return {**self._geometry, 'native': bool(self.handle), 'pinned': self.pinned, 'maximized': self.maximized}

    def layout(self, expanded, aspect):
        with self._lock:
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
                geometry = dimensions(aspect, expanded, (work.right-work.left)/scale, (work.bottom-work.top)/scale, self.preferred_height)
                rect = W.RECT(); self.u.GetWindowRect(self.handle, ctypes.byref(rect))
                width, height = round(geometry['width']*scale), round(geometry['height']*scale)
                x = min(max(rect.left, work.left), work.right-width)
                y = min(max(rect.top, work.top), work.bottom-height)
                self.u.SetWindowPos(self.handle, -1 if self.pinned else -2, x, y, width, height, 0x0030)
                def rounded(left, top, right, bottom, radius):
                    return self.g.CreateRoundRectRgn(*(round(v*scale) for v in (left, top, right, bottom, radius*2, radius*2)))
                pw, h = geometry['phone_width'], geometry['height']
                region = rounded(0, 0, pw, h, 44)
                parts = [rounded(pw+8, 12, pw+52, 46, 13)]
                parts.append(rounded(pw+8, h-42, pw+52, h-8, 13))
                if self.menu_open:
                    parts.append(rounded(pw+8, 46, pw+52, 158, 13))
                rail_top, rail_scale = geometry['rail_top'], geometry['rail_scale']
                for index in range(7):
                    top = rail_top + (index*40 + (4 if index >= 2 else 0) + (8 if index > 2 else 0))*rail_scale
                    parts.append(rounded(pw+8, top, pw+8+44*rail_scale, top+(40 if index==2 else 36)*rail_scale, 12*rail_scale))
                for part in parts:
                    self.g.CombineRgn(region, region, part, 2)
                    self.g.DeleteObject(part)
                if not self.u.SetWindowRgn(self.handle, region, True):
                    self.g.DeleteObject(region)
                    raise OSError('Unable to shape the Pane window.')
            self.aspect, self.expanded, self._geometry = aspect, expanded, geometry
            return self.status()

    def command(self, payload):
        action = payload.get('action')
        if action == 'resize':
            height = payload.get('height')
            if type(height) not in (float, int) or not math.isfinite(height) or not 360 <= height <= 10000:
                raise ValueError('Invalid window height.')
            self.preferred_height = height
            self.maximized = False
            return self.layout(self.expanded, self.aspect)
        if action == 'maximize':
            self.maximized = not self.maximized
            self.preferred_height = 10000 if self.maximized else 760
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
