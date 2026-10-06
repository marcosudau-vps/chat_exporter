"""Produce a minimal release bundle after checking smoke tests, metadata and PE icons."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

import pefile
from check import ROOT, version


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_icons(icon: Path, binary: Path) -> None:
    data = icon.read_bytes()
    expected = {}
    for i in range(struct.unpack_from('<H', data, 4)[0]):
        w, h, _, _, _, _, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + 16 * i)
        expected[(w or 256, h or 256)] = data[offset:offset + length]
    if set(expected) != {(s, s) for s in (16, 24, 32, 48, 64, 128, 256)}:
        raise ValueError('Expected seven icon sizes')
    with pefile.PE(str(binary)) as pe:
        resources, groups = {}, []
        for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if kind.id not in (3, 14):
                continue
            for entry in kind.directory.entries:
                for lang in entry.directory.entries:
                    ref = lang.data.struct
                    payload = pe.get_data(ref.OffsetToData, ref.Size)
                    if kind.id == 3:
                        resources[entry.id] = payload
                    else:
                        groups.append(payload)
        for group in groups:
            images = {}
            for i in range(struct.unpack_from('<H', group, 4)[0]):
                w, h, _, _, _, _, _, identifier = struct.unpack_from('<BBBBHHIH', group, 6 + 14 * i)
                images[(w or 256, h or 256)] = resources[identifier]
            if images == expected:
                return
    raise ValueError('Binary does not contain the expected application icon: ' + binary.name)


def verify_python_distributions(folder: Path, current: str) -> dict[str, str]:
    paths = sorted(folder.iterdir())
    if len(paths) != 2 or not any(p.suffix == '.whl' for p in paths) or not any(p.name.endswith('.tar.gz') for p in paths):
        raise ValueError('Exactly one wheel and one source distribution required')
    result = {}
    for path in paths:
        if current not in path.name:
            raise ValueError('Unversioned Python distribution')
        if path.suffix == '.whl':
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                metadata = [n for n in names if n.endswith('.dist-info/METADATA')]
                if len(metadata) != 1 or not any(n.endswith('.data/data/tools/task_scheduler/scheduler_manager.py') for n in names):
                    raise ValueError('Wheel metadata or scheduler tool missing')
                text = archive.read(metadata[0]).decode('utf-8')
        else:
            with tarfile.open(path) as archive:
                names = archive.getnames()
                metadata = [n for n in names if n.count('/') == 1 and n.endswith('/PKG-INFO')]
                if len(metadata) != 1 or not any(n.endswith('/tools/task_scheduler/scheduler_manager.py') for n in names):
                    raise ValueError('Source distribution metadata or scheduler tool missing')
                text = archive.extractfile(metadata[0]).read().decode('utf-8')
        meta = Parser().parsestr(text)
        if meta['Version'] != current or meta['Name'] != 'chatexporter-gen4':
            raise ValueError('Python distribution version/name differs')
        result[path.name] = digest(path)
    return result


def prepare(build: Path, target: Path, commit: str, python_dist: Path | None = None) -> None:
    current = version()
    report = json.loads((build / 'build_report.json').read_text(encoding='utf-8'))
    exe = build / 'dist/ChatExporter/chatexporter.exe'
    installer = build / f'installer/ChatExporter-Setup-{current}.exe'
    metadata = build / f'dist/ChatExporter/_internal/chatexporter_gen4-{current}.dist-info/METADATA'
    if report.get('version') != current or not report.get('smoke_test') or not all(r['ok'] for r in report['smoke_test']):
        raise ValueError('Build version/smoke tests failed')
    if not installer.is_file() or report.get('installer', {}).get('sha256') != digest(installer):
        raise ValueError('Installer is absent or does not match the build report')
    if report['program']['exe_sha256'] != digest(exe):
        raise ValueError('Executable does not match the build report')
    if not metadata.is_file() or f'\nVersion: {current}\n' not in '\n' + metadata.read_text(encoding='utf-8'):
        raise ValueError('Bundled distribution metadata is stale')
    for binary in (exe, installer):
        verify_icons(ROOT / 'assets/IconChatExporter.ico', binary)
    if python_dist is None:
        raise ValueError('Python distributions required')
    python_files = verify_python_distributions(python_dist, current)
    if target.exists():
        raise ValueError('Refusing to overwrite a release bundle')
    target.mkdir(parents=True)
    shutil.copy2(installer, target / installer.name)
    portable = Path(shutil.make_archive(str(target / f'ChatExporter-Portable-{current}'), 'zip', root_dir=exe.parent.parent, base_dir=exe.parent.name))
    (target / 'python').mkdir()
    for name in python_files:
        shutil.copy2(python_dist / name, target / 'python' / name)
    provenance = {'version': current, 'commit': commit, 'python': report['python'], 'built_at': report['built_at'],
                  'installer': installer.name, 'installer_sha256': digest(installer), 'exe_sha256': digest(exe),
                  'dependency_lock_sha256': digest(ROOT / 'requirements-ci.lock'),
                  'icons_verified': True, 'smoke_test': report['smoke_test'],
                  'project': tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['name'],
                  'python_files': python_files, 'portable': portable.name, 'portable_sha256': digest(portable)}
    (target / f'ChatExporter-BUILD-{current}.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    shutil.copy2(ROOT / 'docs/RELEASE_NOTES.md', target / f'ChatExporter-RELEASE_NOTES-{current}.md')
    checksums = [f'{digest(path)}  {path.name}' for path in sorted(target.rglob('*')) if path.is_file()]
    (target / f'ChatExporter-SHA256SUMS-{current}.txt').write_text('\n'.join(checksums) + '\n', encoding='utf-8')
    print('Release bundle verified: ' + str(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--python-dist', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.build.resolve(), args.out.resolve(), args.commit, args.python_dist.resolve())
