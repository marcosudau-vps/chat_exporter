# layered_config – wiederverwendbare Konfiguration

`src/layered_config/` ist eine projektunabhängige Grundlage für geschichtete
Konfiguration. Sie enthält nichts ChatExporter-Spezifisches (per Test
gesichert: das Paket importiert nichts aus `chatexporter`) und lässt sich als
Ordner in andere Projekte übernehmen. Abhängigkeiten: PyYAML, optional
python-dotenv (für `.env`), unter Windows `winreg` (Standardbibliothek) für den
Registry-Spiegel. Der ChatExporter nutzt sie über `chatexporter.config`
([KONFIGURATION.md](KONFIGURATION.md)).

## Bausteine

| Modul | Aufgabe |
| --- | --- |
| `schema.py` | `Setting` (Pfad, Standard, Typ, Beschreibung, Beispielwert, Umgebungsnamen, `secret`, erlaubte Werte, `global_only`) und `Schema` (`scoped()` = Teilschema ohne nur-globale Einstellungen); Typumwandlung (`str`, `int`, `float`, `bool`, `path`, `list`, `dict`, `duration`, `any`) |
| `sources.py` | Quellen als flache Ebenen: YAML-Datei, Umgebung/`.env` (benannte und generische Namen `PREFIX__A__B`), CLI-Werte `a.b=wert` |
| `resolver.py` | `resolve()`: Standards, darüber die Ebenen in Reihenfolge; Ergebnis mit Werten, verschachteltem Dokument und Herkunft je Wert |
| `template.py` | vollständige Vorlage der Config-Datei: jede Einstellung eine auskommentierte Zeile, Standards echt, sonst erkennbare Beispielwerte |
| `yaml_edit.py` | einzelne Werte in einer YAML-Datei setzen/zurücksetzen, ohne Kommentare und Aufbau zu verlieren |
| `mirror.py` | Spiegel des angewendeten Zustands: `RegistryMirror` (HKCU, nur schreibend), `MemoryMirror` (Tests), `NullMirror` |
| `manager.py` | `ConfigManager`: Datei finden, fehlende Datei aus der Vorlage anlegen, laden, `set`/`reset`/`refresh` mit Sicherung und Rücksprung bei ungültigem Ergebnis, Spiegel nach erfolgreicher Anwendung; optional eine zusätzliche **Scope-Ebene** (`Scope`: eigene Datei + `.env` + Spiegel), Bearbeiten je Ebene (`target="base"|"scope"`) |

## Verwendung

```python
from pathlib import Path
from layered_config import ConfigManager, RegistryMirror, Schema, Setting

SCHEMA = Schema([
    Setting("server.port", 8080, "int", "Port", env=("MYAPP_PORT",)),
    Setting("server.mode", "auto", "str", "Modus", choices=("auto", "manual")),
    Setting("paths.data", None, "path", "Datenordner", example="D:/BEISPIEL/daten"),
    Setting("paths.env_file", ".env", "path", "Datei mit Secrets"),
    Setting("auth.token", None, "str", "Zugangstoken", secret=True),
])

config = ConfigManager(
    SCHEMA, env_prefix="MYAPP", home=lambda: Path("~/.myapp").expanduser(),
    config_env="MYAPP_CONFIG", env_file_setting="paths.env_file",
    mirror=RegistryMirror(r"Software\MyApp\config\Current", r"Software\MyApp\config"),
    header=["MyApp – Konfiguration"])

loaded = config.load(overrides=["server.port=9000"])     # legt fehlende Datei an, spiegelt
loaded.get("server.port"), loaded.origin("server.port")   # (9000, "cli")
config.set("server.mode", "manual")                       # dauerhaft in die Datei
config.reset("server.mode")                               # wieder Standard
```

Reihenfolge der Ebenen: Standard < Datei < `.env` < Umgebung < CLI-Werte.
Suche der Datei: ausdrücklicher Pfad > `config_env` > `discover()` (optional,
z. B. Suche ab dem Arbeitsordner) > `home()/config.yaml`.

**Scope-Ebene** (optional, z. B. je Datenbestand): `ConfigManager(scope=fn)`;
`fn(vorlaeufig_aufgeloest, ordner_der_datei)` liefert ein `Scope(name,
config_file, env_file, base, mirror, header)` oder `None`. Dann gilt:

```text
Standard < Datei < .env < Scope-Datei < Scope-.env < Umgebung < CLI-Werte
```

Die Scope-Datei wird bei Bedarf aus `scope_template()` angelegt (nur
Einstellungen ohne `global_only`); `global_only`-Werte in ihr werden mit
Hinweis verworfen. `Loaded.base_for(schluessel)` liefert den Bezugsordner für
relative Pfade (Scope-Ordner für Scope-Werte). Mit Scope schreibt der Spiegel
nach `Scope.mirror`. Der ChatExporter nutzt das für den Storage
([KONFIGURATION.md](KONFIGURATION.md)).

## Grenzen

- Die Bearbeitung arbeitet zeilenbasiert für Dateien im Stil der Vorlage
  (Einrückung mit Leerzeichen, ein Schlüssel je Zeile, einzeilige Werte; Listen
  und Objekte in Flow-Schreibweise `[a, b]`, `{a: 1}`). Mehrzeilige
  Block-Listen werden als Ganzes ersetzt bzw. auskommentiert.
- Unbekannte Schlüssel in der Datei bleiben beim Laden erhalten; `set` lehnt
  sie ab.
- Der Spiegel wird nie gelesen.
- Tests: `tests/layered_config/test_lc_core.py`, `tests/layered_config/test_lc_scope.py`.
