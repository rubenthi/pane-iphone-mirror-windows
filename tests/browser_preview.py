"""Local integration fixture with disposable app state and no device access."""
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['PANE_DATA_DIR'] = tempfile.mkdtemp(prefix='Pane-browser-')
from handset import server, transfers
transfers._STORE = transfers.TransferStore(Path(os.environ['PANE_DATA_DIR']), Path(os.environ['PANE_DATA_DIR']) / 'Downloads')
server.snapshot = lambda: {'driver': {'ready': True}, 'library': {'ready': True}, 'devices': [], 'developerMode': None, 'error': None}
server.wifi_paired_udids = lambda: []
http = server.SingleServer(('127.0.0.1', 18778), server.Handler)
print('ready', flush=True)
try:
    http.serve_forever()
finally:
    http.server_close()
