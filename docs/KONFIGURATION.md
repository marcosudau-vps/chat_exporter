# Konfiguration

Alle Schichten (Raw Session Updater, Provider, Exporter, Zeitplanung,
Bedienschicht) lesen ihre Einstellungen über **ein** gemeinsames Modul,
`chatexporter.config`. Es baut auf der projektunabhängigen Bibliothek
`layered_config` auf (siehe [CONFIG_BIBLIOTHEK.md](CONFIG_BIBLIOTHEK.md)).

## 1. Wo liegt was?

Programm und Datenhaltung sind getrennt: Das Programm arbeitet mit einem
**Storage** – einer autarken Dateninstanz mit eigenen Daten, eigenem Zustand,
eigener Konfiguration und eigenem Registry-Bereich (Begriff und Beschlüsse:
[STORAGE_KONZEPT.md](STORAGE_KONZEPT.md)). Standard ist
`~/.chatexporter/storages/default`; ein anderer wird mit `--storage PFAD`,
`CHATEXPORTER_STORAGE` oder `storage.root` gewählt.

**Installiertes Programm:**

```text
~/.chatexporter/                     Home (CHATEXPORTER_HOME überschreibt den Ort)
├── config.yaml                      globale Konfiguration: Grundwerte, Browser, Programm
├── .env                             globale Secrets/Overrides
├── .config_backups/                 Sicherungen vor jedem config-global set/reset
├── browser/                         Browser für ChatGPT (global, kein Teil eines Storages)
│   ├── profiles/                    Profilkopien (<JJJJ-MM-TT_hh-mm-ss>_<Profilordner>) und eigene Profile
│   └── chrome-for-testing/          heruntergeladener Chrome for Testing (nur nach Rückfrage)
└── storages/default/                Standard-Storage
    ├── .storage/                    Verwaltungsbereich
    │   ├── storage.yaml             Marker: storage_schema (Storage-Schema 2), ID, Name, Anlagezeitpunkt
    │   ├── config.yaml              Storage-Konfiguration (spezifischer als die globale)
    │   ├── .env                     Storage-Secrets
    │   ├── .config_backups/         Sicherungen vor jedem config set/reset
    │   ├── state.yaml               Gesamtsicht (nur geschrieben, siehe Abschnitt 5)
    │   ├── logs/                    Befehlsprotokoll dieses Storages
    │   ├── runs/ status_registry/ tasks_sched.json OVERVIEW.md
    │   ├── staging/                 Zwischenablage; leere Ordner werden nach jedem Befehl entfernt
    │   └── lock                     Sperre: höchstens ein schreibender Lauf je Storage
    ├── raw_storage/<quelle>/        Quelldaten je Quelle
    └── exports/                     Exporte (Markdown/JSON)
```

**Entwicklung** (Start aus dem Quellcode): Die `workspace/config.yaml` ist die
globale Konfiguration; ihr `storage.data_root: data` (älterer Name für
`storage.root`) wählt `workspace/data` als Storage.

Ein leerer oder fehlender Ordner wird beim ersten Gebrauch als Storage angelegt.
Ein nicht leerer Ordner ohne Storage-Kennzeichen („fremd“, z. B. versehentlich
`--storage C:\Users\…\Dokumente`) wird abgelehnt und nicht verändert.
Ein Datenordner mit Storage-Schema 1 (`runtime/` statt `.storage/`) wird von
keinem Befehl angefasst; umstellen mit `chatexporter storage migrate`
([BEFEHLE.md](BEFEHLE.md)). Formaterkennung nur über eindeutige Marker. Das
Format ist als **Storage-Schema** versioniert (eigene Zählung, nicht die
Programmversion); Beschreibung je Storage-Schema: [storage_schema/](storage_schema/README.md).

## 2. Wie wird die config.yaml gefunden?

Globale Konfiguration:

1. `--config <datei>` (globale Option oder Option eines Befehls)
2. Umgebungsvariable `CHATEXPORTER_CONFIG`
3. nur beim Start aus dem Quellcode: die erste `config.yaml` beim Aufstieg ab
   dem Arbeitsordner; Ordner mit Code (`src/chatexporter`) werden übersprungen
4. `<home>/config.yaml`, also `~/.chatexporter/config.yaml`

Die Storage-Konfiguration liegt immer in `<storage>/.storage/config.yaml`.

**Fehlt eine Datei**, legt das Programm sie beim nächsten Laden neu an:
vollständig, mit **jeder** Einstellung als eigener auskommentierter Zeile
(Standardwerte echt, sonst klar als `BEISPIEL` markiert; Erklärungen in Zeilen
mit `##`). Die Storage-Vorlage enthält nur die Einstellungen, die im Storage
gelten dürfen. Die globale Vorlage liegt als `config.example.yaml` im Codeordner.

## 3. Vorrang

Spezifischere Angaben gewinnen:

```text
Standardwert < globale config.yaml < globale .env
            < Storage-config.yaml < Storage-.env
            < Umgebungsvariable < CLI-Wert (--set SCHLUESSEL=WERT)
```

- **Nur global** gelten: `bootstrap.*`, `storage.root`, `storage.data_root`,
  `providers.chatgpt.browser.*` und `task_scheduler.python`, `.manager_script`,
  `.global_state_file` (in Abschnitt 6 mit „nur global“ markiert). In der
  Storage-Datei werden sie mit Hinweis ignoriert.
- **Relative Pfade** gelten relativ zum Ordner der Datei, aus der sie stammen:
  Storage-Werte relativ zum Storage, globale relativ zur globalen config.yaml.
- **CLI-Werte:** globale Option vor dem Befehl, beliebig oft:
  `chatexporter --set providers.chatgpt.sync.listing_mode=full update`;
  `--storage PFAD` ist die Kurzform für `--set storage.root=PFAD`.
- **Umgebung und `.env`:** jede Einstellung über den generischen Namen
  `CHATEXPORTER__<ABSCHNITT>__<SCHLUESSEL>`, dazu die Kurznamen aus der Tabelle.
- **Secrets** gehören nur in eine `.env` oder die Umgebung, nie in eine
  config.yaml und nie als CLI-Wert.

## 4. Befehle

| Befehl | Wirkung |
| --- | --- |
| `chatexporter config get [SCHLUESSEL]` | wirksamer Wert und Herkunft (`default`, `config`, `.env`, `storage`, `storage .env`, `env`, `cli`) |
| `chatexporter config list` | alle wirksamen Werte mit Herkunft |
| `chatexporter config set SCHLUESSEL WERT` | schreibt in die **Storage**-config.yaml (geprüft; nur-globale Schlüssel und Secrets werden abgelehnt) |
| `chatexporter config reset SCHLUESSEL` / `--all` | Wert in der Storage-Datei auskommentieren / Storage-Datei auf die Vorlage zurücksetzen |
| `chatexporter config-global set|reset|get|list …` | dasselbe für die **globale** config.yaml |
| `chatexporter config refresh` | neu laden, fehlende Dateien anlegen, Registry-Spiegel neu schreiben |
| `chatexporter config path` | globale Dateien, Storage (Ort, Format, Dateien, `state.yaml`) und Registry-Schlüssel |

Vor jedem `set`/`reset` entsteht eine Sicherung unter `.config_backups/` neben
der geänderten Datei (die letzten 10 bleiben). Ist die geänderte Datei danach
nicht gültig ladbar, wird der alte Stand wiederhergestellt. Exitcodes: `0` ok,
`1` unbekannter Schlüssel oder ungültiger Wert, `2` Dateifehler.

## 5. Registry und Zustand

Je Storage gibt es einen eigenen Bereich:

```text
HKEY_CURRENT_USER\Software\ChatExporter\Storages\<storage-id>\
    Path, Name                Ort und Name des Storages
    Config\Current            Spiegel der wirksamen Konfiguration
    State                     Zustandswerte
```

- **Spiegel** (`Config\Current`): nach jedem erfolgreich angewendeten Laden oder
  Ändern geschrieben, nie vorher, nie gelesen; je Einstellung ein Wert, ohne
  Secrets. Ohne benutzbaren Storage (z. B. Storage-Schema 1) wird nach
  `…\ChatExporter\config\Current` gespiegelt.
- **Zustand** (`State`): die Zustandswerte leben hier (je Wert ein Eintrag, JSON):
  Identität, letzter Befehl mit Exitcode, Anzahl und Ergebnis der Updates,
  erster vollständiger Abruf (mit Schätzung der noch nötigen Teilläufe),
  nächster geplanter Lauf, je Quelle aktiv/letztes Update/Bestand.
- **`state.yaml`** im Verwaltungsbereich wird nach jedem Befehl auf dem Storage
  daraus neu erzeugt und nie gelesen: Identität, Zustand, die **wirksame
  Konfiguration mit Herkunft je Schlüssel** (Secrets nur als „(gesetzt)“) und
  alle Pfade – die Gesamtsicht von außen.
- `CHATEXPORTER_REGISTRY_MIRROR=off` schaltet Registry-Spiegel und -Zustand ab
  (Tests, Diagnose); der Zustand liegt dann nur im Speicher des Prozesses.

## 6. Alle Schlüssel

Erzeugt aus dem Schema (`src/chatexporter/config/schema.py`). „–“ als
Standard heißt: kein fester Standard, die Schicht leitet den Wert ab (steht in
der Beschreibung). Jede Einstellung ist zusätzlich über
`CHATEXPORTER__<PFAD>` erreichbar.

| Schlüssel | Standard | Umgebung (Kurzname) | Bedeutung |
| --- | --- | --- | --- |
| **(oberste Ebene)** | | | |
| `dev_mode` | `false` | `CHATEXPORTER_DEV_MODE` | Entwicklungsmodus: wenige Listing-Seiten, simuliertes Rate-Limit, schnelle Fortsetzung (Werte im Abschnitt dev; Gesamtablauf schnell und sparsam testen; nie im Alltag). |
| **`dev`** | | | |
| `dev.listing_max_pages` | `3` | `CHATEXPORTER_DEV_LISTING_MAX_PAGES` | Nur im Entwicklungsmodus: hoechstens so viele Listing-Seiten je Bereich (aktiv/archiviert); Eintraege je Seite: providers.chatgpt.sync.listing_limit. |
| `dev.conversation_fetches` | `5` | `CHATEXPORTER_DEV_CONVERSATION_FETCHES` | Nur im Entwicklungsmodus: simuliertes Rate-Limit (HTTP 429) nach so vielen Konversationsabrufen (0 = kein simuliertes Rate-Limit). |
| `dev.refill_minutes` | `5` | `CHATEXPORTER_DEV_REFILL_MINUTES` | Nur im Entwicklungsmodus: geschaetztes Wiederauffuellen des Limits (Minuten). |
| `dev.rate_limit_wait_minutes` | `1` | `CHATEXPORTER_DEV_RATE_LIMIT_WAIT_MINUTES` | Nur im Entwicklungsmodus: Obergrenze einer konfigurierten Wartezeit beim Rate-Limit (Minuten). |
| `dev.continuation_delay_minutes` | `5` | `CHATEXPORTER_DEV_CONTINUATION_DELAY_MINUTES` | Nur im Entwicklungsmodus: die Fortsetzung startet so viele Minuten nach einem Rate-Limit-Stopp. |
| **`bootstrap`** | | | |
| `bootstrap.venv_path` | `.venv` | `CHATEXPORTER_VENV_PATH` | **nur global.** Python-venv der Entwicklung (nur Anzeige in der Diagnose; installiert ohne Bedeutung). |
| `bootstrap.env_file` | `.env` | `CHATEXPORTER_ENV_FILE` | **nur global.** Datei mit Secrets/Overrides (KEY=WERT), relativ zu dieser Datei. |
| **`storage`** | | | |
| `storage.root` | `storages/default` | `CHATEXPORTER_STORAGE` | **nur global.** Storage (Datenbestand), mit dem gearbeitet wird; relativ zum Ordner der globalen config.yaml. Einmalig auch per --storage PFAD. Darunter: .storage/ (Verwaltung), raw_storage/, exports/. |
| `storage.data_root` | – | `CHATEXPORTER_DATA_ROOT` | **nur global.** Aelterer Name fuer storage.root (gilt, wenn storage.root nicht gesetzt ist). |
| `storage.raw_root` | – | `CHATEXPORTER_RAW_ROOT` | Abweichende Wurzel der Quelldaten (Standard: <storage>/raw_storage; nicht empfohlen). |
| `storage.runtime_root` | – | `CHATEXPORTER_RUNTIME_ROOT` | Abweichende Verwaltungsablage (Standard: <storage>/.storage; nicht empfohlen). |
| `storage.status_root` | – | `CHATEXPORTER_STATUS_ROOT` | Abweichende Statusablage (Standard: <storage>/.storage/status_registry; nicht empfohlen). |
| **`raw_session_updater`** | | | |
| `raw_session_updater.sources` | `[chatgpt, opencode, codex, claude]` | `CHATEXPORTER_SOURCES` | Aktive Quellen und ihre Reihenfolge (update, index, check, cleanup, status). |
| **`logging`** | | | |
| `logging.enabled` | `true` | `CHATEXPORTER_LOG_ENABLED` | Jeden Befehl als JSON-Zeile protokollieren. |
| `logging.dir` | – | `CHATEXPORTER_LOG_DIR` | Ordner des Befehlsprotokolls (Standard: <storage>/.storage/logs). |
| `logging.rotation` | `24h` | `CHATEXPORTER_LOG_ROTATION` | Zeitraum je Logdatei (z. B. 1h, 24h, 7d). |
| `logging.retention` | `30d` | `CHATEXPORTER_LOG_RETENTION` | Aeltere Logdateien werden entfernt (0 = nie). |
| **`exporter`** | | | |
| `exporter.root` | – | `CHATEXPORTER_EXPORT_ROOT` | Ziel der Exporte (Standard: <storage>/exports). |
| `exporter.formats` | `[markdown, json]` | `CHATEXPORTER_EXPORT_FORMATS` | Ausgabeformate (markdown, json). |
| `exporter.sources` | `[chatgpt, opencode, codex, claude]` | `CHATEXPORTER_EXPORT_SOURCES` | Quellen, die exportiert werden. |
| **`task_scheduler`** | | | |
| `task_scheduler.folder` | `\ChatExporter` | `CHATEXPORTER_TASK_FOLDER` | Ordner in der Windows-Aufgabenplanung. |
| `task_scheduler.owner` | `chatexporter` | `CHATEXPORTER_TASK_OWNER` | Eigentuemer-Kennung der Aufgaben. |
| `task_scheduler.state_file` | – | `CHATEXPORTER_TASK_STATE_FILE` | Lokaler State der Aufgaben (Standard: <storage>/.storage/tasks_sched.json). |
| `task_scheduler.global_state_file` | – | `CHATEXPORTER_TASK_GLOBAL_STATE` | **nur global.** Globaler State (Standard: %LOCALAPPDATA%/PyTaskManager/tasks_sched.json). |
| `task_scheduler.python` | – | `CHATEXPORTER_TASK_PYTHON` | **nur global.** Programm, das geplante Befehle ausfuehrt (Standard: venv-Python bzw. installiertes Programm). |
| `task_scheduler.manager_script` | – | `CHATEXPORTER_TASK_MANAGER_SCRIPT` | **nur global.** Ort von scheduler_manager.py (Standard: im Programm enthalten). |
| **`task_scheduler.defaults`** | | | |
| `task_scheduler.defaults.command` | `update --non-interactive` | `CHATEXPORTER_TASK_COMMAND` | Befehl neuer Aufgaben. |
| `task_scheduler.defaults.trigger` | `{type: daily, at: '03:00', every: 1}` | – | Zeitplan neuer Aufgaben (type: daily\|weekly\|once\|logon\|startup). |
| `task_scheduler.defaults.description` | `''` | – | Beschreibung neuer Aufgaben (leer = automatisch). |
| `task_scheduler.defaults.max_runtime_minutes` | `360` | – | Zeitlimit je Lauf in Minuten. |
| `task_scheduler.defaults.start_when_available` | `true` | – | Verpassten Lauf nachholen. |
| `task_scheduler.defaults.allow_on_battery` | `true` | – | Auch im Akkubetrieb starten. |
| `task_scheduler.defaults.wake_to_run` | `false` | – | Rechner dafuer wecken. |
| `task_scheduler.defaults.multiple_instances` | `ignore_new` | – | Wenn der vorige Lauf noch laeuft. Erlaubt: `parallel`, `queue`, `ignore_new`, `stop_existing`. |
| `task_scheduler.defaults.hidden` | `false` | – | Aufgabe in der Aufgabenplanung verbergen. |
| **`task_scheduler.continuation`** | | | |
| `task_scheduler.continuation.enabled` | `true` | – | Nach einem Lauf, der am Rate-Limit endete, automatisch eine Fortsetzung planen. |
| `task_scheduler.continuation.margin_minutes` | `10` | – | Sicherheitsabstand nach dem geschaetzten Wiederauffuellen des Limits (Minuten). |
| `task_scheduler.continuation.command` | `update --source chatgpt --listing-mode full --non-interactive` | – | Befehl der Fortsetzung (vollstaendiges Listing, damit auch noch nie geladene Chats erfasst werden). |
| **`providers.chatgpt`** | | | |
| `providers.chatgpt.browser.user_data_dir` | – | `CHATEXPORTER_EDGE_USER_DATA_DIR` | **nur global.** Browser-Profil MIT ChatGPT-Anmeldung. Leer = automatische Suche (Profilkopie eines Edge-/Chrome-Profils, eigenes Profil, Chrome for Testing); der gefundene Pfad wird danach hier eingetragen. |
| `providers.chatgpt.browser.kind` | `auto` | `CHATEXPORTER_BROWSER_KIND` | **nur global.** Browser zum Profil (auto = Edge bei festem Profil; wird von der Suche eingetragen). Erlaubt: `auto`, `edge`, `chrome`, `chrome_for_testing`. |
| `providers.chatgpt.browser.executable` | – | `CHATEXPORTER_BROWSER_EXE` | **nur global.** Browser-Programm (Standard: automatisch erkennen; wird von der Suche eingetragen). |
| `providers.chatgpt.browser.edge_executable` | – | `CHATEXPORTER_EDGE_EXE` | **nur global.** Aelterer Name fuer das Edge-Programm (gilt, wenn executable leer ist). |
| `providers.chatgpt.browser.allow_download` | `true` | `CHATEXPORTER_BROWSER_ALLOW_DOWNLOAD` | **nur global.** Chrome for Testing als letzte Stufe nach Rueckfrage herunterladen (nur bei interaktivem Start). |
| `providers.chatgpt.browser.chrome_for_testing_url` | `https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json` | – | **nur global.** Quelle der Chrome-for-Testing-Versionen. |
| `providers.chatgpt.browser.cdp_host` | `127.0.0.1` | `CHATEXPORTER_CDP_HOST` | **nur global.** CDP-Adresse. |
| `providers.chatgpt.browser.cdp_port` | `9223` | `CHATEXPORTER_CDP_PORT` | **nur global.** CDP-Port. |
| `providers.chatgpt.browser.launch_if_needed` | `true` | `CHATEXPORTER_EDGE_LAUNCH_IF_NEEDED` | **nur global.** Browser bei Bedarf starten. |
| `providers.chatgpt.browser.open_url` | `https://chatgpt.com/` | `CHATEXPORTER_EDGE_OPEN_URL` | **nur global.** Startseite. |
| `providers.chatgpt.browser.connect_timeout_ms` | `15000` | `CHATEXPORTER_EDGE_CONNECT_TIMEOUT_MS` | **nur global.** Wartezeit auf den Browser (ms). |
| `providers.chatgpt.browser.interactive_reauth` | `true` | `CHATEXPORTER_INTERACTIVE_REAUTH` | **nur global.** Bei Bedarf interaktiv anmelden. |
| `providers.chatgpt.browser.leave_browser_running` | `true` | `CHATEXPORTER_LEAVE_BROWSER_RUNNING` | **nur global.** Browser nach dem Lauf offen lassen. |
| `providers.chatgpt.browser.window` | `offscreen` | `CHATEXPORTER_BROWSER_WINDOW` | **nur global.** Fenster eines vom ChatExporter gestarteten Browsers; sichtbar wird es nur, wenn eine Eingabe noetig ist: offscreen = ausserhalb des Bildschirms (Standard); minimized = minimiert (Anmeldung langsamer); visible = immer sichtbar. Erlaubt: `offscreen`, `minimized`, `visible`. |
| `providers.chatgpt.auth.auto_login` | `auto` | `CHATEXPORTER_AUTO_LOGIN` | Automatische Anmeldung (E-Mail, Passwort, Einmalcode), wenn keine gueltige Sitzung besteht: auto = wenn Zugangsdaten in .env/Umgebung stehen; on = immer (fehlende Daten sind ein Fehler); off = nie. Erlaubt: `auto`, `on`, `off`. |
| `providers.chatgpt.auth.login_timeout_seconds` | `120` | `CHATEXPORTER_LOGIN_TIMEOUT_SECONDS` | Hoechstdauer einer automatischen Anmeldung. |
| `providers.chatgpt.auth.username` | – | `CHATGPT_USERNAME` | E-Mail-Adresse des ChatGPT-Kontos (nur .env/Umgebung). |
| `providers.chatgpt.auth.password` | – | `CHATGPT_PASSWORD` | Passwort des ChatGPT-Kontos (nur .env/Umgebung). |
| `providers.chatgpt.auth.totp_secret` | – | `CHATGPT_2FA_SECRET` | 2FA-Secret (Base32, otpauth://-URI oder verschluesselter Wert der Two-Factor Tools; nur .env/Umgebung). |
| `providers.chatgpt.auth.totp_reference` | – | `CHATGPT_2FA_REFERENCE` | Statt des Secrets: Kennung/Alias im verschluesselten Windows-Speicher der Two-Factor Tools. |
| `providers.chatgpt.api.base_url` | `https://chatgpt.com` | `CHATEXPORTER_API_BASE_URL` | Basis-URL der Backend-API. |
| `providers.chatgpt.api.request_timeout_ms` | `120000` | `CHATEXPORTER_API_REQUEST_TIMEOUT_MS` | Zeitlimit je Anfrage (ms). |
| `providers.chatgpt.sync.listing_mode` | `auto` | `CHATEXPORTER_LISTING_MODE` | auto = sparsam, bei Bedarf vollstaendig; full = gesamter Bestand; recent = nur zuletzt geaenderte. Erlaubt: `auto`, `full`, `recent`. |
| `providers.chatgpt.sync.listing_limit` | `100` | `CHATEXPORTER_LISTING_LIMIT` | Eintraege je Listing-Seite (hoechstens 100). |
| `providers.chatgpt.sync.recent_max_pages` | `3` | `CHATEXPORTER_RECENT_MAX_PAGES` | Deckel fuer recent (Seiten). |
| `providers.chatgpt.sync.recent_confirm_unchanged` | `3` | `CHATEXPORTER_RECENT_CONFIRM_UNCHANGED` | Unveraenderte Eintraege in Folge ab der Grenze. |
| `providers.chatgpt.sync.verify_boundary` | `true` | `CHATEXPORTER_VERIFY_BOUNDARY` | Grenz-Chats inhaltlich pruefen. |
| `providers.chatgpt.sync.verify_max_requests` | `0` | `CHATEXPORTER_VERIFY_MAX_REQUESTS` | Obergrenze Detailabrufe der Grenzpruefung (0 = unbegrenzt). |
| `providers.chatgpt.sync.fetch_files` | `true` | `CHATEXPORTER_FETCH_FILES` | Dateien/Anhaenge laden. |
| `providers.chatgpt.sync.fetch_textdocs` | `true` | `CHATEXPORTER_FETCH_TEXTDOCS` | Canvas-Dokumente laden. |
| `providers.chatgpt.sync.retry_pending_files` | `true` | `CHATEXPORTER_RETRY_PENDING_FILES` | Offene Dateien erneut versuchen. |
| `providers.chatgpt.sync.continue_on_error` | `true` | `CHATEXPORTER_CONTINUE_ON_ERROR` | Nach einzelnen Fehlern weitermachen. |
| `providers.chatgpt.sync.max_errors_per_run` | `5` | `CHATEXPORTER_MAX_ERRORS_PER_RUN` | Fehlerbudget je Lauf (API). |
| `providers.chatgpt.sync.max_file_errors_per_run` | `50` | `CHATEXPORTER_MAX_FILE_ERRORS_PER_RUN` | Fehlerbudget je Lauf (Dateien). |
| `providers.chatgpt.sync.rate_limit_wait_minutes` | `0` | `CHATEXPORTER_RATE_LIMIT_WAIT_MINUTES` | Beim Rate-Limit warten (Minuten; 0 = Lauf regulaer beenden). |
| `providers.chatgpt.sync.max_rate_limit_cycles` | `0` | `CHATEXPORTER_MAX_RATE_LIMIT_CYCLES` | Obergrenze Wartezyklen (0 = unbegrenzt). |
| `providers.chatgpt.sync.quarantine.enabled` | `false` | `CHATEXPORTER_QUARANTINE_ENABLED` | Dauerhaft fehlschlagende Datensaetze aussortieren. |
| `providers.chatgpt.sync.quarantine.min_failed_runs` | `3` | – | Getrennte Laeufe, nicht Versuche. |
| `providers.chatgpt.sync.quarantine.min_age_hours` | `24` | – | Abstand erster bis letzter Vorfall. |
| `providers.chatgpt.sync.quarantine.review_after_days` | `30` | – | Danach erneut pruefen. |
| `providers.chatgpt.sync.manual_exclusions.conversations` | `[]` | – | Bewusst ausgeschlossene Konversationen: Liste von {id, reason}. |
| `providers.chatgpt.sync.manual_exclusions.files` | `[]` | – | Bewusst ausgeschlossene Dateien: Liste von {id, reason}. |
| **`providers.opencode`** | | | |
| `providers.opencode.opencode_exe` | `opencode` | – | OpenCode-Programm. |
| `providers.opencode.db_path` | – | – | OpenCode-Datenbank (Standard: ueber die CLI ermitteln). |
| `providers.opencode.cli_cwd` | – | – | Ausweich-Arbeitsordner fuer die CLI. |
| `providers.opencode.timeout` | `180` | – | Zeitlimit je Export (Sekunden). |
| `providers.opencode.max_retries` | `2` | – | Wiederholungen je Session. |
| **`providers.codex`** | | | |
| `providers.codex.source_root` | – | – | Codex-Ordner (Standard: ~/.codex). |
| `providers.codex.max_retries` | `2` | – | Wiederholungen beim Kopieren. |
| `providers.codex.verify_unchanged` | `false` | – | Unveraenderte Dateien zusaetzlich per Hash pruefen. |
| **`providers.claude`** | | | |
| `providers.claude.source_root` | – | – | Claude-Code-Ordner (Standard: ~/.claude). |
| `providers.claude.max_retries` | `2` | – | Wiederholungen beim Kopieren. |
| `providers.claude.verify_unchanged` | `false` | – | Unveraenderte Dateien zusaetzlich per Hash pruefen. |

Zusätzlich nur als Prozess-Umgebung: `CHATEXPORTER_CONFIG` (Pfad der
config.yaml), `CHATEXPORTER_HOME` (Home-Verzeichnis),
`CHATEXPORTER_REGISTRY_MIRROR` (`off` schaltet den Spiegel ab).

Die einzelnen Provider lesen ihren Abschnitt `providers.<quelle>`; der Raw
Session Updater reicht ihn weiter (nicht gesetzte Werte entfallen, der
Provider nimmt dann seinen eigenen Standard). Die Ablagepfade setzt immer der
Raw Session Updater. Details: [providers/CHATGPT.md](providers/CHATGPT.md),
[providers/LOKALE_QUELLEN.md](providers/LOKALE_QUELLEN.md),
[TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md).

## 7. Prüfen, was gilt

- `chatexporter config list` bzw. `config get SCHLUESSEL`: wirksamer Wert und Herkunft.
- `chatexporter config path`: welche Dateien verwendet werden.
- Menükopf (`chatexporter`) und Beginn jedes Updates: laufender
  Programmstand (Version, Codeordner, Python), verwendete config.yaml,
  Datenordner und aktive Quellen. Liegt der Code in `site-packages`, erscheint
  eine Warnung: Dann läuft eine feste Kopie, und Änderungen am Codeordner
  wirken erst nach einer Neuinstallation.
- `chatexporter-chatgpt doctor`: alle aufgelösten ChatGPT-Pfade und -Werte.

## 7a. Secrets

Einstellungen mit dem Hinweis „nur .env/Umgebung“ (z. B.
`providers.chatgpt.auth.username`, `.password`, `.totp_secret`,
`.totp_reference`) sind Secrets: Sie werden nur aus einer `.env` (globale
`.env` oder Storage-`.env`) oder der Umgebung übernommen; Werte aus einer
config.yaml (global oder Storage) oder `--set` werden verworfen, mit Hinweis. Sie
werden nie in den Registry-Spiegel geschrieben, in der Vorlage nur angedeutet und
von `config list`/`config get` als „gesetzt – wird nicht angezeigt“ ausgegeben;
`config set` lehnt sie ab.

## 8. Entwicklungsmodus (`dev_mode`)

Schalter für Entwicklung und Tests: Der komplette Ablauf (Listing, Abruf,
Rate-Limit-Stopp, automatische Fortsetzung) läuft schnell und mit wenigen
echten Anfragen durch. Die Logik bleibt unverändert; es werden nur
einzelne Grenzwerte gesetzt (`src/chatexporter/config/dev.py`):

| Wirkung | Wert im Entwicklungsmodus (Einstellung, Standard) | sonst |
| --- | --- | --- |
| Listing-Seiten je Bereich (aktiv/archiviert) | `dev.listing_max_pages`, Standard 3 | alle (Voll-Listing) bzw. `recent_max_pages` |
| Einträge je Listing-Seite | `providers.chatgpt.sync.listing_limit` (normale Einstellung, 1–100) | dieselbe |
| Konversationsabrufe bis zum Rate-Limit | `dev.conversation_fetches`, Standard 5, danach **simuliertes** HTTP 429 (kostet keine Anfrage); `0` = kein simuliertes Limit | echtes Server-Limit |
| geschätzte Auffüllzeit des Kontingents | `dev.refill_minutes`, Standard 5 Minuten | gemessener Richtwert |
| Wartezeit bei Rate-Limit im Lauf | höchstens `dev.rate_limit_wait_minutes`, Standard 1 Minute | `sync.rate_limit_wait_minutes` |
| Start der Fortsetzungsaufgabe | `dev.continuation_delay_minutes`, Standard 5 Minuten nach dem Stopp | geschätzte Auffüllzeit + `margin_minutes` |
| gekürztes Voll-Listing | gilt als Teil-Listing: auf dem **Server** gelöschte Konversationen werden nicht erkannt; lokal (im Storage) gelöschte schon (siehe providers/CHATGPT.md, Listing-Modi) | – |

Beispiel: 5 Seiten zu je 10 Einträgen, ohne simuliertes Rate-Limit:
`chatexporter --set dev_mode=true --set dev.listing_max_pages=5 --set dev.conversation_fetches=0
--set providers.chatgpt.sync.listing_limit=10 update --source chatgpt`. Ein
vollständiger Testablauf steht in [TESTABLAUF_ENTWICKLUNGSMODUS.md](TESTABLAUF_ENTWICKLUNGSMODUS.md).

Einschalten: `chatexporter config set dev_mode true`, einmalig
`--set dev_mode=true` oder `CHATEXPORTER_DEV_MODE=1`. Jeder ChatGPT-Lauf
meldet den Modus zu Beginn mit einer Zeile `DEV-MODUS AKTIV: …`, der Laufbericht
enthält `dev_mode: true`. Nicht für den Alltag gedacht: Ein Lauf im
Entwicklungsmodus lädt absichtlich nur einen Teil der Daten.
