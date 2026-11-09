"""Bundled iPhone app version, independent of desktop-only releases."""
import plistlib
import zipfile

COMPANION_VERSION = "2.6.1"
COMPANION_BUILD = "7"


def validate_companion(path):
    with zipfile.ZipFile(path) as archive:
        info = plistlib.loads(archive.read('Payload/PaneFiles.app/Info.plist'))
    if (info.get('CFBundleIdentifier') != 'io.github.rubenthi.PaneFiles'
            or info.get('CFBundleExecutable') != 'PaneFiles'
            or info.get('PaneProtocolVersion') != 1):
        raise ValueError('Unexpected iPhone companion identity')
    if (info.get('CFBundleShortVersionString') != COMPANION_VERSION
            or info.get('CFBundleVersion') != COMPANION_BUILD):
        raise ValueError('iPhone companion version mismatch')
    return info
