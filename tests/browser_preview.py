"""Local integration fixture with disposable app state and no device access."""
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, os.environ.get('PANE_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
os.environ['PANE_DATA_DIR'] = tempfile.mkdtemp(prefix='Pane-browser-')
from handset import server, transfers, setup, companion_update
companion_update.list_devices = lambda: []
try:
    from handset import notifications
except ImportError:
    pass  # The baseline used by measure-idle predates this module.
else:
    notifications._helper = lambda: None  # Fixtures never start real radio services.
transfers._STORE = transfers.TransferStore(Path(os.environ['PANE_DATA_DIR']), Path(os.environ['PANE_DATA_DIR']) / 'Downloads')
server.snapshot = lambda: {'driver': {'ready': True}, 'library': {'ready': True}, 'devices': [], 'developerMode': None, 'error': None}
server.wifi_paired_udids = lambda: []
# Setup imports its own reference; saved host pairings must not affect fixtures.
setup.wifi_paired_udids = lambda: []
http = server.SingleServer(('127.0.0.1', int(os.environ.get('PANE_TEST_PORT', '0'))), server.Handler)
print(f'ready http://127.0.0.1:{http.server_port}', flush=True)
try:
    http.serve_forever()
finally:
    http.server_close()
