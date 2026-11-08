"""Defaults shared by the desktop, browser server and mirroring worker."""
import os
from pathlib import Path
import sys

def is_development():
    """Source runs and explicitly selected executable runs use isolated state."""
    return not getattr(sys, 'frozen', False) or '--development' in sys.argv


DEVELOPMENT = is_development()
APP_NAME = 'Pane (Development)' if DEVELOPMENT else 'Pane'
PORT = int(os.environ.get('PANE_PORT', 8775 if DEVELOPMENT else 8765))
STREAM_PORT = int(os.environ.get('PANE_STREAM_PORT', 8776 if DEVELOPMENT else 8766))


def data_dir():
    return Path(os.environ.get('PANE_DATA_DIR', Path(os.environ.get('LOCALAPPDATA', Path.home())) / APP_NAME))
