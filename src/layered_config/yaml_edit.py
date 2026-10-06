"""Einzelne Werte in einer YAML-Datei setzen oder zuruecksetzen, Kommentare bleiben.

Zeilenbasiert fuer den Aufbau, den ``template.py`` erzeugt (Einrueckung mit
Leerzeichen, ein Schluessel je Zeile, Werte einzeilig), und fuer handgeschriebene
Dateien desselben Stils:

- ``# schluessel: wert``  auskommentierte Einstellung (Vorlage)
- ``## text``             reine Erklaerung, nie eine Einstellung
- ``schluessel: wert``    aktive Einstellung (ein ``  # kommentar`` dahinter bleibt)

``set_value`` aktiviert eine vorhandene (auch auskommentierte) Zeile oder legt sie
an der passenden Stelle an; uebergeordnete Abschnittszeilen werden dabei
mitaktiviert. ``unset_value`` kommentiert die aktive Zeile (und ihren Block)
wieder aus, sodass der Standardwert gilt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ConfigError

_KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_][A-Za-z0-9_\-]*):(?P<rest>(?:\s.*)?)$")


@dataclass
class _Entry:
    index: int
    commented: bool
    indent: int
    key: str
    value: str        # Wertteil ohne Kommentar ("" bei Abschnittskopf)
    comment: str      # "  # ..." am Zeilenende oder ""
    path: str = ""


def _split_comment(rest: str) -> tuple[str, str]:
    """Trennt ``wert  # kommentar``; Anfuehrungszeichen werden beachtet."""
    quote = None
    for i, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or rest[i - 1] in " \t"):
            j = i
            while j > 0 and rest[j - 1] in " \t":
                j -= 1
            return rest[:j].strip(), rest[j:]
    return rest.strip(), ""


def _parse_line(index: int, line: str) -> _Entry | None:
    if line.startswith("##"):
        return None
    commented = line.startswith("#")
    body = line
    if commented:
        body = line[1:]
        if body.startswith(" "):
            body = body[1:]
    if body.lstrip().startswith("#") or body.lstrip().startswith("- "):
        return None
    match = _KEY.match(body)
    if not match:
        return None
    value, comment = _split_comment(match.group("rest"))
    return _Entry(index, commented, len(match.group("indent")), match.group("key"), value, comment)


def _entries(lines: list[str]) -> list[_Entry]:
    entries: list[_Entry] = []
    stack: list[_Entry] = []
    for i, line in enumerate(lines):
        entry = _parse_line(i, line)
        if entry is None:
            continue
        while stack and stack[-1].indent >= entry.indent:
            stack.pop()
        entry.path = ".".join([e.key for e in stack] + [entry.key])
        entries.append(entry)
        stack.append(entry)
    return entries


def _indent_of(line: str) -> int | None:
    """Einrueckung einer Inhaltszeile (aktiv oder auskommentiert); ``None`` fuer Leer-/Erklaerzeilen."""
    if not line.strip() or line.startswith("##"):
        return None
    body = line
    if line.startswith("#"):
        body = line[1:]
        if body.startswith(" "):
            body = body[1:]
    return len(body) - len(body.lstrip(" "))


def _block_end(lines: list[str], entry: _Entry, *, active_only: bool) -> int:
    """Index nach dem letzten Zeilenblock unter ``entry`` (tiefer eingerueckt)."""
    end = entry.index + 1
    for i in range(entry.index + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.startswith("##"):
            continue
        if active_only and line.lstrip().startswith("#"):
            continue
        indent = _indent_of(line)
        if indent is None or indent <= entry.indent:
            break
        end = i + 1
    return end


def _render(indent: int, key: str, value: str, comment: str = "") -> str:
    return f"{' ' * indent}{key}:{(' ' + value) if value != '' else ''}{comment}"


def _comment_out(line: str) -> str:
    return line if line.startswith("#") else f"# {line}"


def _uncomment(line: str) -> str:
    if not line.startswith("#") or line.startswith("##"):
        return line
    body = line[1:]
    return body[1:] if body.startswith(" ") else body


def find_active(text: str, path: str) -> bool:
    return any(e.path == path and not e.commented for e in _entries(text.splitlines()))


def set_value(text: str, path: str, value: str) -> str:
    """Setzt ``path`` auf den bereits YAML-formatierten Wert ``value``."""
    lines = text.splitlines()
    entries = _entries(lines)
    parts = path.split(".")
    active = [e for e in entries if e.path == path and not e.commented]
    commented = [e for e in entries if e.path == path and e.commented]

    def activate_parents(before_index: int) -> None:
        for depth in range(1, len(parts)):
            prefix = ".".join(parts[:depth])
            if any(e.path == prefix and not e.commented for e in _entries(lines)):
                continue
            candidates = [e for e in _entries(lines) if e.path == prefix and e.commented and e.index < before_index]
            if candidates:
                head = candidates[-1]
                lines[head.index] = _uncomment(lines[head.index])

    if active:
        target = active[-1]
        end = _block_end(lines, target, active_only=False)
        if end > target.index + 1 and target.value == "":
            # Ein aktiver Abschnitt wird zu einem Einzelwert: alte Unterzeilen auskommentieren.
            for i in range(target.index + 1, end):
                lines[i] = _comment_out(lines[i])
        lines[target.index] = _render(target.indent, target.key, value, target.comment)
        return "\n".join(lines) + "\n"
    def inside_active_ancestors(entry: _Entry) -> bool:
        """Liegt die auskommentierte Zeile innerhalb der aktiven Abschnitte ihres Pfads?"""
        for depth in range(1, len(parts)):
            prefix = ".".join(parts[:depth])
            heads = [e for e in entries if e.path == prefix and not e.commented]
            if heads and not any(h.index < entry.index < _block_end(lines, h, active_only=False) for h in heads):
                return False
        return True

    commented = [e for e in commented if inside_active_ancestors(e)]
    if commented:
        target = commented[-1]
        lines[target.index] = _render(target.indent, target.key, value, target.comment)
        activate_parents(target.index)
        return "\n".join(lines) + "\n"

    # Neu anlegen: unter dem tiefsten vorhandenen Abschnitt (aktiv bevorzugt).
    for depth in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:depth])
        heads = [e for e in entries if e.path == prefix and not e.commented] or \
                [e for e in entries if e.path == prefix and e.commented]
        if heads:
            head = heads[-1]
            if head.value != "":
                raise ConfigError(f"{prefix} hat einen Einzelwert und kann keinen Unterpunkt {path} aufnehmen")
            insert_at = head.index + 1
            new = [_render(head.indent + 2 * (k + 1 - depth), parts[k], "") for k in range(depth, len(parts) - 1)]
            new.append(_render(head.indent + 2 * (len(parts) - depth), parts[-1], value))
            lines[insert_at:insert_at] = new
            if head.commented:
                lines[head.index] = _uncomment(lines[head.index])
            activate_parents(head.index)
            return "\n".join(lines) + "\n"
    new = [_render(2 * k, parts[k], "") for k in range(len(parts) - 1)]
    new.append(_render(2 * (len(parts) - 1), parts[-1], value))
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(new)
    return "\n".join(lines) + "\n"


def unset_value(text: str, path: str) -> tuple[str, bool]:
    """Kommentiert die aktive Einstellung ``path`` (samt Block) aus. Rueckgabe: (Text, geaendert)."""
    lines = text.splitlines()
    active = [e for e in _entries(lines) if e.path == path and not e.commented]
    if not active:
        return text, False
    for target in reversed(active):
        end = _block_end(lines, target, active_only=True)
        for i in range(target.index, end):
            if lines[i].strip() and not lines[i].lstrip().startswith("#"):
                lines[i] = _comment_out(lines[i])
    return "\n".join(lines) + "\n", True
