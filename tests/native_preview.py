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
app.main()
