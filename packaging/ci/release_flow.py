"""Versioned GitHub release snapshots. Tags follow tests, builds and verified uploads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STABLE = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')


def stable(value: str) -> tuple[int, int, int]:
    if not STABLE.fullmatch(value):
        raise ValueError('Expected a stable major.minor.patch version')
    return tuple(int(n) for n in value.split('.'))


def next_version(base: str, bump: str = 'patch') -> str:
    major, minor, patch = stable(base)
    if bump == 'major':
        return f'{major + 1}.0.0'
    if bump == 'minor':
        return f'{major}.{minor + 1}.0'
    if bump == 'patch':
        return f'{major}.{minor}.{patch + 1}'
    raise ValueError('Unknown version increment')


def release_base(tags: list[str]) -> str:
    versions = [stable(tag[1:]) for tag in tags if tag.startswith('v') and STABLE.fullmatch(tag[1:])]
    # An unpublished release candidate is not a published patch. First patch: 0.0.0 -> 0.0.1.
    return '.'.join(map(str, max(versions, default=(0, 0, 0))))


def set_version(root: Path, value: str) -> None:
    stable(value)
    paths = [root / 'pyproject.toml', root / 'src/chatexporter/config/version.py']
    edits = []
    for path, pattern in zip(paths, (r'(?m)^version = "[^"]+"$', r'(?m)^__version__ = "[^"]+"$')):
        content = path.read_text(encoding='utf-8')
        updated, count = re.subn(pattern, ('version' if path.suffix == '.toml' else '__version__') + f' = "{value}"', content)
        if count != 1:
            raise ValueError('Version source is ambiguous: ' + path.name)
        edits.append((path, updated))
    for path, content in edits:
        path.write_text(content, encoding='utf-8', newline='\n')
    notes = root / 'docs/RELEASE_NOTES.md'
    text = notes.read_text(encoding='utf-8')
    text = re.sub(r'(?m)^# ChatExporter .*$', '# ChatExporter ' + value, text, count=1)
    notes.write_text(text, encoding='utf-8', newline='\n')
    readme = root / 'README.md'
    text = readme.read_text(encoding='utf-8')
    text = re.sub(r'Aktueller Quellstand: \*\*[^*]+\*\*\.[^\n]*',
                  f'Aktueller Quellstand: **{value}**. Veröffentlichung wird über den Release-Ablauf vorbereitet.', text, count=1)
    readme.write_text(text, encoding='utf-8', newline='\n')
    changelog = root / 'CHANGELOG.md'
    if changelog.is_file():
        text = changelog.read_text(encoding='utf-8')
        header = '## ' + value + ' — ' + datetime.now(timezone.utc).date().isoformat()
        changelog.write_text(text.replace('## Unreleased', header, 1), encoding='utf-8', newline='\n')


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def prepare(bump: str) -> dict:
    run = os.environ['GITHUB_RUN_ID']
    if not run.isdigit():
        raise ValueError('Invalid run id')
    branch = 'release/run-' + run
    existing = git('ls-remote', '--heads', 'origin', 'refs/heads/' + branch)
    if existing:
        git('fetch', 'origin', branch)
        git('checkout', '-B', branch, 'FETCH_HEAD')
        plan = json.loads((ROOT / '.github/release-plan.json').read_text(encoding='utf-8'))
        if plan['bump'] != bump or plan['run_id'] != run:
            raise ValueError('Retry must use the original release plan')
    else:
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
        git('fetch', '--tags', 'origin')
        base = release_base(git('tag', '--list').splitlines())
        value = next_version(base, bump)
        plan = {'project': project['name'], 'version': value, 'base': base, 'bump': bump, 'run_id': run,
                'branch': branch, 'source_commit': git('rev-parse', 'HEAD')}
        git('switch', '-c', branch)
        set_version(ROOT, value)
        (ROOT / '.github/release-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
        git('config', 'user.name', 'github-actions[bot]')
        git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        git('add', 'pyproject.toml', 'src/chatexporter/config/version.py', 'docs/RELEASE_NOTES.md', 'README.md', 'CHANGELOG.md', '.github/release-plan.json')
        git('commit', '-m', 'Prepare release ' + value)
        git('push', 'origin', branch)
    plan['commit'] = git('rev-parse', 'HEAD')
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        for key in ('version', 'commit', 'branch', 'project'):
            output.write(key + '=' + plan[key] + '\n')
    print(json.dumps(plan, indent=2))
    return plan


def verify_uploads(expected: dict[str, str], assets: list[dict]) -> None:
    actual = {item['name']: item.get('digest') for item in assets}
    if set(actual) != set(expected):
        raise ValueError('Release attachments are incomplete or unexpected')
    if any(actual[name] != 'sha256:' + digest for name, digest in expected.items()):
        raise ValueError('GitHub upload checksum mismatch')


def verify(bundle: Path) -> dict:
    manifests = list(bundle.glob('ChatExporter-BUILD-*.json'))
    if len(manifests) != 1:
        raise ValueError('Expected exactly one versioned build manifest')
    manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
    stable(manifest['version'])
    if not re.fullmatch(r'[a-f0-9]{40}', manifest['commit']):
        raise ValueError('Invalid source commit')
    expected = manifest['python_files']
    if len(expected) != 2 or not any(n.endswith('.whl') for n in expected) or not any(n.endswith('.tar.gz') for n in expected):
        raise ValueError('A wheel and source distribution are required')
    for name, expected in manifest['python_files'].items():
        if Path(name).name != name or manifest['version'] not in name or not name.endswith(('.whl', '.tar.gz')):
            raise ValueError('Unsafe distribution name')
        if hashlib.sha256((bundle / 'python' / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Local distribution checksum mismatch: ' + name)
    installer = manifest['installer']
    if Path(installer).name != installer or manifest['version'] not in installer:
        raise ValueError('Unsafe or unversioned installer name')
    if hashlib.sha256((bundle / installer).read_bytes()).hexdigest() != manifest['installer_sha256']:
        raise ValueError('Installer checksum mismatch')
    portable = manifest['portable']
    if Path(portable).name != portable or manifest['version'] not in portable:
        raise ValueError('Unsafe or unversioned portable name')
    if hashlib.sha256((bundle / portable).read_bytes()).hexdigest() != manifest['portable_sha256']:
        raise ValueError('Portable checksum mismatch')
    return manifest


def finalize(bundle: Path) -> None:
    # Independent checksum guard in addition to the workflow needs:tests,build.
    manifest = verify(bundle)
    if git('rev-parse', 'HEAD') != manifest['commit']:
        raise ValueError('Release checkout differs from tested build')
    version = manifest['version']
    tag = 'v' + manifest['version']
    files = [path for path in bundle.rglob('*') if path.is_file()]
    if any(version not in path.name for path in files):
        raise ValueError('Every attachment must have a versioned filename')
    expected = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    if len(expected) != len(files):
        raise ValueError('Duplicate attachment names')
    # Draft metadata does not create a Git ref. Upload and verify everything before tagging.
    result = subprocess.run(['gh', 'release', 'view', tag, '--json', 'apiUrl,isDraft,targetCommitish'], capture_output=True, text=True)
    if result.returncode:
        subprocess.run(['gh', 'release', 'create', tag, *[str(path) for path in files], '--draft', '--target', manifest['commit'],
                        '--title', 'ChatExporter ' + version, '--notes-file',
                        str(bundle / f'ChatExporter-RELEASE_NOTES-{version}.md')], check=True)
        result = subprocess.run(['gh', 'release', 'view', tag, '--json', 'apiUrl,isDraft,targetCommitish'], capture_output=True, text=True, check=True)
    release = json.loads(result.stdout)
    if release['targetCommitish'] != manifest['commit']:
        raise ValueError('Existing release targets another source commit')
    release_id = release['apiUrl'].rsplit('/', 1)[-1]
    if not release_id.isdigit():
        raise ValueError('Invalid GitHub release id')
    assets = json.loads(subprocess.check_output(['gh', 'api', f'repos/{os.environ["GH_REPO"]}/releases/{release_id}/assets',
                                                '-F', 'per_page=100', '--method', 'GET'], text=True))
    verify_uploads(expected, assets)
    existing = git('ls-remote', '--tags', 'origin', 'refs/tags/' + tag, 'refs/tags/' + tag + '^{}')
    if existing:
        refs = dict(line.split()[::-1] for line in existing.splitlines())
        target = refs.get('refs/tags/' + tag + '^{}', refs.get('refs/tags/' + tag))
        if target != manifest['commit']:
            raise ValueError('Existing tag points at another commit')
    else:
        git('config', 'user.name', 'github-actions[bot]')
        git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        git('tag', '-a', tag, '-m', 'Verified GitHub release ' + manifest['version'])
        git('push', 'origin', tag)
    if release['isDraft']:
        subprocess.run(['gh', 'release', 'edit', tag, '--draft=false'], check=True)
    print('Uploads verified; GitHub tag and release ready: ' + tag)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--bump', choices=('patch', 'minor', 'major'), default='patch')
    for action in ('verify', 'finalize'):
        command = sub.add_parser(action)
        command.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.bump)
    elif args.action == 'finalize':
        finalize(args.bundle)
    else:
        verify(args.bundle)
        print('All distribution checksums verified')
