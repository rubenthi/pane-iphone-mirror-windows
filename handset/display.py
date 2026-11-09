"""Render the native UI at the pixel density of the screen hosting it."""
import ctypes
from ctypes import wintypes as W
import os


def enable_per_monitor_dpi():
    """Source runs need the same early DPI mode as the packaged manifest.

    Call before importing/creating WinForms or WebView2. An existing manifest
    setting is authoritative; never change only one thread to hide a failure.
    """
    if os.name != 'nt':
        return
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetThreadDpiAwarenessContext.argtypes = []
    user.GetThreadDpiAwarenessContext.restype = W.HANDLE
    user.AreDpiAwarenessContextsEqual.argtypes = [W.HANDLE, W.HANDLE]
    user.AreDpiAwarenessContextsEqual.restype = W.BOOL
    if user.AreDpiAwarenessContextsEqual(user.GetThreadDpiAwarenessContext(), -4):
        return
    user.SetProcessDpiAwarenessContext.argtypes = [W.HANDLE]
    user.SetProcessDpiAwarenessContext.restype = W.BOOL
    if not user.SetProcessDpiAwarenessContext(-4):
        raise OSError(ctypes.get_last_error(), 'Pane needs per-monitor DPI awareness before opening its window.')
