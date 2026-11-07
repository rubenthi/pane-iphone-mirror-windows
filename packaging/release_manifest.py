"""Build the immutable fork-specific update manifest and standalone installer."""
import argparse
import hashlib
import json
import plistlib
import zipfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from handset.version import REPOSITORY, VERSION


def validate_companion(path):
    with zipfile.ZipFile(path) as archive:
        info = plistlib.loads(archive.read('Payload/PaneFiles.app/Info.plist'))
    if (info.get('CFBundleIdentifier') != 'io.github.rubenthi.PaneFiles'
            or info.get('CFBundleExecutable') != 'PaneFiles'
            or info.get('PaneProtocolVersion') != 1):
        raise ValueError('Unexpected iPhone companion identity')
    if info.get('CFBundleShortVersionString') != VERSION:
        raise ValueError('iPhone companion version mismatch')
    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    if args.tag != f'v{VERSION}':
        raise SystemExit('Tag must match handset/version.py')
    metadata = (ROOT / 'packaging/version.txt').read_text()
    numeric = ', '.join(VERSION.split('.') + ['0'])
    if f'filevers=({numeric})' not in metadata or f'prodvers=({numeric})' not in metadata or metadata.count(f'"{VERSION}"') != 2:
        raise SystemExit('Windows version metadata mismatch')
    validate_companion(ROOT / 'ios' / 'Pane-unsigned.ipa')
    dist = ROOT / 'dist'
    exe = dist / 'Pane.exe'
    manifest = dict(version=VERSION, url=f'https://github.com/{REPOSITORY}/releases/download/v{VERSION}/Pane.exe',
                    sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), size=exe.stat().st_size)
    (dist / 'update.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    installer = (ROOT / 'packaging/install.ps1').read_text(encoding='utf-8')
    installer = installer.replace('. "$PSScriptRoot/../handset/install_update.ps1"',
                                  (ROOT / 'handset/install_update.ps1').read_text(encoding='utf-8'))
    (dist / 'install.ps1').write_text(installer, encoding='utf-8-sig')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
