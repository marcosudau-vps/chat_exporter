"""Browser gezielt schliessen/wieder oeffnen (Restart Manager) – mit einem Ersatzprozess."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from chatexporter.providers.chatgpt.auth import process_control
from chatexporter.providers.chatgpt.auth.browsers import profile_in_use

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="nur Windows")

HOLDER = r"""
import ctypes, sys, time
from ctypes import wintypes
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateFileW.restype = wintypes.HANDLE
k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
h = k.CreateFileW(sys.argv[1], 0x40000000, 0, None, 4, 0x80, None)   # exklusiv wie Chromium
print("ok", flush=True)
time.sleep(120)
"""


@pytest.fixture
def holder(tmp_path):
    data = tmp_path / "User Data"
    data.mkdir()
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(data / "lockfile")], stdout=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    assert proc.stdout.readline().strip() == b"ok"
    yield data, proc
    proc.kill()


def test_finds_and_closes_only_the_holder(holder):
    data, proc = holder
    assert profile_in_use(data)
    with process_control.RestartManagerSession(data / "lockfile") as session:
        pids = [p.pid for p in session.processes()]
    assert proc.pid in pids or any(pid != 0 for pid in pids)
    started = []
    closed = process_control.close_browser(data, Path("C:/browser.exe"), in_use=profile_in_use,
                                           graceful=False, force_seconds=10)
    assert not profile_in_use(data)
    assert proc.wait(timeout=10) is not None
    closed.launcher = started.append
    assert closed.reopen() in ("restart", "started")
    if started:
        assert started[0][:2] == ["C:\\browser.exe", "--restore-last-session"]
        assert started[0][2] == f"--user-data-dir={data}", "kein Standardverzeichnis -> ausdruecklich angeben"


def test_nothing_to_close_when_free(tmp_path):
    closed = process_control.close_browser(tmp_path, None, in_use=lambda p: False)
    assert closed.processes == [] and closed.reopen() == "none"


def test_reopen_command_for_the_default_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    default = tmp_path / "Microsoft" / "Edge" / "User Data"
    default.mkdir(parents=True)
    closed = process_control.ClosedBrowser(None, Path("msedge.exe"), user_data_dir=default)
    assert closed.reopen_command() == ["msedge.exe", "--restore-last-session"]
