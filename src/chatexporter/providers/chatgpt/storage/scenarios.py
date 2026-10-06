"""Abschluss-/Mutations-Tests gegen eine KOPIE des Rohdatenbestands.

Zweck: Alle real denkbaren Daten-Konstellationen einmal gegenschleifen --
fehlender/korrupter Index, fehlende/korrupte Conversations, manipulierte
Rohdaten, fehlende/verfaelschte Library-Dateien, verwaiste Dateien, verlorene
Statusablage, Staging-Reste -- und pruefen, dass `verify-store` sie korrekt
erkennt und dass sich das Wiederherstellbare mit einem definierten Schritt
wieder herstellen laesst.

Sicherheit: Der Live-Bestand wird **nie** angefasst. Das Skript legt eine Kopie
an (`--source` -> `--work`) und arbeitet ausschliesslich dort. Jede Mutation wird
nach dem Szenario zurueckgerollt.

Beispiele:
    chatexporter-chatgpt scenarios --source <raw_root> --work <kopie-verzeichnis>
    chatexporter-chatgpt scenarios --root <bestehende-kopie> --scenario index_missing
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from chatexporter.providers.chatgpt.storage.integrity import verify_store
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.storage.status_store import FileIndex, rebuild_file_index, resolve_status_root


_RES: dict = {}


def _resolve_layout(store_root: Path, status_arg, source: str = "chatgpt",
                    runtime_arg=None) -> dict:
    """Erkennt Namespace- vs. flaches Legacy-Layout (read-only)."""
    store = Path(store_root)
    src = store / source
    if (src / "conversations").is_dir():
        runtime = Path(runtime_arg) if runtime_arg is not None else store.parent / ".storage"
        status = Path(status_arg) if status_arg is not None else runtime / "status_registry"
        return {"new": True, "src": src, "status": status,
                "index": status / "storage_index.json",
                "staging": runtime / "staging",
                "runtime": runtime}
    status = resolve_status_root(store, status_arg)
    return {"new": False, "src": store, "status": status,
            "index": store / "storage_index.json",
            "staging": store / ".staging",
            "runtime": store.parent / "runtime"}


def _src() -> Path:
    return _RES["src"]


def _index_file() -> Path:
    return _RES["index"]


def _staging_dir() -> Path:
    return _RES["staging"]


class Scratch:
    """Merkt sich den Originalzustand und stellt ihn am Ende wieder her."""

    def __init__(self) -> None:
        self._entries: list[tuple[Path, str, object]] = []
        self._tracked: set[str] = set()

    def track(self, path: Path) -> None:
        path = Path(path)
        key = str(path)
        if key in self._tracked:
            return
        self._tracked.add(key)
        if path.is_file():
            self._entries.append((path, "file", path.read_bytes()))
        elif path.is_dir():
            tmp = Path(tempfile.mkdtemp(prefix="scenario_backup_"))
            shutil.copytree(path, tmp / "data")
            self._entries.append((path, "dir", tmp))
        else:
            self._entries.append((path, "missing", None))

    def restore(self) -> None:
        for path, kind, payload in reversed(self._entries):
            try:
                if kind == "file":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)  # type: ignore[arg-type]
                elif kind == "dir":
                    if path.exists():
                        shutil.rmtree(path)
                    shutil.copytree(payload / "data", path)  # type: ignore[operator]
                    shutil.rmtree(payload, ignore_errors=True)  # type: ignore[arg-type]
                else:
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    elif path.exists():
                        path.unlink()
            except Exception as exc:  # noqa: BLE001
                print(f"  ! Wiederherstellen fehlgeschlagen: {path}: {exc}")
        self._entries = []


def _first_conversation(root: Path) -> Optional[Path]:
    return next(iter(sorted((root / "conversations").rglob("*.json"))), None)


def _first_library_dir(root: Path) -> Optional[Path]:
    for base in ("files", "audio"):
        b = root / "library" / base
        if b.exists():
            for d in sorted(p for p in b.iterdir() if p.is_dir()):
                return d
    return None


def _rebuild_all(root: Path, status_root: Path) -> None:
    if _RES.get("new"):
        repo = RawRepository(root, status_root, index_path=_index_file(),
                             staging_root=_RES["staging"])
    else:
        repo = RawRepository(root, status_root)
    repo.rebuild_index()
    rebuild_file_index(repo, repo.index.status_root)


def _rebuild_file_index_only(root: Path, status_root: Path) -> None:
    if _RES.get("new"):
        repo = RawRepository(root, status_root, index_path=_index_file(),
                             staging_root=_RES["staging"])
    else:
        repo = RawRepository(root, status_root)
    rebuild_file_index(repo, repo.index.status_root)


Apply = Callable[[Path, Path, Scratch], None]
Recover = Callable[[Path, Path], None]


@dataclass
class Scenario:
    name: str
    description: str
    apply: Apply
    expect_before_ok: bool
    expect_before_codes: tuple[str, ...] = ()
    recover: Optional[Recover] = None
    expect_after_ok: Optional[bool] = None
    expect_after_codes: tuple[str, ...] = ()
    recoverable: bool = True
    deep: bool = False
    requires: Optional[str] = None
    _samples: dict = field(default_factory=dict)


# -- Mutationen ------------------------------------------------------------

def _index_missing(root, status, ctx):
    ctx.track(_index_file())
    _index_file().unlink(missing_ok=True)


def _index_corrupt(root, status, ctx):
    ctx.track(_index_file())
    _index_file().write_text("{bad", encoding="utf-8")


def _index_bogus_entry(root, status, ctx):
    ctx.track(_index_file())
    data = json.loads(_index_file().read_text(encoding="utf-8"))
    data["conversations"]["00000000-0000-0000-0000-000000000000"] = {
        "relative_path": "conversations/1970-01/00000000-0000-0000-0000-000000000000.json",
        "title": "ghost", "json_complete": True, "files_complete": True,
    }
    _index_file().write_text(json.dumps(data), encoding="utf-8")


def _conversation_missing(root, status, ctx):
    path = _first_conversation(root)
    ctx.track(path)
    path.unlink()


def _conversation_corrupt(root, status, ctx):
    path = _first_conversation(root)
    ctx.track(path)
    path.write_text("{not json", encoding="utf-8")


def _raw_tampered(root, status, ctx):
    path = _first_conversation(root)
    ctx.track(path)
    env = json.loads(path.read_text(encoding="utf-8"))
    env["raw"]["title"] = "tampered-by-scenario"
    path.write_text(json.dumps(env), encoding="utf-8")


def _bucket_moved(root, status, ctx):
    path = _first_conversation(root)
    dest = path.parent.parent / "1900-01" / path.name
    ctx.track(path)
    ctx.track(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.rename(dest)


def _library_content_deleted(root, status, ctx):
    d = _first_library_dir(root)
    content = next(iter(sorted(d.glob("content.*"))))
    ctx.track(content)
    content.unlink()


def _library_content_tampered(root, status, ctx):
    d = _first_library_dir(root)
    content = next(iter(sorted(d.glob("content.*"))))
    ctx.track(content)
    data = content.read_bytes()
    patched = (b"X" if data[:1] != b"X" else b"Y") + data[1:]  # gleiche Groesse
    content.write_bytes(patched)


def _library_metadata_deleted(root, status, ctx):
    d = _first_library_dir(root)
    meta = d / "metadata.json"
    ctx.track(meta)
    meta.unlink()


def _library_orphan_added(root, status, ctx):
    target = root / "library" / "files" / "file_orphan_scenario"
    ctx.track(target)
    target.mkdir(parents=True, exist_ok=True)
    (target / "content.txt").write_bytes(b"orphan")
    (target / "metadata.json").write_text(json.dumps(
        {"schema_version": 1, "file_id": "file_orphan_scenario", "size": 6,
         "_local": {"conversation_id": "n/a"}}), encoding="utf-8")


def _file_index_wiped(root, status, ctx):
    fi = status / "file_index.json"
    ctx.track(fi)
    if fi.exists():
        data = json.loads(fi.read_text(encoding="utf-8"))
        data["files"] = {}
        fi.write_text(json.dumps(data), encoding="utf-8")


def _status_removed(root, status, ctx):
    ctx.track(status)
    if status.exists():
        shutil.rmtree(status)


def _staging_leftover(root, status, ctx):
    tmp = _staging_dir() / "leftover.tmp"
    ctx.track(tmp)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("leftover", encoding="utf-8")


SCENARIOS: list[Scenario] = [
    Scenario("index_missing", "storage_index.json fehlt", _index_missing,
             expect_before_ok=True, expect_before_codes=("index.missing",),
             recover=_rebuild_all, expect_after_ok=True, requires="index"),
    Scenario("index_corrupt", "storage_index.json ist korrupt", _index_corrupt,
             expect_before_ok=False, expect_before_codes=("index.corrupt",),
             recover=_rebuild_all, expect_after_ok=True, requires="index"),
    Scenario("index_bogus_entry", "Index verweist auf nicht existierende Conversation", _index_bogus_entry,
             expect_before_ok=False, expect_before_codes=("index.entry-without-file",),
             recover=_rebuild_all, expect_after_ok=True, requires="index"),
    Scenario("conversation_missing", "Conversation-Datei fehlt (Index verweist darauf)", _conversation_missing,
             expect_before_ok=False, expect_before_codes=("index.entry-without-file",),
             recover=_rebuild_all, expect_after_ok=True, requires="conversation"),
    Scenario("conversation_corrupt", "Conversation-JSON ist korrupt (Datenverlust -> Backup)", _conversation_corrupt,
             expect_before_ok=False, expect_before_codes=("envelope.unparseable",),
             recoverable=False, requires="conversation"),
    Scenario("raw_tampered", "raw-Payload manipuliert (Integritaet)", _raw_tampered,
             expect_before_ok=False, expect_before_codes=("envelope.raw-integrity",),
             recoverable=False, requires="conversation"),
    Scenario("bucket_moved", "Conversation im falschen Monats-Bucket", _bucket_moved,
             expect_before_ok=False, expect_before_codes=("naming.bucket-mismatch", "index.path-drift"),
             recover=_rebuild_all, expect_after_ok=True, requires="conversation"),
    Scenario("library_content_deleted", "Library-content.* fehlt", _library_content_deleted,
             expect_before_ok=False,
             expect_before_codes=("library.content-missing", "completeness.files-complete-drift"),
             recoverable=False, requires="library"),
    Scenario("library_content_tampered", "Library-content.* gleiche Groesse, anderer Inhalt", _library_content_tampered,
             expect_before_ok=False, expect_before_codes=("library.content-hash-mismatch",),
             deep=True, recoverable=False, requires="library"),
    Scenario("library_metadata_deleted", "Library-metadata.json fehlt", _library_metadata_deleted,
             expect_before_ok=False, expect_before_codes=("library.metadata-missing",),
             recoverable=False, requires="library"),
    Scenario("library_orphan_added", "Library-Eintrag ohne Dateireferenz", _library_orphan_added,
             expect_before_ok=True, expect_before_codes=("library.orphan",), requires="library"),
    Scenario("file_index_wiped", "Rueckwaertsindex geleert (rebuildbar)", _file_index_wiped,
             expect_before_ok=True, expect_before_codes=("file-index.missing-entry",),
             recover=_rebuild_file_index_only, expect_after_ok=True, requires="index"),
    Scenario("status_registry_removed", "Statusablage entfernt (Datenverlust ohne Re-Sync)", _status_removed,
             expect_before_ok=False, expect_before_codes=("completeness.files-complete-drift",),
             recoverable=False, requires="index"),
    Scenario("staging_leftover", "Temporaere Datei im Staging", _staging_leftover,
             expect_before_ok=True, expect_before_codes=("store.staging-leftover",),
             recover=lambda root, status: _staging_dir().joinpath("leftover.tmp").unlink(missing_ok=True),
             expect_after_ok=True, requires="index"),
]


def _requirement_met(requirement: Optional[str], root: Path, status: Path) -> bool:
    if requirement is None:
        return True
    if requirement == "conversation":
        return _first_conversation(_src()) is not None
    if requirement == "library":
        return _first_library_dir(_src()) is not None
    if requirement == "index":
        return _index_file().exists() or (_src() / "conversations").exists()
    return True


def _codes(report) -> set[str]:
    return {i.code for i in report.issues}


def run_scenarios(root: Path, status_root: Optional[Path], only: Optional[str] = None, *,
                  source: str = "chatgpt", runtime_root: Optional[Path] = None) -> int:
    store = Path(root)
    _RES.clear()
    _RES.update(_resolve_layout(store, status_root, source, runtime_root))
    src = _RES["src"]
    status = _RES["status"]
    print(f"Rohdaten (Kopie): {src}")
    print(f"Statusablage    : {status}")
    print(f"Layout          : {'namespace'} ({source})" if _RES["new"] else "Layout          : flach (legacy)")
    baseline = verify_store(store, status, source=source,
                            runtime_root=_RES["runtime"], index_path=_RES["index"])
    print(f"Baseline        : ok={baseline.ok}, errors={len(baseline.errors)}, warnings={len(baseline.warnings)}")
    print(json.dumps(baseline.counts, indent=2))
    if not baseline.ok:
        print("! Baseline ist nicht fehlerfrei -- Szenarien laufen trotzdem, aber bitte zuerst pruefen.")
    print("")

    passed = failed = skipped = 0
    for scenario in SCENARIOS:
        if only and scenario.name != only:
            continue
        if not _requirement_met(scenario.requires, src, status):
            print(f"SKIP  {scenario.name}: Voraussetzung '{scenario.requires}' nicht vorhanden")
            skipped += 1
            continue
        scratch = Scratch()
        try:
            # Index und Statusablage immer mitsichern: Recovery-Schritte
            # (z. B. Index-Rebuild) schreiben sonst dauerhaft und wuerden das
            # naechste Szenario verfaelschen.
            scratch.track(_index_file())
            scratch.track(status)
            scenario.apply(src, status, scratch)
            before = verify_store(store, status, deep=scenario.deep, source=source,
                                  runtime_root=_RES["runtime"], index_path=_RES["index"])
            ok_match = before.ok == scenario.expect_before_ok
            codes_match = all(c in _codes(before) for c in scenario.expect_before_codes)
            after_ok_match = True
            after_codes_match = True
            after = None
            if scenario.recover is not None:
                scenario.recover(src, status)
                after = verify_store(store, status, deep=scenario.deep, source=source,
                                     runtime_root=_RES["runtime"], index_path=_RES["index"])
                if scenario.expect_after_ok is not None:
                    after_ok_match = after.ok == scenario.expect_after_ok
                after_codes_match = all(c in _codes(after) for c in scenario.expect_after_codes)
            ok = ok_match and codes_match and after_ok_match and after_codes_match
        finally:
            scratch.restore()

        status_word = "PASS" if ok else "FAIL"
        recovered = "" if scenario.recover is None else (", nach Recovery ok" if after and after.ok else ", nach Recovery NICHT ok")
        rec = "" if scenario.recoverable else "  [nicht automatisch wiederherstellbar]"
        print(f"{status_word}  {scenario.name:<28} vorher_ok={before.ok} erwartet={scenario.expect_before_ok}{recovered}{rec}")
        if not ok:
            print(f"      Codes vorher : {sorted(_codes(before))}")
            if after is not None:
                print(f"      Codes nachher: {sorted(_codes(after))}")
        if ok:
            passed += 1
        else:
            failed += 1

    print("")
    print(f"Ergebnis: {passed} bestanden, {failed} fehlgeschlagen, {skipped} uebersprungen")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mutations-/Abschlusstests gegen eine Kopie des Rohdatenbestands")
    parser.add_argument("--source", type=Path, default=None,
                        help="Rohdatenbestand, von dem eine Kopie erstellt wird (Live-Bestand wird nicht angefasst)")
    parser.add_argument("--work", type=Path, default=None,
                        help="Zielverzeichnis fuer die Kopie (muss nicht existieren)")
    parser.add_argument("--root", type=Path, default=None,
                        help="Bereits vorhandene Kopie direkt nutzen (kein Kopieren)")
    parser.add_argument("--scenario", default=None, help="Nur dieses Szenario ausfuehren")
    parser.add_argument("--keep-copy", action="store_true", help="Erstellte Kopie nach dem Lauf behalten")
    args = parser.parse_args(argv)

    root = args.root
    created_copy = False
    copy_dir_to_remove = None
    if root is None:
        if args.source is None:
            parser.error("Entweder --root (vorhandene Kopie) oder --source + --work angeben")
        if args.work is None:
            parser.error("--work fehlt")
        work = Path(args.work)
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        root = work / "raw_storage"
        print(f"Erstelle Kopie: {args.source} -> {root} ...")
        shutil.copytree(args.source, root)
        # Runtime mitkopieren und INNERHALB des Arbeitsverzeichnisses ablegen,
        # damit die Kopie in sich geschlossen bleibt. Legacy-Fallback: alte
        # Statusablage neben dem Store.
        runtime_source = Path(args.source).parent / ".storage"
        if runtime_source.exists():
            shutil.copytree(runtime_source, work / ".storage")
        else:
            status_source = resolve_status_root(args.source)
            if status_source.exists():
                shutil.copytree(status_source, work / "status_registry")
        created_copy = True
        copy_dir_to_remove = work

    try:
        return run_scenarios(root, None, only=args.scenario)
    finally:
        if created_copy and not args.keep_copy and copy_dir_to_remove is not None:
            shutil.rmtree(copy_dir_to_remove, ignore_errors=True)
            print(f"Kopie entfernt: {copy_dir_to_remove}")


if __name__ == "__main__":
    raise SystemExit(main())
