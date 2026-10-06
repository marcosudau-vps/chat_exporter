# Provider `opencode`, `codex`, `claude`

Drei eigenständige Provider, jeweils **eine Datei** unter
`src/chatexporter/providers/`. Sie importieren nichts aus dem restlichen Paket
und bringen Konfiguration, atomares Schreiben und Redaktion selbst mit. Aus
pre-5 übernommen, inhaltlich unverändert (nur Dokumentationstexte angepasst).

| Provider | Quelle | Ablage |
| --- | --- | --- |
| `opencode` | lokale OpenCode-SQLite-DB (nur lesend, inkl. Child-/Subagent-Sessions), Tabelle `session_v2`, falls vorhanden, sonst `session`; Nutzdaten ausschließlich über `opencode session export <ID>` | `raw_storage/opencode/sessions/…` |
| `codex` | `~/.codex/sessions` (oder `source_root`) | bytegetreue Spiegelung nach `raw_storage/codex/sessions/…` |
| `claude` | `~/.claude/projects` (oder `source_root`) | bytegetreue Spiegelung nach `raw_storage/claude/projects/…` |

## Konfiguration (`providers.<quelle>` in der config.yaml)

| Provider | Schlüssel |
| --- | --- |
| `opencode` | `opencode_exe` (Default `opencode`), `db_path` (Default: über CLI ermittelt), `cli_cwd`, `timeout` (180), `max_retries` (2) |
| `codex`, `claude` | `source_root` (Default `~/.codex` bzw. `~/.claude`; auch der Unterordner `sessions`/`projects` direkt wird akzeptiert), `max_retries` (2), `verify_unchanged` (false; `true` vergleicht auch bei gleicher Größe/mtime per SHA-256) |

Im Updater-Lauf erhalten sie die Ablagepfade vom Raw Session Updater. Als eigenständige
Kommandozeile lesen sie `storage` und `providers.<quelle>` selbst aus der
config.yaml. Den Pfad übergibt die Bedienschicht automatisch.

## OpenCode: Änderungserkennung

Nach jedem Export vergleicht der Provider die Session-Signatur aus der
Datenbank mit der im Export (ID, Zeiten, Titel, Projekt, Verzeichnis, Parent,
Archiv). Nur bei Gleichheit wird gespeichert, sonst wird erneut exportiert.

- **Tabelle:** Neuere OpenCode-Versionen (belegt mit 1.18.32) führen
  Sitzungen in `session_v2`. Die alte Tabelle `session` enthielt am
  2026-10-01 nur 48 statt 54 Sitzungen und teils veraltete `time_updated`.
- **Verzeichnis:** Der Export führt es nur noch unter
  `info.location.directory`, in Windows-Schreibweise. Verglichen wird es
  normalisiert (Schrägstriche, Groß-/Kleinschreibung, abschließender
  Trenner).

Beides zusammen ließ im Lauf vom 2026-09-30 alle 48 Sessions mit „Session
wurde während des Exports verändert (Retry-Limit)“ scheitern. Seit der
Korrektur bestehen alle 54 Sitzungen die Prüfung (read-only nachgewiesen).

## Verhalten

- `update`: inkrementell (Größe/mtime, optional Hash), atomar über
  `.storage/staging/<quelle>/`. Im Updater-Lauf schreibt der Provider **keinen**
  eigenen Laufbericht; als eigenständige Kommandozeile (`update` ohne
  `--dry-run`) schreibt er einen Schema-4-Laufbericht nur für sich.
- `recreate_index`: Fragment mit namespaced Schlüsseln (`<quelle>:<kind>:…`).
  Einen eigenen persistenten Index führen diese Provider nicht.
- `check_storage_health`, `cleanup_storage`, `state_n_stats`: gemäß
  [Provider-Vertrag](../PROVIDER_VERTRAG.md).
