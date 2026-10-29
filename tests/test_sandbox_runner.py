"""The sandbox runner must test the requested installer and optional upgrade baseline."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    'sandbox_runner', Path(__file__).resolve().parents[1] / 'packaging/sandbox/run_sandbox_test.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_missing_upgrade_baseline_stops_before_launch(tmp_path, monkeypatch):
    installer = tmp_path / 'ChatExporter-Setup-0.0.1.exe'
    installer.write_bytes(b'new installer')
    monkeypatch.setattr(runner, 'sandbox_running', lambda: False)
    monkeypatch.setattr(runner.os, 'startfile', lambda *args: (_ for _ in ()).throw(AssertionError('must not launch')))
    assert runner.main(['--installer', str(installer), '--upgrade-from', str(tmp_path / 'missing.exe')]) == 2


def test_upgrade_baseline_is_separate_and_removed_for_clean_install(tmp_path, monkeypatch):
    installer = tmp_path / 'ChatExporter-Setup-0.0.1.exe'
    baseline = tmp_path / 'ChatExporter-Setup-0.0.1rc3.exe'
    installer.write_bytes(b'new installer')
    baseline.write_bytes(b'old installer')
    work = tmp_path / 'sandbox'
    monkeypatch.setattr(runner, 'sandbox_running', lambda: False)

    def complete_sandbox(_):
        (work / 'out/results.txt').write_text('OK installation\n', encoding='utf-8')
        (work / 'out/done.txt').write_text('done', encoding='utf-8')

    monkeypatch.setattr(runner.os, 'startfile', complete_sandbox)
    args = ['--installer', str(installer), '--work', str(work)]
    assert runner.main([*args, '--upgrade-from', str(baseline)]) == 0
    assert (work / 'in/upgrade_baseline.exe').read_bytes() == b'old installer'
    assert list((work / 'in').glob('ChatExporter-Setup-*.exe')) == [work / 'in' / installer.name]
    assert runner.main(args) == 0
    assert not (work / 'in/upgrade_baseline.exe').exists()
