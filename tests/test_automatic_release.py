"""Boundary and failure cases for the automatic release; failed verification cannot consume a tag."""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_flow', ROOT / 'packaging/ci/release_flow.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)
spec = importlib.util.spec_from_file_location('release_start', ROOT / 'packaging/release.py')
start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start)


@pytest.mark.parametrize('base,mode,expected', [
    ('0.0.0', 'patch', '0.0.1'), ('1.2.9', 'patch', '1.2.10'),
    ('1.2.9', 'minor', '1.3.0'), ('1.2.9', 'major', '2.0.0'),
    ('0.9.99', 'minor', '0.10.0'), ('9.99.99', 'major', '10.0.0')])
def test_version_increment(base, mode, expected):
    assert flow.next_version(base, mode) == expected


@pytest.mark.parametrize('value', ['1.2', '01.2.3', 'v1.2.3', '1.2.3rc1', '1.2.3;danger'])
def test_invalid_version_is_rejected(value):
    with pytest.raises(ValueError):
        flow.next_version(value)


def test_only_completed_stable_tags_count():
    assert flow.release_base(['v0.0.1rc3', 'release/run-100']) == '0.0.0'
    assert flow.release_base(['v1.2.10', 'v1.10.0', 'v9.0.0rc1', 'notes']) == '1.10.0'


@pytest.mark.parametrize('flags,mode', [([], 'patch'), (['--minor'], 'minor'), (['--major'], 'major')])
def test_cli_flags_dispatch_automatic_release(monkeypatch, flags, mode):
    calls = []
    monkeypatch.setattr(start.subprocess, 'run', lambda args, **kw: calls.append(args))
    start.main(flags)
    assert 'bump=' + mode in calls[0] and 'dry_run=true' in calls[0]


def test_conflicting_increment_flags_fail_before_dispatch(monkeypatch):
    monkeypatch.setattr(start.subprocess, 'run', lambda *a, **k: pytest.fail('must not dispatch'))
    with pytest.raises(SystemExit):
        start.main(['--minor', '--major'])


def test_both_version_sources_change_together(tmp_path):
    (tmp_path / 'src/chatexporter/config').mkdir(parents=True)
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion = "0.0.1rc3"\n')
    (tmp_path / 'src/chatexporter/config/version.py').write_text('__version__ = "0.0.1rc3"\n')
    (tmp_path / 'docs/RELEASE_NOTES.md').write_text('# ChatExporter 0.0.1rc3\n')
    (tmp_path / 'README.md').write_text('Aktueller Quellstand: **0.0.1rc3**. Candidate.\n')
    flow.set_version(tmp_path, '0.1.0')
    assert 'version = "0.1.0"' in (tmp_path / 'pyproject.toml').read_text()
    assert '__version__ = "0.1.0"' in (tmp_path / 'src/chatexporter/config/version.py').read_text()
    assert '0.1.0' in (tmp_path / 'docs/RELEASE_NOTES.md').read_text()


@pytest.fixture
def release_bundle(tmp_path):
    (tmp_path / 'python').mkdir()
    files = {'chatexporter_gen4-0.0.1-py3-none-any.whl': b'wheel', 'chatexporter_gen4-0.0.1.tar.gz': b'source'}
    for name, data in files.items():
        (tmp_path / 'python' / name).write_bytes(data)
    installer = 'ChatExporter-Setup-0.0.1.exe'
    portable = 'ChatExporter-Portable-0.0.1.zip'
    (tmp_path / installer).write_bytes(b'installer')
    (tmp_path / portable).write_bytes(b'portable')
    manifest = {'version': '0.0.1', 'commit': 'a' * 40, 'installer': installer,
                'installer_sha256': hashlib.sha256(b'installer').hexdigest(),
                'portable': portable, 'portable_sha256': hashlib.sha256(b'portable').hexdigest(),
                'python_files': {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}}
    (tmp_path / 'ChatExporter-BUILD-0.0.1.json').write_text(json.dumps(manifest))
    (tmp_path / 'ChatExporter-RELEASE_NOTES-0.0.1.md').write_text('Release')
    return tmp_path


def test_modified_wheel_prevents_tag_creation(release_bundle, monkeypatch):
    next((release_bundle / 'python').glob('*.whl')).write_bytes(b'modified')
    monkeypatch.setattr(flow, 'git', lambda *a: pytest.fail('must not access Git before verification'))
    with pytest.raises(ValueError, match='checksum mismatch'):
        flow.finalize(release_bundle)


@pytest.mark.parametrize('asset_problem', ['missing', 'modified'])
def test_failed_upload_prevents_tag_creation(release_bundle, monkeypatch, asset_problem):
    calls = []
    def fake_git(*args):
        calls.append(args)
        return 'a' * 40
    monkeypatch.setattr(flow, 'git', fake_git)
    monkeypatch.setenv('GH_REPO', 'owner/project')
    release = {'apiUrl': 'https://api.github.com/repos/owner/project/releases/123', 'isDraft': True, 'targetCommitish': 'a' * 40}
    monkeypatch.setattr(flow.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(release)))
    files = list(release_bundle.rglob('*'))
    assets = [{'name': p.name, 'digest': 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()} for p in files if p.is_file()]
    if asset_problem == 'missing':
        assets.pop()
    else:
        assets[0]['digest'] = 'sha256:modified'
    monkeypatch.setattr(flow.subprocess, 'check_output', lambda *a, **k: json.dumps(assets))
    with pytest.raises(ValueError, match='attachments|upload checksum'):
        flow.finalize(release_bundle)
    assert calls == [('rev-parse', 'HEAD')]


def test_tag_is_last_mutation_after_all_uploads_verified(release_bundle, monkeypatch):
    calls = []
    def fake_git(*args):
        calls.append(args)
        return 'a' * 40 if args == ('rev-parse', 'HEAD') else ''
    monkeypatch.setattr(flow, 'git', fake_git)
    monkeypatch.setenv('GH_REPO', 'owner/project')
    release = {'apiUrl': 'https://api.github.com/repos/owner/project/releases/123', 'isDraft': True, 'targetCommitish': 'a' * 40}
    monkeypatch.setattr(flow.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(release)))
    assets = [{'name': p.name, 'digest': 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()} for p in release_bundle.rglob('*') if p.is_file()]
    monkeypatch.setattr(flow.subprocess, 'check_output', lambda *a, **k: json.dumps(assets))
    flow.finalize(release_bundle)
    assert calls[-1] == ('push', 'origin', 'v0.0.1')


def test_installed_wheel_uses_its_shipped_scheduler(tmp_path, monkeypatch):
    from chatexporter.task_scheduler import config
    installed = tmp_path / 'venv/Lib/site-packages/chatexporter/task_scheduler/config.py'
    monkeypatch.setattr(config, '__file__', str(installed))
    monkeypatch.setattr(config.sys, 'prefix', str(tmp_path / 'venv'))
    monkeypatch.setattr(config.sys, 'frozen', False, raising=False)
    tool = tmp_path / 'venv/tools/task_scheduler/scheduler_manager.py'
    tool.parent.mkdir(parents=True)
    tool.write_text('pass')
    assert config.default_manager_script() == tool
