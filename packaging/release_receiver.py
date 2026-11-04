"""Package the exact receiver already shipped with the matching native source."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from PyInstaller.archive.readers import CArchiveReader


ROOT = Path(__file__).resolve().parents[1]
# The receiver was built from 25ff9f27a387a70755b1b38e184aff293d782fb6.
SOURCE_TREE = "476f93f0f31b140462910ff087ee5c243c1ee18c"
URL = "https://github.com/rubenthi/pane-iphone-mirror-windows/releases/download/v1.7.0/Pane.exe"
PACKAGE_SHA = "dbb3c7da88985d4ab5d8952a56cd00fc53e9abce74aad54af2af8357c7f84df6"
RECEIVER_SHA = "7e44bb3b03a05c8bcad15c52d54a97c397306a3ab15540b05af3d471f51ab45b"


def package(path):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != PACKAGE_SHA:
            raise ValueError("Receiver source package checksum mismatch.")
    archive = CArchiveReader(str(path))
    key = next(k for k in archive.toc if k.replace(chr(92), "/") == "native/Pane.Audio.exe")
    data = archive.extract(key)
    if hashlib.sha256(data).hexdigest() != RECEIVER_SHA:
        raise ValueError("Receiver checksum mismatch.")
    (ROOT / "native" / "Pane.Audio.exe").write_bytes(data)


if __name__ == "__main__":
    tree = subprocess.check_output(["git", "rev-parse", "HEAD:native/Pane.Audio"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "native/Pane.Audio"], cwd=ROOT)
    if tree != SOURCE_TREE or dirty:
        sys.exit("Native source changed. Build and verify the new receiver before updating its release pin.")
    if len(sys.argv) == 2:
        package(Path(sys.argv[1]))
    else:
        with tempfile.TemporaryDirectory(prefix="Pane-receiver-build-") as directory:
            path = Path(directory) / "Pane.exe"
            with urllib.request.urlopen(URL, timeout=60) as response, path.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            package(path)
    print("Verified released Bluetooth receiver", RECEIVER_SHA)
