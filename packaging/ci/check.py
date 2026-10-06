"""Fail closed on release metadata, broken local documentation, or skipped CI tests."""
from __future__ import annotations

import argparse
import importlib.metadata
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]


def version(root: Path = ROOT) -> str:
    data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    declared = data['project']['version']
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)', (root / 'src/chatexporter/config/version.py').read_text(encoding='utf-8'))
    if not match or declared != match.group(1):
        raise ValueError('pyproject and source version differ')
    if importlib.metadata.version('chatexporter-gen4') != declared:
        raise ValueError('Installed distribution metadata is stale')
    return declared


def check_docs(root: Path = ROOT) -> None:
    errors = []
    for path in [root / 'README.md', *root.joinpath('docs').rglob('*.md')]:
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text(encoding='utf-8-sig')):
            if '://' in link or link.startswith('#') or link.startswith('mailto:'):
                continue
            destination = (path.parent / unquote(link.split('#')[0].strip('<>'))).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.exists():
                errors.append(f'{path.relative_to(root)}: {link}')
    if errors:
        raise ValueError('Invalid local documentation links:\n' + '\n'.join(errors))


def check_junit(path: Path) -> None:
    cases = ElementTree.parse(path).findall('.//testcase')
    if len(cases) < 689:
        raise ValueError('Full test suite was not collected')
    if any(case.find(kind) is not None for case in cases for kind in ('failure', 'error', 'skipped')):
        raise ValueError('A test failed, errored, or was skipped; Edge is required in CI')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag')
    parser.add_argument('--junit', type=Path)
    args = parser.parse_args()
    current = version()
    if args.tag and args.tag != 'v' + current:
        raise SystemExit('Tag must be exactly v' + current)
    check_docs()
    if args.junit:
        check_junit(args.junit)
    print('Version, installed metadata, documentation and requested gates: OK (' + current + ')')


if __name__ == '__main__':
    main()
