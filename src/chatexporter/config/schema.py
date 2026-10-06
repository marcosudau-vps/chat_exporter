"""Alle Einstellungen des ChatExporters (Schema fuer ``layered_config``).

Reihenfolge = Reihenfolge in der erzeugten config.yaml. Pfade sind relativ zum
Ordner der Datei, aus der sie stammen (globale config.yaml bzw. Storage-Ordner).
``global_only`` (siehe ``GLOBAL_ONLY``) gilt nur in der globalen config.yaml. Standardwerte hier sind die wirksamen Standards; wo
eine Schicht einen Wert noch weiter ableitet (z. B. ``storage.raw_root`` aus
``storage.data_root``), steht der Standard auf ``None`` mit Beispielwert.
"""

from __future__ import annotations

from dataclasses import replace

from layered_config import Schema, Setting

S = Setting

SETTINGS: list[Setting] = [
    S("dev_mode", False, "bool",
      "Entwicklungsmodus: wenige Listing-Seiten, simuliertes Rate-Limit, schnelle Fortsetzung\n"
      "(Werte im Abschnitt dev; Gesamtablauf schnell und sparsam testen; nie im Alltag).",
      env=("CHATEXPORTER_DEV_MODE",)),
    S("dev.listing_max_pages", 3, "int",
      "Nur im Entwicklungsmodus: hoechstens so viele Listing-Seiten je Bereich (aktiv/archiviert);\n"
      "Eintraege je Seite: providers.chatgpt.sync.listing_limit.",
      env=("CHATEXPORTER_DEV_LISTING_MAX_PAGES",)),
    S("dev.conversation_fetches", 5, "int",
      "Nur im Entwicklungsmodus: simuliertes Rate-Limit (HTTP 429) nach so vielen Konversationsabrufen\n"
      "(0 = kein simuliertes Rate-Limit).", env=("CHATEXPORTER_DEV_CONVERSATION_FETCHES",)),
    S("dev.refill_minutes", 5, "int", "Nur im Entwicklungsmodus: geschaetztes Wiederauffuellen des Limits (Minuten).",
      env=("CHATEXPORTER_DEV_REFILL_MINUTES",)),
    S("dev.rate_limit_wait_minutes", 1, "int",
      "Nur im Entwicklungsmodus: Obergrenze einer konfigurierten Wartezeit beim Rate-Limit (Minuten).",
      env=("CHATEXPORTER_DEV_RATE_LIMIT_WAIT_MINUTES",)),
    S("dev.continuation_delay_minutes", 5, "int",
      "Nur im Entwicklungsmodus: die Fortsetzung startet so viele Minuten nach einem Rate-Limit-Stopp.",
      env=("CHATEXPORTER_DEV_CONTINUATION_DELAY_MINUTES",)),

    # -- Umgebung ----------------------------------------------------------------
    S("bootstrap.venv_path", ".venv", "path",
      "Python-venv der Entwicklung (nur Anzeige in der Diagnose; installiert ohne Bedeutung).",
      env=("CHATEXPORTER_VENV_PATH",)),
    S("bootstrap.env_file", ".env", "path",
      "Datei mit Secrets/Overrides (KEY=WERT), relativ zu dieser Datei.",
      env=("CHATEXPORTER_ENV_FILE",)),

    # -- Ablage ------------------------------------------------------------------
    S("storage.root", "storages/default", "path",
      "Storage (Datenbestand), mit dem gearbeitet wird; relativ zum Ordner der globalen config.yaml.\n"
      "Einmalig auch per --storage PFAD. Darunter: .storage/ (Verwaltung), raw_storage/, exports/.",
      env=("CHATEXPORTER_STORAGE",)),
    S("storage.data_root", None, "path",
      "Aelterer Name fuer storage.root (gilt, wenn storage.root nicht gesetzt ist).",
      example="D:/BEISPIEL/chat_daten", env=("CHATEXPORTER_DATA_ROOT",)),
    S("storage.raw_root", None, "path",
      "Abweichende Wurzel der Quelldaten (Standard: <storage>/raw_storage; nicht empfohlen).",
      example="D:/BEISPIEL/chat_daten/raw_storage", env=("CHATEXPORTER_RAW_ROOT",)),
    S("storage.runtime_root", None, "path",
      "Abweichende Verwaltungsablage (Standard: <storage>/.storage; nicht empfohlen).",
      example="D:/BEISPIEL/chat_daten/.storage", env=("CHATEXPORTER_RUNTIME_ROOT",)),
    S("storage.status_root", None, "path",
      "Abweichende Statusablage (Standard: <storage>/.storage/status_registry; nicht empfohlen).",
      example="D:/BEISPIEL/chat_daten/.storage/status_registry", env=("CHATEXPORTER_STATUS_ROOT",)),

    # -- Raw Session Updater -------------------------------------------------------
    S("raw_session_updater.sources", ["chatgpt", "opencode", "codex", "claude"], "list",
      "Aktive Quellen und ihre Reihenfolge (update, index, check, cleanup, status).",
      env=("CHATEXPORTER_SOURCES",)),

    # -- Befehlsprotokoll ------------------------------------------------------------
    S("logging.enabled", True, "bool", "Jeden Befehl als JSON-Zeile protokollieren.",
      env=("CHATEXPORTER_LOG_ENABLED",)),
    S("logging.dir", None, "path", "Ordner des Befehlsprotokolls (Standard: <storage>/.storage/logs).",
      example="D:/BEISPIEL/chat_logs", env=("CHATEXPORTER_LOG_DIR",)),
    S("logging.rotation", "24h", "duration", "Zeitraum je Logdatei (z. B. 1h, 24h, 7d).",
      env=("CHATEXPORTER_LOG_ROTATION",)),
    S("logging.retention", "30d", "duration", "Aeltere Logdateien werden entfernt (0 = nie).",
      env=("CHATEXPORTER_LOG_RETENTION",)),

    # -- Exporter ----------------------------------------------------------------------
    S("exporter.root", None, "path", "Ziel der Exporte (Standard: <storage>/exports).",
      example="D:/BEISPIEL/chat_exporte", env=("CHATEXPORTER_EXPORT_ROOT",)),
    S("exporter.formats", ["markdown", "json"], "list", "Ausgabeformate (markdown, json).",
      env=("CHATEXPORTER_EXPORT_FORMATS",)),
    S("exporter.sources", ["chatgpt", "opencode", "codex", "claude"], "list",
      "Quellen, die exportiert werden.", env=("CHATEXPORTER_EXPORT_SOURCES",)),

    # -- Zeitplanung ---------------------------------------------------------------------
    S("task_scheduler.folder", "\\ChatExporter", "str", "Ordner in der Windows-Aufgabenplanung.",
      env=("CHATEXPORTER_TASK_FOLDER",)),
    S("task_scheduler.owner", "chatexporter", "str", "Eigentuemer-Kennung der Aufgaben.",
      env=("CHATEXPORTER_TASK_OWNER",)),
    S("task_scheduler.state_file", None, "path",
      "Lokaler State der Aufgaben (Standard: <storage>/.storage/tasks_sched.json).",
      example="D:/BEISPIEL/chat_daten/.storage/tasks_sched.json", env=("CHATEXPORTER_TASK_STATE_FILE",)),
    S("task_scheduler.global_state_file", None, "path",
      "Globaler State (Standard: %LOCALAPPDATA%/PyTaskManager/tasks_sched.json).",
      example="C:/BEISPIEL/AppData/Local/PyTaskManager/tasks_sched.json",
      env=("CHATEXPORTER_TASK_GLOBAL_STATE",)),
    S("task_scheduler.python", None, "path",
      "Programm, das geplante Befehle ausfuehrt (Standard: venv-Python bzw. installiertes Programm).",
      example="C:/BEISPIEL/venv/Scripts/python.exe", env=("CHATEXPORTER_TASK_PYTHON",)),
    S("task_scheduler.manager_script", None, "path",
      "Ort von scheduler_manager.py (Standard: im Programm enthalten).",
      example="C:/BEISPIEL/tools/task_scheduler/scheduler_manager.py",
      env=("CHATEXPORTER_TASK_MANAGER_SCRIPT",)),
    S("task_scheduler.defaults.command", "update --non-interactive", "str",
      "Befehl neuer Aufgaben.", env=("CHATEXPORTER_TASK_COMMAND",)),
    S("task_scheduler.defaults.trigger", {"type": "daily", "at": "03:00", "every": 1}, "dict",
      "Zeitplan neuer Aufgaben (type: daily|weekly|once|logon|startup)."),
    S("task_scheduler.defaults.description", "", "str", "Beschreibung neuer Aufgaben (leer = automatisch)."),
    S("task_scheduler.defaults.max_runtime_minutes", 360, "float", "Zeitlimit je Lauf in Minuten."),
    S("task_scheduler.defaults.start_when_available", True, "bool", "Verpassten Lauf nachholen."),
    S("task_scheduler.defaults.allow_on_battery", True, "bool", "Auch im Akkubetrieb starten."),
    S("task_scheduler.defaults.wake_to_run", False, "bool", "Rechner dafuer wecken."),
    S("task_scheduler.defaults.multiple_instances", "ignore_new", "str",
      "Wenn der vorige Lauf noch laeuft.", choices=("parallel", "queue", "ignore_new", "stop_existing")),
    S("task_scheduler.defaults.hidden", False, "bool", "Aufgabe in der Aufgabenplanung verbergen."),
    S("task_scheduler.continuation.enabled", True, "bool",
      "Nach einem Lauf, der am Rate-Limit endete, automatisch eine Fortsetzung planen."),
    S("task_scheduler.continuation.margin_minutes", 10, "int",
      "Sicherheitsabstand nach dem geschaetzten Wiederauffuellen des Limits (Minuten)."),
    S("task_scheduler.continuation.command", "update --source chatgpt --listing-mode full --non-interactive", "str",
      "Befehl der Fortsetzung (vollstaendiges Listing, damit auch noch nie geladene Chats erfasst werden)."),

    # -- Provider: ChatGPT ------------------------------------------------------------------
    S("providers.chatgpt.browser.user_data_dir", None, "path",
      "Browser-Profil MIT ChatGPT-Anmeldung. Leer = automatische Suche (Profilkopie eines\n"
      "Edge-/Chrome-Profils, eigenes Profil, Chrome for Testing); der gefundene Pfad wird danach\n"
      "hier eingetragen.",
      example="D:/BEISPIEL/browser_profil", env=("CHATEXPORTER_EDGE_USER_DATA_DIR",)),
    S("providers.chatgpt.browser.kind", "auto", "str",
      "Browser zum Profil (auto = Edge bei festem Profil; wird von der Suche eingetragen).",
      choices=("auto", "edge", "chrome", "chrome_for_testing"), env=("CHATEXPORTER_BROWSER_KIND",)),
    S("providers.chatgpt.browser.executable", None, "path",
      "Browser-Programm (Standard: automatisch erkennen; wird von der Suche eingetragen).",
      example="C:/BEISPIEL/Programme/Google/Chrome/Application/chrome.exe", env=("CHATEXPORTER_BROWSER_EXE",)),
    S("providers.chatgpt.browser.edge_executable", None, "path",
      "Aelterer Name fuer das Edge-Programm (gilt, wenn executable leer ist).",
      example="C:/BEISPIEL/Programme/Microsoft/Edge/Application/msedge.exe", env=("CHATEXPORTER_EDGE_EXE",)),
    S("providers.chatgpt.browser.allow_download", True, "bool",
      "Chrome for Testing als letzte Stufe nach Rueckfrage herunterladen (nur bei interaktivem Start).",
      env=("CHATEXPORTER_BROWSER_ALLOW_DOWNLOAD",)),
    S("providers.chatgpt.browser.chrome_for_testing_url",
      "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json", "str",
      "Quelle der Chrome-for-Testing-Versionen."),
    S("providers.chatgpt.browser.cdp_host", "127.0.0.1", "str", "CDP-Adresse.", env=("CHATEXPORTER_CDP_HOST",)),
    S("providers.chatgpt.browser.cdp_port", 9223, "int", "CDP-Port.", env=("CHATEXPORTER_CDP_PORT",)),
    S("providers.chatgpt.browser.launch_if_needed", True, "bool", "Browser bei Bedarf starten.",
      env=("CHATEXPORTER_EDGE_LAUNCH_IF_NEEDED",)),
    S("providers.chatgpt.browser.open_url", "https://chatgpt.com/", "str", "Startseite.",
      env=("CHATEXPORTER_EDGE_OPEN_URL",)),
    S("providers.chatgpt.browser.connect_timeout_ms", 15000, "int", "Wartezeit auf den Browser (ms).",
      env=("CHATEXPORTER_EDGE_CONNECT_TIMEOUT_MS",)),
    S("providers.chatgpt.browser.interactive_reauth", True, "bool", "Bei Bedarf interaktiv anmelden.",
      env=("CHATEXPORTER_INTERACTIVE_REAUTH",)),
    S("providers.chatgpt.browser.leave_browser_running", True, "bool", "Browser nach dem Lauf offen lassen.",
      env=("CHATEXPORTER_LEAVE_BROWSER_RUNNING",)),
    S("providers.chatgpt.browser.window", "offscreen", "str",
      "Fenster eines vom ChatExporter gestarteten Browsers; sichtbar wird es nur, wenn eine Eingabe noetig ist:\n"
      "offscreen = ausserhalb des Bildschirms (Standard); minimized = minimiert (Anmeldung langsamer);\n"
      "visible = immer sichtbar.",
      choices=("offscreen", "minimized", "visible"), env=("CHATEXPORTER_BROWSER_WINDOW",)),
    S("providers.chatgpt.auth.auto_login", "auto", "str",
      "Automatische Anmeldung (E-Mail, Passwort, Einmalcode), wenn keine gueltige Sitzung besteht:\n"
      "auto = wenn Zugangsdaten in .env/Umgebung stehen; on = immer (fehlende Daten sind ein Fehler); off = nie.",
      choices=("auto", "on", "off"), env=("CHATEXPORTER_AUTO_LOGIN",)),
    S("providers.chatgpt.auth.login_timeout_seconds", 120, "int", "Hoechstdauer einer automatischen Anmeldung.",
      env=("CHATEXPORTER_LOGIN_TIMEOUT_SECONDS",)),
    S("providers.chatgpt.auth.username", None, "str", "E-Mail-Adresse des ChatGPT-Kontos (nur .env/Umgebung).",
      secret=True, example="beispiel@example.org", env=("CHATGPT_USERNAME",)),
    S("providers.chatgpt.auth.password", None, "str", "Passwort des ChatGPT-Kontos (nur .env/Umgebung).",
      secret=True, example="BEISPIEL-PASSWORT", env=("CHATGPT_PASSWORD",)),
    S("providers.chatgpt.auth.totp_secret", None, "str",
      "2FA-Secret (Base32, otpauth://-URI oder verschluesselter Wert der Two-Factor Tools; nur .env/Umgebung).",
      secret=True, example="JBSWY3DPEHPK3PXP", env=("CHATGPT_2FA_SECRET",)),
    S("providers.chatgpt.auth.totp_reference", None, "str",
      "Statt des Secrets: Kennung/Alias im verschluesselten Windows-Speicher der Two-Factor Tools.",
      secret=True, example="chatgpt-konto", env=("CHATGPT_2FA_REFERENCE",)),
    S("providers.chatgpt.api.base_url", "https://chatgpt.com", "str", "Basis-URL der Backend-API.",
      env=("CHATEXPORTER_API_BASE_URL",)),
    S("providers.chatgpt.api.request_timeout_ms", 120000, "int", "Zeitlimit je Anfrage (ms).",
      env=("CHATEXPORTER_API_REQUEST_TIMEOUT_MS",)),
    S("providers.chatgpt.sync.listing_mode", "auto", "str",
      "auto = sparsam, bei Bedarf vollstaendig; full = gesamter Bestand; recent = nur zuletzt geaenderte.",
      choices=("auto", "full", "recent"), env=("CHATEXPORTER_LISTING_MODE",)),
    S("providers.chatgpt.sync.listing_limit", 100, "int", "Eintraege je Listing-Seite (hoechstens 100).",
      env=("CHATEXPORTER_LISTING_LIMIT",)),
    S("providers.chatgpt.sync.recent_max_pages", 3, "int", "Deckel fuer recent (Seiten).",
      env=("CHATEXPORTER_RECENT_MAX_PAGES",)),
    S("providers.chatgpt.sync.recent_confirm_unchanged", 3, "int",
      "Unveraenderte Eintraege in Folge ab der Grenze.", env=("CHATEXPORTER_RECENT_CONFIRM_UNCHANGED",)),
    S("providers.chatgpt.sync.verify_boundary", True, "bool", "Grenz-Chats inhaltlich pruefen.",
      env=("CHATEXPORTER_VERIFY_BOUNDARY",)),
    S("providers.chatgpt.sync.verify_max_requests", 0, "int", "Obergrenze Detailabrufe der Grenzpruefung (0 = unbegrenzt).",
      env=("CHATEXPORTER_VERIFY_MAX_REQUESTS",)),
    S("providers.chatgpt.sync.fetch_files", True, "bool", "Dateien/Anhaenge laden.",
      env=("CHATEXPORTER_FETCH_FILES",)),
    S("providers.chatgpt.sync.fetch_textdocs", True, "bool", "Canvas-Dokumente laden.",
      env=("CHATEXPORTER_FETCH_TEXTDOCS",)),
    S("providers.chatgpt.sync.retry_pending_files", True, "bool", "Offene Dateien erneut versuchen.",
      env=("CHATEXPORTER_RETRY_PENDING_FILES",)),
    S("providers.chatgpt.sync.continue_on_error", True, "bool", "Nach einzelnen Fehlern weitermachen.",
      env=("CHATEXPORTER_CONTINUE_ON_ERROR",)),
    S("providers.chatgpt.sync.max_errors_per_run", 5, "int", "Fehlerbudget je Lauf (API).",
      env=("CHATEXPORTER_MAX_ERRORS_PER_RUN",)),
    S("providers.chatgpt.sync.max_file_errors_per_run", 50, "int", "Fehlerbudget je Lauf (Dateien).",
      env=("CHATEXPORTER_MAX_FILE_ERRORS_PER_RUN",)),
    S("providers.chatgpt.sync.rate_limit_wait_minutes", 0, "int",
      "Beim Rate-Limit warten (Minuten; 0 = Lauf regulaer beenden).",
      env=("CHATEXPORTER_RATE_LIMIT_WAIT_MINUTES",)),
    S("providers.chatgpt.sync.max_rate_limit_cycles", 0, "int", "Obergrenze Wartezyklen (0 = unbegrenzt).",
      env=("CHATEXPORTER_MAX_RATE_LIMIT_CYCLES",)),
    S("providers.chatgpt.sync.quarantine.enabled", False, "bool",
      "Dauerhaft fehlschlagende Datensaetze aussortieren.", env=("CHATEXPORTER_QUARANTINE_ENABLED",)),
    S("providers.chatgpt.sync.quarantine.min_failed_runs", 3, "int", "Getrennte Laeufe, nicht Versuche."),
    S("providers.chatgpt.sync.quarantine.min_age_hours", 24, "int", "Abstand erster bis letzter Vorfall."),
    S("providers.chatgpt.sync.quarantine.review_after_days", 30, "int", "Danach erneut pruefen."),
    S("providers.chatgpt.sync.manual_exclusions.conversations", [], "list",
      "Bewusst ausgeschlossene Konversationen: Liste von {id, reason}."),
    S("providers.chatgpt.sync.manual_exclusions.files", [], "list",
      "Bewusst ausgeschlossene Dateien: Liste von {id, reason}."),

    # -- Provider: lokale Quellen ---------------------------------------------------------------
    S("providers.opencode.opencode_exe", "opencode", "str", "OpenCode-Programm."),
    S("providers.opencode.db_path", None, "path", "OpenCode-Datenbank (Standard: ueber die CLI ermitteln).",
      example="C:/BEISPIEL/.local/share/opencode/opencode.db"),
    S("providers.opencode.cli_cwd", None, "path", "Ausweich-Arbeitsordner fuer die CLI.",
      example="C:/BEISPIEL/projekt"),
    S("providers.opencode.timeout", 180, "int", "Zeitlimit je Export (Sekunden)."),
    S("providers.opencode.max_retries", 2, "int", "Wiederholungen je Session."),
    S("providers.codex.source_root", None, "path", "Codex-Ordner (Standard: ~/.codex).",
      example="C:/Users/BEISPIEL/.codex"),
    S("providers.codex.max_retries", 2, "int", "Wiederholungen beim Kopieren."),
    S("providers.codex.verify_unchanged", False, "bool", "Unveraenderte Dateien zusaetzlich per Hash pruefen."),
    S("providers.claude.source_root", None, "path", "Claude-Code-Ordner (Standard: ~/.claude).",
      example="C:/Users/BEISPIEL/.claude"),
    S("providers.claude.max_retries", 2, "int", "Wiederholungen beim Kopieren."),
    S("providers.claude.verify_unchanged", False, "bool", "Unveraenderte Dateien zusaetzlich per Hash pruefen."),
]

SECTIONS = {
    "dev": "Entwicklungsmodus (wirkt nur mit dev_mode: true)",
    "bootstrap": "Umgebung",
    "storage": "Storage (Datenbestand) und Ablage",
    "raw_session_updater": "Raw Session Updater: Daten holen und im Raw Storage ablegen",
    "logging": "Befehlsprotokoll",
    "exporter": "Exporter: Markdown/JSON aus dem Raw Storage",
    "task_scheduler": "Zeitplanung (Windows-Aufgabenplanung)",
    "task_scheduler.defaults": "Standardwerte neuer Aufgaben",
    "task_scheduler.continuation": "Automatische Fortsetzung nach einem Rate-Limit-Stopp",
    "providers": "Einstellungen je Quelle",
    "providers.chatgpt.sync.manual_exclusions": "Nach manueller Pruefung bewusst ausgeschlossen",
}

#: Einstellungen, die nur in der globalen config.yaml gelten (nicht im Storage):
#: Programm, Ort des Storages, Browser (global, siehe docs/STORAGE_KONZEPT.md F4).
GLOBAL_ONLY = ("bootstrap.", "storage.root", "storage.data_root", "providers.chatgpt.browser.",
               "task_scheduler.python", "task_scheduler.manager_script", "task_scheduler.global_state_file")


def _global_only(path: str) -> bool:
    return any(path == item or (item.endswith(".") and path.startswith(item)) for item in GLOBAL_ONLY)


SETTINGS = [replace(s, global_only=True) if _global_only(s.path) else s for s in SETTINGS]

SCHEMA = Schema(SETTINGS, sections=SECTIONS)
