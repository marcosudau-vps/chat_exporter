"""Vollstaendige, auskommentierte Vorlage der Config-Datei.

Jede Einstellung steht als **eigene auskommentierte Zeile** (``# schluessel: wert``),
damit man einzelne Werte durch Entfernen des ``#`` setzen kann. Erklaerende
Zeilen beginnen mit ``##`` und werden nie als Einstellung gelesen. Einstellungen
mit Standardwert zeigen den echten Standard; alle anderen einen klar erkennbaren
Beispielwert.
"""

from __future__ import annotations

from typing import Any, Iterable

from .schema import Schema, Setting

INDENT = "  "
EXAMPLE_MARK = "BEISPIEL – kein Standardwert"


def dump_value(value: Any) -> str:
    """Ein Wert als einzeilige YAML-Darstellung (Listen/Objekte in Flow-Schreibweise)."""
    import yaml
    text = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10**9, sort_keys=False)
    text = text.strip()
    if text.endswith("\n..."):
        text = text[: -len("\n...")]
    elif text.endswith("..."):
        text = text[:-3].rstrip()
    return text.strip()


def _setting_lines(setting: Setting, depth: int, env_prefix: str | None) -> list[str]:
    pad = INDENT * depth
    lines: list[str] = []
    for text in (setting.description or "").splitlines():
        lines.append(f"##{pad or " "}{text}".rstrip())
    notes = []
    if setting.default is None:
        notes.append(EXAMPLE_MARK)
    if setting.choices:
        notes.append("erlaubt: " + ", ".join(map(str, setting.choices)))
    env = list(setting.env)
    if env_prefix:
        env.append(f"{env_prefix}__" + "__".join(p.upper() for p in setting.parts))
    if env:
        notes.append("Umgebung: " + ", ".join(env))
    for note in notes:
        lines.append(f"##{pad or " "}({note})")
    if setting.secret:
        value = '"<geheim – nur in der .env oder Umgebung setzen>"'
    elif setting.default is not None:
        value = dump_value(setting.default)
    else:
        value = dump_value(setting.example) if setting.example is not None else '""'
    lines.append(f"# {pad}{setting.parts[-1]}: {value}")
    return lines


def render_template(schema: Schema, *, header: Iterable[str] = (), env_prefix: str | None = None) -> str:
    out: list[str] = [f"## {line}".rstrip() for line in header]
    if out:
        out.append("")
    opened: tuple[str, ...] = ()
    for setting in schema:
        parents = setting.parts[:-1]
        common = 0
        while common < min(len(opened), len(parents)) and opened[common] == parents[common]:
            common += 1
        if parents[:1] != opened[:1] and out and out[-1] != "":
            out.append("")
        for depth in range(common, len(parents)):
            section_path = ".".join(parents[: depth + 1])
            out.append(f"# {INDENT * depth}{parents[depth]}:")
            description = schema.sections.get(section_path)
            if description:
                for text in description.splitlines():
                    out.append(f"##{INDENT * (depth + 1)}{text}".rstrip())
        opened = parents
        out.extend(_setting_lines(setting, len(parents), env_prefix))
    return "\n".join(out).rstrip() + "\n"
