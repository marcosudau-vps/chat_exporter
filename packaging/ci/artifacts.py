"""Produce a minimal release bundle after checking smoke tests, metadata and PE icons."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
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


def prepare(build: Path, target: Path, commit: str) -> None:
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
    if target.exists():
        raise ValueError('Refusing to overwrite a release bundle')
    target.mkdir(parents=True)
    shutil.copy2(installer, target / installer.name)
    (target / 'SHA256SUMS.txt').write_text(f'{digest(installer)}  {installer.name}\n', encoding='utf-8')
    provenance = {'version': current, 'commit': commit, 'python': report['python'], 'built_at': report['built_at'],
                  'installer': installer.name, 'installer_sha256': digest(installer), 'exe_sha256': digest(exe),
                  'dependency_lock_sha256': digest(ROOT / 'requirements-ci.lock'),
                  'icons_verified': True, 'smoke_test': report['smoke_test']}
    (target / 'BUILD.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    shutil.copy2(ROOT / 'docs/RELEASE_NOTES.md', target / 'RELEASE_NOTES.md')
    print('Release bundle verified: ' + str(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    prepare(args.build.resolve(), args.out.resolve(), args.commit)
