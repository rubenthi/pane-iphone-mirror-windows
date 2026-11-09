"""Desktop visibility preflight for the physical-pixel Win32 test fixture."""
import ctypes
from ctypes import wintypes as W
from contextlib import contextmanager
import os
from pathlib import Path
import time


def _api(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


_user = ctypes.WinDLL('user32', use_last_error=True)
_kernel = ctypes.WinDLL('kernel32', use_last_error=True)
_open_input = _api(_user, 'OpenInputDesktop', W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
_close_desktop = _api(_user, 'CloseDesktop', W.BOOL, W.HANDLE)
_thread_desktop = _api(_user, 'GetThreadDesktop', W.HANDLE, W.DWORD)
_thread_id = _api(_kernel, 'GetCurrentThreadId', W.DWORD)
_object_info = _api(_user, 'GetUserObjectInformationW', W.BOOL, W.HANDLE, ctypes.c_int,
                    ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD))
_window_callback = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
_enum_windows = _api(_user, 'EnumDesktopWindows', W.BOOL, W.HANDLE, _window_callback, W.LPARAM)
_window_process = _api(_user, 'GetWindowThreadProcessId', W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
_open_process = _api(_kernel, 'OpenProcess', W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
_process_image = _api(_kernel, 'QueryFullProcessImageNameW', W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR,
                      ctypes.POINTER(W.DWORD))
_close_handle = _api(_kernel, 'CloseHandle', W.BOOL, W.HANDLE)
_post = _api(_user, 'PostMessageW', W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
_execution_state = _api(_kernel, 'SetThreadExecutionState', W.DWORD, W.DWORD)


def _name(desktop):
    name = ctypes.create_unicode_buffer(256)
    size = W.DWORD()
    if desktop and _object_info(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(size)):
        return name.value
    return None


def input_desktop_name():
    desktop = _open_input(0, False, 0x0001)  # DESKTOP_READOBJECTS
    try:
        return _name(desktop)
    finally:
        if desktop:
            _close_desktop(desktop)


def _dismiss_windows_screen_saver():
    desktop = _open_input(0, False, 0x0041)  # DESKTOP_ENUMERATE | DESKTOP_READOBJECTS
    if not desktop:
        return
    windows_dir = Path(os.environ['SystemRoot'])
    allowed = {windows_dir / 'System32', windows_dir / 'SysWOW64'}

    @_window_callback
    def dismiss(hwnd, _):
        pid = W.DWORD()
        _window_process(hwnd, ctypes.byref(pid))
        process = _open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if process:
            try:
                name = ctypes.create_unicode_buffer(32768)
                count = W.DWORD(len(name))
                if _process_image(process, 0, name, ctypes.byref(count)):
                    image = Path(name.value)
                    if image.parent in allowed and image.suffix.lower() == '.scr':
                        _post(hwnd, 0x0010, 0, 0)  # WM_CLOSE; Windows controls any unlock prompt.
            finally:
                _close_handle(process)
        return True

    try:
        if (_name(desktop) or '').casefold() == 'screen-saver':
            _enum_windows(desktop, dismiss, 0)
    finally:
        _close_desktop(desktop)


@contextmanager
def visible_test_desktop():
    """Require access to the actual interactive desktop throughout physical QA."""
    own = _name(_thread_desktop(_thread_id()))
    active = input_desktop_name()
    if (active or '').casefold() == 'screen-saver':
        _dismiss_windows_screen_saver()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            active = input_desktop_name()
            if own and active == own:
                break
            time.sleep(.05)
    if not own or active != own:
        raise RuntimeError(f'Physical pixel test needs the visible Windows desktop. '
                           f'Test desktop={own!r}, input desktop={active!r}. '
                           'Unlock or wake the display and rerun.')
    if not _execution_state(0x80000002):  # ES_CONTINUOUS | ES_DISPLAY_REQUIRED
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        _execution_state(0x80000000)
