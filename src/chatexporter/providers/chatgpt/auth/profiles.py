"""Browser-Profile finden, auf ChatGPT-Anmeldung pruefen und kopieren.

- ``list_profiles``: Profile eines installierten Browsers (Edge/Chrome) aus
  ``Local State`` (Anzeigename) bzw. den Profilordnern.
- ``chatgpt_cookie_status``: enthaelt das Profil ChatGPT-Cookies, insbesondere
  das Sitzungs-Cookie? Gelesen werden nur **Namen** und Domains, nie Werte.
- ``copy_profile``: kopiert ``Local State`` und einen Profilordner (ohne
  Caches) in ein eigenes Datenverzeichnis. Mit der Kopie kann der Lauf arbeiten,
  waehrend der normale Browser offen ist. Kopiert wird nur, wenn der Browser
  geschlossen ist (sonst sind die Dateien gesperrt und die Kopie inkonsistent).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from chatexporter.providers.chatgpt.auth.browsers import LABELS, default_user_data_dir, profile_in_use

CHATGPT_HOSTS = ("chatgpt.com", "chat.openai.com", "openai.com")
SESSION_COOKIE = "__Secure-next-auth.session-token"
#: Grosse, fuer die Anmeldung unnoetige Ordner, die nicht mitkopiert werden.
SKIP_DIRS = {"Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache",
             "GrShaderCache", "ShaderCache", "CacheStorage", "ScriptCache", "Crashpad", "component_crx_cache",
             "optimization_guide_model_store", "Safe Browsing", "BrowserMetrics"}
COPY_MARKER = "chatexporter_copy.json"


@dataclass
class BrowserProfile:
    kind: str
    user_data_dir: Path       # Wurzel (z. B. ...\Edge\User Data)
    directory: str            # Profilordner (Default, Profile 1, ...)
    name: str                 # Anzeigename
    chatgpt: bool | None = None   # None = nicht pruefbar
    detail: str = ""

    @property
    def path(self) -> Path:
        return self.user_data_dir / self.directory

    @property
    def label(self) -> str:
        return f"{LABELS.get(self.kind, self.kind)} – Profil '{self.name}' ({self.directory})"


def _profile_dirs(root: Path) -> list[tuple[str, str]]:
    names: dict[str, str] = {}
    try:
        state = json.loads((root / "Local State").read_text(encoding="utf-8"))
        cache = (state.get("profile") or {}).get("info_cache") or {}
        names = {key: str((value or {}).get("name") or key) for key, value in cache.items()}
    except (OSError, ValueError, AttributeError):
        names = {}
    found = []
    for entry in sorted(root.iterdir()) if root.is_dir() else []:
        if entry.is_dir() and (entry.name == "Default" or entry.name.startswith("Profile ")) \
                and (entry / "Preferences").exists():
            found.append((entry.name, names.get(entry.name, entry.name)))
    for key, name in names.items():
        if (root / key).is_dir() and key not in [d for d, _ in found]:
            found.append((key, name))
    return found


def chatgpt_cookie_status(profile_path: Path) -> tuple[bool | None, str]:
    """(True/False/None, Erklaerung). Liest nur Namen und Domains der Cookies."""
    candidates = [profile_path / "Network" / "Cookies", profile_path / "Cookies"]
    db = next((c for c in candidates if c.is_file()), None)
    if db is None:
        return False, "keine Cookie-Datenbank"
    rows = None
    try:
        uri = db.resolve().as_uri() + "?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True, timeout=1) as conn:
            rows = conn.execute("SELECT host_key, name FROM cookies").fetchall()
    except sqlite3.Error:
        rows = None
    if rows is None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "Cookies"
                shutil.copy2(db, copy)
                with sqlite3.connect(copy) as conn:
                    rows = conn.execute("SELECT host_key, name FROM cookies").fetchall()
        except (OSError, sqlite3.Error) as exc:
            return None, f"Cookies nicht lesbar ({type(exc).__name__}; Browser geoeffnet?)"
    relevant = [(h, n) for h, n in rows if any(str(h).lstrip(".").endswith(host) for host in CHATGPT_HOSTS)]
    session = any(str(n).startswith(SESSION_COOKIE) for _, n in relevant)
    if session:
        return True, f"ChatGPT-Sitzungs-Cookie vorhanden ({len(relevant)} ChatGPT-Cookies)"
    if relevant:
        return False, f"{len(relevant)} ChatGPT-Cookies, aber kein Sitzungs-Cookie (abgemeldet?)"
    return False, "keine ChatGPT-Cookies"


def list_profiles(kind: str, root: Path | None = None, *, check_cookies: bool = True) -> list[BrowserProfile]:
    root = root or default_user_data_dir(kind)
    if root is None or not root.is_dir():
        return []
    out = []
    for directory, name in _profile_dirs(root):
        profile = BrowserProfile(kind, root, directory, name)
        if check_cookies:
            profile.chatgpt, profile.detail = chatgpt_cookie_status(profile.path)
        out.append(profile)
    # Profile mit ChatGPT-Sitzung zuerst, dann unbekannte, dann ohne.
    order = {True: 0, None: 1, False: 2}
    return sorted(out, key=lambda p: (order[p.chatgpt], p.directory != "Default", p.directory))


def copy_target(browser_root: Path, profile: BrowserProfile, *, now: datetime | None = None) -> Path:
    """``<browser_root>/profiles/<JJJJ-MM-TT_hh-mm-ss>_<Profilordner>`` (Ortszeit der Kopie).

    Die Browser-Art steht in der Info-Datei der Kopie (``COPY_MARKER``)."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    return Path(browser_root) / "profiles" / f"{stamp}_{profile.directory.replace(' ', '_')}"


def _same_path(a: object, b: object) -> bool:
    import os
    try:
        return os.path.normcase(str(Path(str(a)).resolve())) == os.path.normcase(str(Path(str(b)).resolve()))
    except OSError:
        return False


def copy_of(copies: list[tuple[Path, dict]], profile: BrowserProfile) -> Path | None:
    """Neueste vorhandene Kopie dieses Profils (gleiche Browser-Art und Quelle)."""
    for path, info in copies:
        if info.get("kind") == profile.kind and _same_path(info.get("source"), profile.path):
            return path
    return None


def existing_copies(browser_root: Path) -> list[tuple[Path, dict]]:
    """Vorhandene Profilkopien, neueste zuerst."""
    base = Path(browser_root) / "profiles"
    out = []
    for entry in sorted(base.iterdir(), reverse=True) if base.is_dir() else []:
        marker = entry / COPY_MARKER
        if marker.is_file():
            try:
                out.append((entry, json.loads(marker.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
    return out


def _select_only(local_state: Path, directory: str) -> None:
    """In der KOPIE von ``Local State`` nur das kopierte Profil fuehren und als
    zuletzt benutzt markieren (der Browser oeffnet es dann ohne Profilauswahl).
    Alles andere, insbesondere der Cookie-Schluessel ``os_crypt``, bleibt unveraendert."""
    try:
        state = json.loads(local_state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    section = state.setdefault("profile", {})
    cache = section.get("info_cache")
    if isinstance(cache, dict):
        section["info_cache"] = {key: value for key, value in cache.items() if key == directory}
    section["last_used"] = directory
    section["last_active_profiles"] = [directory]
    local_state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def copy_profile(profile: BrowserProfile, target: Path, *, say: Callable[[str], None] = lambda _m: None,
                 in_use: Callable[[Path], bool] = profile_in_use) -> Path:
    """Kopiert ``Local State`` + Profilordner nach ``target`` (neues Datenverzeichnis).

    Atomar: erst in ``<target>.partial``, am Ende umbenannt. Rueckgabe: ``target``.
    """
    if in_use(profile.user_data_dir):
        raise RuntimeError(f"{LABELS.get(profile.kind, profile.kind)} ist noch geoeffnet; "
                           "das Profil kann erst nach dem Schliessen kopiert werden")
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)

    def ignore(folder: str, names: list[str]) -> set[str]:
        return {n for n in names if n in SKIP_DIRS or n.endswith(("LOCK", ".lock")) or n == "lockfile"}

    try:
        shutil.copy2(profile.user_data_dir / "Local State", partial / "Local State")
        _select_only(partial / "Local State", profile.directory)
        say(f"Kopiere {profile.label} ...")
        shutil.copytree(profile.path, partial / profile.directory, ignore=ignore)
        (partial / COPY_MARKER).write_text(json.dumps({
            "source": str(profile.path), "kind": profile.kind, "directory": profile.directory,
            "name": profile.name, "copied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial.replace(target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    say(f"Kopie fertig: {target} ({size // (1024 * 1024)} MB)")
    return target
