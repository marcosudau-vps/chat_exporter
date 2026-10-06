# Getting Started – Normalbetrieb

Kurzanleitung für den Alltag. Hintergrund und alle Optionen:
[BEFEHLE.md](BEFEHLE.md), [KONFIGURATION.md](KONFIGURATION.md),
[ARCHITEKTUR.md](ARCHITEKTUR.md). Was (noch) nicht geht:
[BEKANNTE_EINSCHRAENKUNGEN.md](BEKANNTE_EINSCHRAENKUNGEN.md).

## A. Installiertes Programm (Windows)

### Installieren

1. `ChatExporter-Setup-<Version>.exe` ausführen. Es braucht keine
   Administratorrechte: Installiert wird für den angemeldeten Benutzer nach
   `%LOCALAPPDATA%\Programs\ChatExporter`. Optional wird der Programmordner in
   den PATH eingetragen.
2. Am Ende bietet das Installationsprogramm an, die Einrichtung zu starten
   (`chatexporter setup`, auch später über das Startmenü):
   - **Konfiguration:** `~/.chatexporter\config.yaml` wird bei Bedarf als
     vollständige, auskommentierte Vorlage angelegt.
   - **Browser und ChatGPT-Anmeldung:** Das Programm sucht einen Edge- oder
     Chrome-Profilordner mit ChatGPT-Anmeldung und legt nach Rückfrage eine
     Kopie an. Ein geöffneter Browser wird dafür geschlossen und danach wieder
     geöffnet. Ohne Anmeldung bietet es ein eigenes, leeres Profil oder Chrome for
     Testing an ([providers/CHATGPT.md](providers/CHATGPT.md), Abschnitt 2).
   - **Täglicher Abruf:** eine Windows-Aufgabe, Standard 03:00.

   Jeder Schritt fragt nach; die Einrichtung lässt sich wiederholen.
3. **Automatische Anmeldung**, empfohlen: ChatGPT verlangt nach etwa 10–14
   Tagen eine neue Anmeldung. Damit die geplanten Läufe dann weiterlaufen, die
   Zugangsdaten in `~/.chatexporter\.env` eintragen (nie in die config.yaml):

   ```text
   CHATGPT_USERNAME=name@example.org
   CHATGPT_PASSWORD=...
   CHATGPT_2FA_SECRET=<Base32 oder otpauth://…>     # oder CHATGPT_2FA_REFERENCE=<Alias>
   ```

   Prüfen mit `chatexporter chatgpt login`. Zum Mitschauen mit `--schrittweise`:
   Das Programm hält dann vor jedem Schritt an. Einzelheiten:
   [providers/CHATGPT.md](providers/CHATGPT.md), Abschnitt 2a.

### Wo liegt was?

```text
~/.chatexporter\
├── config.yaml, .env               globale Konfiguration und Zugangsdaten
├── browser\                        Browser-Profile des ChatExporters (Profilkopien)
└── storages\default\               Ihre Daten („Storage“)
    ├── raw_storage\<quelle>\       Quelldaten (nicht von Hand ändern)
    ├── exports\                    Exporte (Markdown/JSON, jederzeit neu erzeugbar)
    └── .storage\                   Verwaltung: Laufberichte runs\, Protokoll logs\,
                                    Übersicht OVERVIEW.md, Gesamtsicht state.yaml
```

Ein anderer Storage lässt sich mit `--storage <Ordner>` wählen. Der Ordner muss
leer oder neu sein, oder er ist schon ein Storage
([KONFIGURATION.md](KONFIGURATION.md)).

### Aktualisieren, deinstallieren

- **Neue Version:** einfach das neue Installationsprogramm ausführen.
  Konfiguration, Zugangsdaten und Daten bleiben erhalten.
- **Deinstallieren:** über „Apps“ in den Windows-Einstellungen oder mit
  `chatexporter uninstall`. Entfernt werden Programm, Startmenü, PATH-Eintrag,
  die Windows-Aufgaben aller bekannten Storages und der Registry-Schlüssel.
  `~/.chatexporter` mit Daten und Konfiguration **bleibt**.
- **Von einem älteren Testprogramm** (vor 0.0.1, Home-Ordner `~/.chat_exporter`):
  Diese Daten übernimmt das Programm nicht von selbst. So geht es von Hand:
  1. Alte Aufgaben entfernen. Sie tragen den Eigentümer `chatexporter` und
     erscheinen nur so: `chatexporter task list --owner chatexporter`, dann
     `chatexporter task delete <Name> --yes --owner chatexporter`. Auch die
     Deinstallation entfernt sie nicht von selbst.
  2. Den alten Datenordner `~/.chat_exporter\data` an einen neuen Ort
     verschieben, z. B. `~/.chatexporter\storages\alt`.
  3. Ihn umstellen: `chatexporter storage migrate <Ordner>`, erst mit
     `--dry-run`.
  4. Ihn verwenden: `chatexporter config-global set storage.root <Ordner>`.
  5. Die Einrichtung `chatexporter setup` erneut ausführen, damit die tägliche
     Aufgabe für diesen Storage angelegt wird.

## B. Start aus dem Quellcode

Die eigenständige Installation steht in [README](../README.md). Für Tests
`CHATEXPORTER_HOME` auf einen eigenen leeren Ordner setzen und
`CHATEXPORTER_REGISTRY_MIRROR=off` verwenden. Echte Zugangsdaten bleiben lokal.

## Alltag

```powershell
chatexporter                  # Menü: alle Alltagsfunktionen als Auswahl
chatexporter update           # alle aktiven Quellen aktualisieren
chatexporter export           # Exporte (Markdown/JSON) aller Quellen aus dem Raw Storage
chatexporter config list      # wirksame Einstellungen und ihre Herkunft
chatexporter check            # prüfen (read-only)
chatexporter status           # Momentaufnahme + .storage\OVERVIEW.md
chatexporter storage show     # welcher Storage, Format, Zustand
```

`chatexporter update` lädt neue und geänderte Daten **aller aktiven Quellen**
(`raw_session_updater.sources`) nacheinander. Er schreibt **einen** Laufbericht
nach `<storage>\.storage\runs\sync_<UTC>.json`.

Das ChatGPT-Listing wählt standardmäßig selbst (`auto`):
- ohne Bestand vollständig,
- sonst die zuletzt geänderten Chats,
- vollständig nur bei Bedarf, z. B. wenn lokal Dateien gelöscht wurden
  ([providers/CHATGPT.md](providers/CHATGPT.md), Abschnitt 4).

Ein Update erzeugt **keine** Exporte; sie entstehen mit `chatexporter export`.

| Exitcode | Bedeutung |
| --- | --- |
| `0` | ok |
| `1` | abgeschlossen mit fachlichen Fehlern (Details im Laufbericht) |
| `2` | abgebrochen oder teilweise ausgefallen (Quelle fehlgeschlagen, Konfigurationsfehler, Storage nicht benutzbar oder belegt) |

## Automatisch (täglich)

Am einfachsten über `chatexporter setup`, oder direkt:

```powershell
chatexporter task create "Täglicher Update"                       # 03:00, alle Quellen
chatexporter task create "Täglicher Export" --command export --daily 04:00
chatexporter task list
```

Siehe [task_scheduler/TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md).

- Jeder geplante Lauf steht im Befehlsprotokoll (`<storage>\.storage\logs\`).
- Endet ein Lauf am Rate-Limit, plant das Programm selbst eine Fortsetzung.
- Ist die ChatGPT-Anmeldung abgelaufen, meldet es sich automatisch neu an, wenn
  Zugangsdaten eingetragen sind.

## Verhalten bei Störungen (normal, kein Datenverlust)

- **HTTP 429 (Rate-Limit):** regulärer Zustand, kein Fehler. Der Lauf endet
  regulär, eine Fortsetzung wird geplant. Mit `sync.rate_limit_wait_minutes > 0`
  wartet der Lauf stattdessen und setzt fort.
- **429 beim Listing** (eigenes, kleineres Kontingent): mindestens 5 Minuten
  warten, dann neu starten. Kommt sofort wieder 429, den Lauf regulär beenden
  und frühestens nach etwa 60 Minuten erneut versuchen.
- **Anmeldung abgelaufen (HTTP 401) mitten im Lauf:** Das Programm erneuert die
  Anmeldung im selben Browser und macht weiter. Klappt das nicht, endet der Lauf
  geordnet, mit dem Grund im Laufbericht.
- **Browser geschlossen oder Verbindung zum Browser verloren:** sofortiger,
  geordneter Abbruch ohne weitere Anfragen.
- **Verbindungsabbruch oder Timeout beim Listing:** wird bis zu dreimal mit
  Wartezeit wiederholt, danach kontrollierter Abbruch. Laufbericht prüfen,
  später neu starten.
- **Abbruch** (`aborted: true`): Grund in `abort_stage`/`abort_reason` des
  Laufberichts. Bereits gespeicherte Daten bleiben gültig, der nächste Lauf
  setzt auf.
- **Strg+C:** beendet die laufende Quelle. Der Laufbericht wird trotzdem
  geschrieben (`abort_stage: interrupted`), die nächste Quelle läuft weiter.

## Grundregeln

- Keine Secrets (Passwörter, Tokens, Cookies, `.env`-Inhalte) in Doku, Logs
  oder Berichten.
- Rohdaten und Laufzeitdateien nicht von Hand editieren; dafür gibt es Befehle.
- Bei neuen Fehlerbildern: Konsolenausgabe und Laufbericht sichern, dann in
  `workspace\_dokumentation` dokumentieren.
