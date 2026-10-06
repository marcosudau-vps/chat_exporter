"""Einstieg: Config finden, laden, setzen, zuruecksetzen, Vorlage anlegen, spiegeln."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .errors import ConfigError
from .mirror import Mirror, NullMirror, now_iso
from .resolver import Resolved, resolve
from .schema import Schema
from .sources import Layer, environment_layer, flatten, overrides_layer, read_yaml, _text_value
from .template import dump_value, render_template
from .yaml_edit import set_value, unset_value

Notice = Callable[[str], None]


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


@dataclass
class Scope:
    """Zusaetzliche, spezifischere Ebene ueber der Grund-Config (z. B. ein Datenbestand).

    ``config_file`` und ``env_file`` liegen ueblicherweise im Scope-Ordner;
    relative Pfade aus diesen Dateien gelten relativ zu ``base``.
    """

    name: str
    config_file: Path
    env_file: Path | None = None
    base: Path | None = None
    mirror: Mirror | None = None
    header: tuple[str, ...] = ()

    @property
    def layer_names(self) -> tuple[str, str]:
        return self.name, f"{self.name} .env"

    @property
    def folder(self) -> Path:
        return self.base or self.config_file.parent


@dataclass
class Loaded:
    """Ergebnis eines Ladevorgangs."""

    resolved: Resolved
    config_file: Path
    created: bool = False
    env_file: Path | None = None
    scope: Scope | None = None
    scope_created: bool = False

    @property
    def base(self) -> Path:
        return self.config_file.parent

    def base_for(self, path: str) -> Path:
        """Bezugsordner fuer relative Pfade: der Ordner der Ebene, aus der der Wert stammt."""
        if self.scope is not None and self.origin(path) in self.scope.layer_names:
            return self.scope.folder
        return self.base

    @property
    def document(self) -> dict[str, Any]:
        return self.resolved.document

    @property
    def values(self) -> dict[str, Any]:
        return self.resolved.values

    def get(self, path: str, default: Any = None) -> Any:
        return self.resolved.get(path, default)

    def origin(self, path: str) -> str | None:
        return self.resolved.origin(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class ConfigManager:
    """Geschichtete Konfiguration eines Projekts.

    Reihenfolge (spaeter gewinnt): Schema-Defaults < Config-Datei < ``.env`` <
    Prozess-Umgebung < CLI-Werte. Die Config-Datei wird gesucht: ausdruecklicher
    Pfad > Umgebungsvariable ``config_env`` > ``discover()`` > ``home()/config_name``.
    Fehlt sie, wird die vollstaendige, auskommentierte Vorlage angelegt.
    """

    def __init__(self, schema: Schema, *, env_prefix: str, home: Callable[[], Path],
                 config_name: str = "config.yaml", config_env: str | None = None,
                 discover: Callable[[], Path | None] | None = None,
                 env_file_setting: str | None = None, dotenv_exclude: Iterable[str] = (),
                 mirror: Mirror | None = None, header: Iterable[str] = (),
                 preprocess: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 notice: Notice | None = None, backups: int = 10,
                 scope: Callable[[Resolved, Path], Scope | None] | None = None) -> None:
        self.schema = schema
        self.env_prefix = env_prefix
        self.home = home
        self.config_name = config_name
        self.config_env = config_env
        self.discover = discover
        self.env_file_setting = env_file_setting
        self.dotenv_exclude = set(dotenv_exclude)
        self.mirror = mirror or NullMirror()
        self.header = list(header)
        self.preprocess = preprocess
        self.notice = notice or _stderr
        self.backups = backups
        #: Liefert zur vorlaeufig aufgeloesten Grund-Konfiguration die Scope-Ebene (oder None).
        self.scope = scope
        self._mirrored: str | None = None

    # -- Datei --------------------------------------------------------------
    def locate(self, explicit: Path | str | None = None, environ: Mapping[str, str] | None = None) -> Path:
        env = os.environ if environ is None else environ
        if explicit is not None:
            return Path(explicit).expanduser().resolve()
        if self.config_env and env.get(self.config_env):
            return Path(str(env[self.config_env])).expanduser().resolve()
        if self.discover is not None:
            found = self.discover()
            if found is not None:
                return Path(found).resolve()
        return (Path(self.home()).expanduser() / self.config_name).resolve()

    def template(self) -> str:
        return render_template(self.schema, header=self.header, env_prefix=self.env_prefix)

    def scope_template(self, scope: Scope) -> str:
        """Vorlage der Scope-Datei: nur Einstellungen, die dort gelten duerfen."""
        return render_template(self.schema.scoped(), header=scope.header or self.header,
                               env_prefix=self.env_prefix)

    def create_config_file(self, path: Path) -> None:
        """Legt die vollstaendige, auskommentierte Vorlage an (nur wenn die Datei fehlt)."""
        if path.exists():
            return
        atomic_write_text(path, self.template())

    def _backup(self, path: Path) -> Path | None:
        if not path.exists():
            return None
        folder = path.parent / ".config_backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = folder / f"{path.name}.{stamp}.bak"
        target.write_bytes(path.read_bytes())
        if self.backups > 0:
            old = sorted(folder.glob(f"{path.name}.*.bak"))
            for extra in old[: max(0, len(old) - self.backups)]:
                try:
                    extra.unlink()
                except OSError:
                    pass
        return target

    # -- Laden ----------------------------------------------------------------
    def _env_file(self, base: Path, layers: list[Layer]) -> Path | None:
        if not self.env_file_setting:
            return None
        provisional = resolve(self.schema, layers)
        raw = provisional.values.get(self.env_file_setting)
        if raw in (None, ""):
            return None
        candidate = Path(str(raw)).expanduser()
        return candidate if candidate.is_absolute() else (base / candidate).resolve()

    def load(self, explicit: Path | str | None = None, overrides: Iterable[str] | Mapping[str, Any] = (),
             environ: Mapping[str, str] | None = None, *, mirror: bool = True,
             force_mirror: bool = False) -> Loaded:
        env = dict(os.environ if environ is None else environ)
        path = self.locate(explicit, env)
        created = False
        if not path.exists():
            self.create_config_file(path)
            created = True
            self.notice(f"Hinweis: Config-Datei fehlte, vollstaendige Vorlage angelegt: {path}")
        file_layer = Layer("config", flatten(self._read(path), self.schema), str(path))
        cli_layer = overrides_layer(overrides, name="cli")
        process_layer = environment_layer(env, self.schema, prefix=self.env_prefix, name="env")
        env_file = self._env_file(path.parent, [file_layer, process_layer, cli_layer])
        layers = [file_layer]
        if env_file is not None and env_file.is_file():
            layers.append(self._dotenv_layer(env_file, ".env"))
        scope = None
        scope_created = False
        if self.scope is not None:
            scope = self.scope(resolve(self.schema, [*layers, process_layer, cli_layer]), path.parent)
        if scope is not None:
            if not scope.config_file.exists():
                atomic_write_text(scope.config_file, self.scope_template(scope))
                scope_created = True
            file_name, env_name = scope.layer_names
            scope_layer = Layer(file_name, self._scoped(flatten(self._read(scope.config_file), self.schema),
                                                        scope.config_file), str(scope.config_file))
            layers.append(scope_layer)
            if scope.env_file is not None and scope.env_file.is_file():
                dot = self._dotenv_layer(scope.env_file, env_name)
                dot.values = self._scoped(dot.values, scope.env_file)
                layers.append(dot)
        layers += [process_layer, cli_layer]
        resolved = resolve(self.schema, layers)
        loaded = Loaded(resolved, path, created, env_file, scope, scope_created)
        if mirror:
            self._write_mirror(loaded, force=force_mirror)
        return loaded

    def _read(self, path: Path) -> dict[str, Any]:
        document = read_yaml(path)
        return self.preprocess(document) if self.preprocess is not None else document

    def _dotenv_layer(self, env_file: Path, name: str) -> Layer:
        from dotenv import dotenv_values
        exclude = set(self.dotenv_exclude)
        if self.env_file_setting:
            exclude.add(self.env_file_setting)
        dot = environment_layer(dotenv_values(env_file), self.schema, prefix=self.env_prefix,
                                name=name, exclude=exclude)
        dot.detail = str(env_file)
        return dot

    def _scoped(self, values: dict[str, Any], source: Path) -> dict[str, Any]:
        """Nur-global-Einstellungen aus einer Scope-Datei verwerfen (mit Hinweis)."""
        blocked = self.schema.global_only()
        dropped = sorted(k for k in values if k in blocked)
        if dropped:
            self.notice(f"Hinweis: in {source} nicht erlaubt (nur global), ignoriert: {', '.join(dropped)}")
        return {k: v for k, v in values.items() if k not in blocked}

    def _write_mirror(self, loaded: Loaded, *, force: bool = False) -> None:
        secrets = self.schema.secrets()
        values = {k: v for k, v in sorted(loaded.values.items()) if k not in secrets}
        scope = loaded.scope
        target = scope.mirror if scope is not None and scope.mirror is not None else self.mirror
        meta = {"config_file": str(loaded.config_file), "written_at": now_iso()}
        if scope is not None:
            meta["scope_config_file"] = str(scope.config_file)
        digest = hashlib.sha256(json.dumps([str(loaded.config_file), meta.get("scope_config_file"), values],
                                           sort_keys=True, default=str).encode("utf-8")).hexdigest()
        if not force and digest == self._mirrored:
            return
        try:
            target.write(values, meta)
        except OSError as exc:
            self.notice(f"Hinweis: Konfigurationsspiegel nicht geschrieben: {exc}")
            return
        self._mirrored = digest

    # -- Aendern ----------------------------------------------------------------
    def _target(self, explicit: Path | str | None, target: str, environ) -> tuple[Path, Callable[[], str]]:
        """Datei, die eine Aenderung betrifft: Grund-Config (``base``) oder Scope-Datei (``scope``)."""
        if target == "base":
            return self.locate(explicit, environ), self.template
        if target != "scope":
            raise ConfigError(f"Unbekannte Ebene: {target}")
        loaded = self.load(explicit, environ=environ, mirror=False)
        if loaded.scope is None:
            raise ConfigError("Keine Scope-Ebene aktiv")
        scope = loaded.scope
        return scope.config_file, lambda: self.scope_template(scope)

    def _check_target(self, path: str, target: str) -> None:
        setting = self.schema.get(path)
        if target == "scope" and setting is not None and setting.global_only:
            raise ConfigError(f"{path} gilt nur global und kann hier nicht gesetzt werden")

    def _edit(self, explicit: Path | str | None, change: Callable[[str], str], environ,
              target: str = "base") -> Loaded:
        path, template = self._target(explicit, target, environ)
        if not path.exists():
            atomic_write_text(path, template())
        old = path.read_text(encoding="utf-8-sig")
        new = change(old)
        if new == old:
            return self.load(explicit, environ=environ)
        self._backup(path)
        atomic_write_text(path, new)
        try:
            # Erst wenn die geaenderte Datei vollstaendig gueltig geladen ist,
            # gilt die Aenderung als angewendet (und wird gespiegelt).
            return self.load(explicit, environ=environ)
        except ConfigError:
            atomic_write_text(path, old)
            raise

    def set(self, path: str, value: Any, *, explicit: Path | str | None = None,
            environ: Mapping[str, str] | None = None, target: str = "base") -> Loaded:
        setting = self.schema.get(path)
        if setting is None:
            if self.schema.is_section(path):
                raise ConfigError(f"{path} ist ein Abschnitt; bitte einen einzelnen Schluessel setzen")
            raise ConfigError(f"Unbekannte Einstellung: {path}")
        if setting.secret:
            raise ConfigError(f"{path} ist geheim und gehoert in die .env oder die Umgebung, nicht in die Config-Datei")
        self._check_target(path, target)
        raw = _text_value(value) if isinstance(value, str) else value
        coerced = setting.coerce(raw)
        return self._edit(explicit, lambda text: set_value(text, path, dump_value(coerced)), environ, target)

    def set_many(self, values: Mapping[str, Any], *, explicit: Path | str | None = None,
                 environ: Mapping[str, str] | None = None, target: str = "base") -> Loaded:
        """Mehrere Werte in einem Schritt (eine Sicherung, eine Pruefung, ein Spiegel)."""
        prepared: list[tuple[str, str]] = []
        for path, value in values.items():
            setting = self.schema.get(path)
            if setting is None:
                raise ConfigError(f"Unbekannte Einstellung: {path}")
            if setting.secret:
                raise ConfigError(f"{path} ist geheim und gehoert nicht in die Config-Datei")
            self._check_target(path, target)
            raw = _text_value(value) if isinstance(value, str) else value
            prepared.append((path, dump_value(setting.coerce(raw))))

        def change(text: str) -> str:
            for path, dumped in prepared:
                text = set_value(text, path, dumped)
            return text
        return self._edit(explicit, change, environ, target)

    def reset(self, path: str | None = None, *, explicit: Path | str | None = None,
              environ: Mapping[str, str] | None = None, target: str = "base") -> Loaded:
        """Einen Schluessel (oder mit ``None`` die ganze Datei) auf den Standard zuruecksetzen."""
        if path is None:
            _path, template = self._target(explicit, target, environ)
            return self._edit(explicit, lambda _text: template(), environ, target)
        if self.schema.get(path) is None and not self.schema.is_section(path):
            raise ConfigError(f"Unbekannte Einstellung: {path}")
        return self._edit(explicit, lambda text: unset_value(text, path)[0], environ, target)

    def refresh(self, explicit: Path | str | None = None, overrides: Iterable[str] = (),
                environ: Mapping[str, str] | None = None) -> Loaded:
        """Neu laden (fehlende Datei wird angelegt) und den Spiegel neu schreiben."""
        return self.load(explicit, overrides, environ, force_mirror=True)
