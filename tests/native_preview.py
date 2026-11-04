"""Disposable UI test instance, with no device operations and no release update checks."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['PANE_PORT'] = '18776'
os.environ['PANE_DATA_DIR'] = tempfile.mkdtemp(prefix='Pane-ui-test-')
import webview
webview.settings['REMOTE_DEBUGGING_PORT'] = 18777
from handset import server, app
server.snapshot = lambda: {'driver': {'ready': True}, 'library': {'ready': True}, 'devices': [], 'developerMode': None, 'error': None}
server.wifi_paired_udids = lambda: []
# Query the real HWND region, not just CSS or our intended geometry.
from handset.window import shell
import ctypes
from ctypes import wintypes as W
original_status = shell.status

def checked_status():
    if not shell.handle:
        return original_status()
    def inspect():
        # Read geometry and its native region in the same UI-thread turn.
        state = original_status()
        state['menu_open'] = shell.menu_open
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
            return state
        finally:
            shell.g.DeleteObject(region)
    return shell._on_ui(inspect)

shell.status = checked_status
app.main()
