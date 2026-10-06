"""Chrome for Testing: Version ermitteln, herunterladen, pruefen, entpacken.

Letzte Stufe der Profilsuche, nur nach ausdruecklicher Bestaetigung. Ablage:
``<browser_root>/chrome-for-testing/<version>/chrome-win64/chrome.exe``.
Ein abgebrochener oder kaputter Download hinterlaesst keine halbe Installation:
entpackt wird in einen temporaeren Ordner, der erst am Ende umbenannt wird.
"""

from __future__ import annotations

import json
import shutil
import ssl
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

PLATFORM = "win64"
EXE_RELATIVE = Path("chrome-win64") / "chrome.exe"
MIN_ZIP_BYTES = 10 * 1024 * 1024        # ein echtes Archiv ist > 100 MB; alles unter 10 MB ist kaputt
TIMEOUT_SECONDS = 60


class ChromeForTestingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    url: str


def ssl_context() -> ssl.SSLContext:
    """Zertifikatspruefung ueber den Zertifikatsspeicher des Systems (``truststore``).

    Pythons eigene Pruefung (OpenSSL) laedt fehlende Stammzertifikate nicht nach;
    auf einem frischen Windows schlug der Download deshalb mit
    ``CERTIFICATE_VERIFY_FAILED`` fehl (Windows Sandbox, 2026-10-04). Mit
    ``truststore`` prueft Windows selbst und ergaenzt Stammzertifikate bei Bedarf.
    Ohne ``truststore`` bleibt es bei der Standardpruefung.
    """
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS, context=ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, target: Path, progress: Callable[[str], None]) -> None:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS, context=ssl_context()) as response,             open(target, "wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done, step = 0, 10
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if total and done * 100 // total >= step:
                progress(f"  Download {done * 100 // total} % ({done // (1024 * 1024)} MB)")
                step += 10


def latest_release(url: str, *, fetch: Callable[[str], Any] = _fetch_json) -> Release:
    try:
        data = fetch(url)
        stable = data["channels"]["Stable"]
        version = str(stable["version"])
        entries = stable["downloads"]["chrome"]
        link = next(e["url"] for e in entries if e.get("platform") == PLATFORM)
    except (KeyError, StopIteration, TypeError) as exc:
        raise ChromeForTestingError(f"Versionsliste unvollstaendig ({exc})") from None
    except (OSError, ValueError) as exc:
        raise ChromeForTestingError(f"Versionsliste nicht abrufbar: {exc}") from None
    if not version or not link.startswith("https://"):
        raise ChromeForTestingError("Versionsliste enthaelt keinen gueltigen Download")
    return Release(version, link)


def installed_executable(root: Path) -> Path | None:
    """Neueste bereits installierte Version."""
    base = Path(root) / "chrome-for-testing"
    if not base.is_dir():
        return None
    found = []
    for entry in base.iterdir():
        exe = entry / EXE_RELATIVE
        if entry.is_dir() and not entry.name.startswith(".") and exe.is_file():
            try:
                found.append((tuple(int(p) for p in entry.name.split(".")), exe))
            except ValueError:
                continue
    return max(found)[1] if found else None


def install(root: Path, release: Release, *, progress: Callable[[str], None] = lambda _m: None,
            download: Callable[[str, Path, Callable[[str], None]], None] = _download) -> Path:
    """Laedt und entpackt eine Version; vorhandene Installation wird wiederverwendet."""
    base = Path(root) / "chrome-for-testing"
    target = base / release.version
    exe = target / EXE_RELATIVE
    if exe.is_file():
        return exe
    staging = base / ".download"
    staging.mkdir(parents=True, exist_ok=True)
    archive = staging / f"chrome-{release.version}.zip"
    partial = base / f".{release.version}.partial"
    try:
        progress(f"Lade Chrome for Testing {release.version} herunter ...")
        download(release.url, archive, progress)
        if archive.stat().st_size < MIN_ZIP_BYTES:
            raise ChromeForTestingError(f"Download zu klein ({archive.stat().st_size} Bytes)")
        if not zipfile.is_zipfile(archive):
            raise ChromeForTestingError("Download ist kein ZIP-Archiv")
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise ChromeForTestingError(f"ZIP-Archiv beschaedigt ({bad})")
            names = zf.namelist()
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise ChromeForTestingError("ZIP-Archiv enthaelt unzulaessige Pfade")
            if partial.exists():
                shutil.rmtree(partial)
            zf.extractall(partial)
        if not (partial / EXE_RELATIVE).is_file():
            raise ChromeForTestingError(f"{EXE_RELATIVE} fehlt im Archiv")
        partial.replace(target)
    except ChromeForTestingError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ChromeForTestingError(f"Installation fehlgeschlagen: {exc}") from None
    finally:
        if partial.exists():
            shutil.rmtree(partial, ignore_errors=True)
        archive.unlink(missing_ok=True)
    progress(f"Chrome for Testing {release.version} installiert: {exe}")
    return exe
