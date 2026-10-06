"""Release gates reject incomplete suites and missing/tampered build outputs."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

CI = Path(__file__).resolve().parents[1] / 'packaging/ci'
spec = importlib.util.spec_from_file_location('check', CI / 'check.py')
check = importlib.util.module_from_spec(spec)
sys.modules['check'] = check
spec.loader.exec_module(check)
spec = importlib.util.spec_from_file_location('release_artifacts', CI / 'artifacts.py')
artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifacts)


@pytest.mark.parametrize('bad', ['failure', 'error', 'skipped'])
def test_ci_cannot_pass_with_unverified_cases(tmp_path, bad):
    path = tmp_path / 'results.xml'
    path.write_text('<testsuite>' + '<testcase/>' * 688 + f'<testcase><{bad}/></testcase></testsuite>')
    with pytest.raises(ValueError, match='failed, errored, or was skipped'):
        check.check_junit(path)


def test_ci_requires_entire_suite(tmp_path):
    path = tmp_path / 'results.xml'
    path.write_text('<testsuite><testcase/></testsuite>')
    with pytest.raises(ValueError, match='Full test suite'):
        check.check_junit(path)


def test_version_mismatch_is_detected(tmp_path):
    (tmp_path / 'src/chatexporter/config').mkdir(parents=True)
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion="0.0.1"')
    (tmp_path / 'src/chatexporter/config/version.py').write_text('__version__="0.0.1rc3"')
    with pytest.raises(ValueError, match='source version differ'):
        check.version(tmp_path)


@pytest.mark.parametrize('installer_state', ['absent', 'modified'])
def test_incomplete_or_modified_installer_is_rejected(tmp_path, monkeypatch, installer_state):
    monkeypatch.setattr(artifacts, 'version', lambda: '0.0.1rc3')
    report = {'version': '0.0.1rc3', 'smoke_test': [{'ok': True}], 'installer': {'sha256': 'wrong'}}
    (tmp_path / 'build_report.json').write_text(json.dumps(report))
    if installer_state == 'modified':
        (tmp_path / 'installer').mkdir()
        (tmp_path / 'installer/ChatExporter-Setup-0.0.1rc3.exe').write_bytes(b'modified')
    with pytest.raises(ValueError, match='Installer is absent or does not match'):
        artifacts.prepare(tmp_path, tmp_path / 'release', 'source')
    assert not (tmp_path / 'release').exists()
