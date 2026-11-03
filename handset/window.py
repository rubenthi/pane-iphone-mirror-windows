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

DRAWER = 356
TAB = 28
DEFAULT_ASPECT = 390 / 844


def dimensions(aspect=DEFAULT_ASPECT, expanded=False, work_width=1920, work_height=1080):
    if type(expanded) is not bool or type(aspect) not in (float, int) or not math.isfinite(aspect) or not .35 <= aspect <= 2.5:
        raise ValueError('Invalid window layout.')
    extra = DRAWER if expanded else TAB
    height = max(240, min(760, work_height - 48, (work_width - extra - 48 - 16) / aspect + 16))
    width = round((height - 16) * aspect) + 16
    return {'phone_width': width, 'height': round(height), 'width': width + extra, 'expanded': expanded}


class FloatingWindow:
    def __init__(self):
        self.handle = None
        self.expanded = False
        self.aspect = DEFAULT_ASPECT
        self.pinned = False
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
                self.layout(False, DEFAULT_ASPECT)
                return True
            time.sleep(.1)
        return False

    def status(self):
        return {**self._geometry, 'native': bool(self.handle), 'pinned': self.pinned}

    def layout(self, expanded, aspect):
        with self._lock:
            geometry = dimensions(aspect, expanded)
            if self.handle:
                scale = (self.u.GetDpiForWindow(self.handle) or 96) / 96
                work = W.RECT()
                self.u.SystemParametersInfoW(48, 0, ctypes.byref(work), 0)
                geometry = dimensions(aspect, expanded, (work.right-work.left)/scale, (work.bottom-work.top)/scale)
                rect = W.RECT(); self.u.GetWindowRect(self.handle, ctypes.byref(rect))
                width, height = round(geometry['width']*scale), round(geometry['height']*scale)
                x = min(max(rect.left, work.left), work.right-width)
                y = min(max(rect.top, work.top), work.bottom-height)
                self.u.SetWindowPos(self.handle, -1 if self.pinned else -2, x, y, width, height, 0x0030)
                def rounded(left, top, right, bottom, radius):
                    return self.g.CreateRoundRectRgn(*(round(v*scale) for v in (left, top, right, bottom, radius*2, radius*2)))
                pw, h = geometry['phone_width'], geometry['height']
                region = rounded(0, 0, pw, h, 48)
                parts = [rounded(pw-12, h/2-38, pw+TAB, h/2+38, 14)]
                if expanded:
                    parts.append(rounded(pw+12, 0, geometry['width'], h, 24))
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
        if action == 'layout':
            return self.layout(payload.get('expanded', self.expanded), payload.get('aspect', self.aspect))
        if action not in ('drag', 'minimize', 'close', 'pin', 'focus'):
            raise ValueError('Unknown window action.')
        if not self.handle:
            raise ValueError('Native window controls are unavailable in browser mode.')
        if action == 'pin':
            self.pinned = not self.pinned
            return self.layout(self.expanded, self.aspect)
        if action == 'drag':
            point = W.POINT(); self.u.GetCursorPos(ctypes.byref(point))
            self.u.PostMessageW(self.handle, 0x00A1, 2, (point.x & 65535) | ((point.y & 65535) << 16))
        elif action == 'minimize':
            self.u.ShowWindow(self.handle, 6)
        elif action == 'close':
            self.u.PostMessageW(self.handle, 0x0010, 0, 0)
        elif action == 'focus':
            self.u.ShowWindow(self.handle, 9)
            self.u.SetForegroundWindow(self.handle)
        return self.status()


shell = FloatingWindow()
