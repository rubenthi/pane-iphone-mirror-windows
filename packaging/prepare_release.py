"""Prepare a versioned release snapshot without writing back to main.

Only the two desktop version files change. Run before testing/building; publish
that exact commit after the gates pass. Existing tags are never moved.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)')


def version_tuple(value):
    if not SEMVER.fullmatch(value):
        raise ValueError(f'Invalid stable version: {value}')
    result = tuple(map(int, value.split('.')))
    if max(result) > 65535:
        raise ValueError('Version exceeds Windows version-resource limits')
    return result


def choose_version(requested, occupied, explicit_tag=None):
    current = version_tuple(requested)
    versions = [version_tuple(tag[1:]) for tag in occupied
                if tag.startswith('v') and SEMVER.fullmatch(tag[1:])]
    highest = max(versions, default=(-1, -1, -1))
    if explicit_tag is not None:
        if explicit_tag != f'v{requested}':
            raise ValueError('Tag does not match source version')
        # The triggering tag is expected; existing releases are checked separately.
        others = [v for v in versions if v != current]
        if others and current <= max(others):
            raise ValueError('Refusing to publish an older version as latest')
        return requested
    selected = current if current > highest else (highest[0], highest[1], highest[2] + 1)
    result = '.'.join(map(str, selected))
    version_tuple(result)
    return result


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def write_versions(version):
    version_tuple(version)
    path = ROOT / 'handset/version.py'
    text, count = re.subn(r'^VERSION = "[^"]+"$', f'VERSION = "{version}"', path.read_text(), flags=re.M)
    if count != 1:
        raise ValueError('Expected exactly one VERSION declaration')
    metadata = ROOT / 'packaging/version.txt'
    resource = metadata.read_text()
    numeric = ', '.join(version.split('.') + ['0'])
    for name in ('filevers', 'prodvers'):
        resource, count = re.subn(rf'{name}=\([^)]*\)', f'{name}=({numeric})', resource)
        if count != 1:
            raise ValueError(f'Expected exactly one {name}')
    for name in ('FileVersion', 'ProductVersion'):
        resource, count = re.subn(rf'StringStruct\("{name}", "[^"]+"\)', f'StringStruct("{name}", "{version}")', resource)
        if count != 1:
            raise ValueError(f'Expected exactly one {name}')
    path.write_text(text, encoding='utf-8')
    metadata.write_text(resource, encoding='utf-8')


def companion_identity(project, declaration):
    version = re.search(r"^    MARKETING_VERSION: '([^']+)'$", project, re.M).group(1)
    build = int(re.search(r"^    CURRENT_PROJECT_VERSION: '(\d+)'$", project, re.M).group(1))
    bundled = re.search(r'^COMPANION_VERSION = "([^"]+)"$', declaration, re.M).group(1)
    if version != bundled:
        raise ValueError('Companion declaration and Xcode marketing version differ')
    return version_tuple(version), build


def validate_companion_change(releases):
    stable = [r['tag_name'] for r in releases if not r.get('draft') and not r.get('prerelease')
              and r['tag_name'].startswith('v') and SEMVER.fullmatch(r['tag_name'][1:])]
    current = companion_identity((ROOT / 'ios/project.yml').read_text(),
                                 (ROOT / 'handset/companion_version.py').read_text())
    if not stable:
        return
    baseline = max(stable, key=lambda tag: version_tuple(tag[1:]))
    previous = companion_identity(git('show', f'{baseline}:ios/project.yml'),
                                  git('show', f'{baseline}:handset/companion_version.py'))
    changes = git('diff', '--name-only', baseline, 'HEAD', '--', 'ios', 'handset/companion_version.py').splitlines()
    substantive = [p for p in changes if not p.lower().endswith('.md')]
    if substantive and (current[0] <= previous[0] or current[1] <= previous[1]):
        raise ValueError('iOS changes require a higher companion marketing version AND build number')
    if current[0] < previous[0] or current[1] < previous[1]:
        raise ValueError('Companion version/build must not go backward')


def release_input(path):
    if path.endswith('.md'):
        return False
    return (path.startswith(('handset/', 'native/', 'signer/', 'ios/', 'packaging/'))
            or (path.startswith('requirements') and '/' not in path and path.endswith('.txt'))
            or path in {'package.json', 'package-lock.json', '.github/workflows/release.yml',
                        '.github/workflows/companion.yml'})


def check_current(source, current):
    # Refuse divergent/rewritten main, and supersede only for release inputs.
    git('merge-base', '--is-ancestor', source, current)
    changed = git('diff', '--name-only', source, current).splitlines()
    if any(release_input(path) for path in changed):
        raise ValueError('Main has newer release inputs; let the newer qualifying run publish')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--releases', type=Path)
    parser.add_argument('--source', required=True)
    parser.add_argument('--tag')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-current')
    args = parser.parse_args()
    if args.check_current:
        check_current(args.source, args.check_current)
        return
    if not args.releases or not args.output:
        parser.error('--releases and --output are required for preparation')
    if git('rev-parse', 'HEAD') != args.source:
        raise ValueError('Checkout does not match triggering commit')
    releases = json.loads(args.releases.read_text(encoding='utf-8-sig'))
    # gh --paginate --slurp returns an array of pages.
    releases = [release for page in releases for release in page]
    validate_companion_change(releases)
    tags = git('tag', '--list', 'v*').splitlines()
    marker = f'Pane-Source: {args.source}'
    if not args.tag:
        for tag in tags:
            if git('rev-parse', f'{tag}^{{commit}}') == args.source or marker in git('show', '-s', '--format=%B', tag).splitlines():
                raise ValueError(f'Source already reserved by {tag}; inspect that release instead of republishing')
    requested = re.search(r'^VERSION = "([^"]+)"$', (ROOT / 'handset/version.py').read_text(), re.M).group(1)
    version = choose_version(requested, tags + [r['tag_name'] for r in releases], args.tag)
    tag = f'v{version}'
    if any(r['tag_name'] == tag for r in releases):
        raise ValueError('Release already exists (including drafts); refusing overwrite')
    if args.tag:
        # Tagged source must already contain matching Windows metadata.
        metadata = (ROOT / 'packaging/version.txt').read_text()
        numeric = ', '.join(version.split('.') + ['0'])
        if any(f'{name}=({numeric})' not in metadata for name in ('filevers', 'prodvers')) or metadata.count(f'"{version}"') != 2:
            raise ValueError('Tag Windows metadata does not match version')
    else:
        write_versions(version)
        git('config', 'user.name', 'github-actions[bot]')
        git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        git('add', 'handset/version.py', 'packaging/version.txt')
        git('commit', '--allow-empty', '-m', f'Release {tag}\n\n{marker}')
    with args.output.open('a', encoding='utf-8') as output:
        output.write(f'PANE_RELEASE_TAG={tag}\nPANE_RELEASE_COMMIT={git("rev-parse", "HEAD")}\n')


if __name__ == '__main__':
    main()
