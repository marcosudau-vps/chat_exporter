# Changelog

Historie bis pre-5: `../ChatExporter_Gen4_pre-5/CHANGELOG.md`.

## Unreleased

- Automatische Release-Version: Patch als Standard, Minor/Major auf Auswahl;
  erster stabiler Patch 0.0.1. Versionierter Snapshot ohne vorzeitigen Tag.
- Vollständige Tests und Windows-/Python-Bau vor dem Release. Git-Tag erst
  nach Upload und Abgleich aller GitHub-Anhänge; Veröffentlichung nach Abnahme.
- Versionierte Installer, Portable-ZIP, Wheel, Quellpaket, Berichte und Prüfsummen.
  Keine PyPI-Veröffentlichung.
- Scheduler-Werkzeug im Python-Wheel mitliefern; normale pip-Installation kann
  es auch ohne Entwicklungsquellbaum finden. Bestehende Quellen-/EXE-Pfade erhalten.

## 0.0.1rc3 — 2026-10-05: Windows-Icon und Desktop-Verknüpfung

- Vorgegebenes `assets/IconChatExporter.png` als unveränderte Vorlage;
  Windows-ICO mit sieben Größen, beim Bauen durch `packaging/make_icon.py`
  erzeugt (Pillow nur als Entwicklungsabhängigkeit).
- Programm-EXE, Setup und Deinstallation erhalten das Icon. Desktop- und
  Programm-Verknüpfungen sowie der Eintrag in Windows-Apps nutzen die Ressource.
  Das Setup erstellt die Desktop-Verknüpfung automatisch pro Benutzer;
  die Deinstallation entfernt sie.
- Tests der Konvertierung inklusive Transparenz und unverzerrter Verarbeitung
  nicht quadratischer Vorlagen; **689 Tests bestanden**. Bau erfolgreich,
  **12/12 Schnellprüfungen bestanden**, sieben Icon-Bildgrößen in beiden EXEs
  nachgewiesen. Sandbox: **46/46 bestanden**, darunter Desktop-Ziel/Icon,
  App-Icon und Entfernung. Im Testskript wird beim Ersatzbrowser-Start nun
  ausdrücklich das Benutzerverzeichnis als Arbeitsordner gesetzt; erster
  Versuch unvollständig (CFT Exitcode 7), Wiederholung mit demselben Installer grün.
- Live-Nachweis vom Benutzer nachgetragen: Edge-Profilkopie mit Anmeldung und
  wiederhergestellten Tabs; Chrome bleibt als nicht live bestätigt dokumentiert.
- Projektübersicht, Produktstand und Restplan bis GitHub-Release unter
  `../_dokumentation/10_PROJEKT/` aktualisiert; historische Arbeitsbelege erhalten.

## 0.0.1rc2 — 2026-10-05: Korrektur aus dem ersten Gesamttest

- **Gesamttest (Benutzer, `live_testablauf.py`), Schritt 1:** Die automatische
  Anmeldung brach nach dem Passwort mit „Die Anmeldeseite verlangt einen Code per
  E-Mail …“ ab, obwohl der Browser die 2FA-Seite zeigte (`auth.openai.com/mfa-challenge/…`,
  „Authenticator-App prüfen“). Das ergab die nur lesende Untersuchung des offenen
  Test-Browsers: Erkennung jetzt `mfa`, Codefeld und „Weiter“ sichtbar, keine
  Fehlermeldung.
- **Ursache:** derselbe Seitenwechsel wie am 2026-10-05 beim E-Mail-Schritt, nur an
  anderer Stelle. Die Unterscheidung „2FA-Code oder Code per E-Mail“ prüfte die vor
  der Feldsuche gelesene Adresse (noch `…/log-in/password`, ohne `mfa`), das Codefeld
  stammte schon von der neuen Seite. Die Korrektur vom Vormittag (`_checked`) griff
  erst danach.
- **Behoben:** Entschieden wird erst, wenn die Adresse vor der Feldsuche, die
  Adresse danach und das Dokument des Codefelds zur selben Seite gehören; sonst gilt
  der Moment als Seitenwechsel (`loading`). Test
  `test_code_page_reached_during_a_page_change_is_not_mistaken_for_an_email_code`
  stellt den Live-Fehler mit derselben Meldung nach (vor der Korrektur rot); eine echte
  E-Mail-Code-Seite wird weiter an den Benutzer übergeben. 686 Tests grün.
- **Konto-E-Mail in der Konsole maskiert:** `update` zeigte „ChatGPT-Sitzung validiert:
  <volle E-Mail>“ (im Gesamttest aufgefallen). E-Mail/Benutzername zählt zu den
  geschützten Angaben (`_governance/CONFIG_AND_SECRETS.md`); jetzt `m***@…` wie bei
  `chatgpt login` (`common.redaction.mask_email`, `contract.session_hint`, Test in
  `test_redaction.py`). Gespeichert wurde die volle Adresse nicht (das Befehlsprotokoll
  nimmt die Konsolenausgabe nur für die Zusammenfassung).
- Version `0.0.1rc2`. Der Installer `0.0.1rc1` enthält die Korrektur nicht und wird
  nicht weiter verwendet.

## pre-6 — Nachtrag 2026-10-05 (14): Gesamttest-Skript für den Live-Test

- **`tools/chatgpt/live_testablauf.py`** (Wunsch des Benutzers: automatisch prüfen und
  wiederverwendbar): führt den Testablauf gegen echtes ChatGPT im Entwicklungsmodus
  aus und prüft jedes Ergebnis selbst. Teil A (Anmeldung, Erstabruf, Folgelauf, lokal
  gelöschte Chats, Kontrolllauf), Teil B (geplanter, unbeaufsichtigter Lauf mit
  automatischer Anmeldung) und Zusatzfälle (fremder Ordner, Passwort über `--set`)
  laufen automatisch; Teil C (Profilkopie) interaktiv mit `--teil-c`, mit
  automatischer Prüfung der Anmeldung in der Kopie. Dazu prüft es, dass kein
  Zugangsdatum aus der `.env` in Ausgaben oder Storage-Dateien auftaucht (Vergleich
  nur im Speicher; in gespeicherten Ausgaben würden Treffer verdeckt). Eigene
  Test-Konfiguration je Lauf unter `_testlauf/<Zeitpunkt>/`. Aufräumen am Ende; den
  Registry-Spiegel der echten Konfiguration sichert es vorher und stellt ihn wieder her
  (am echten Eintrag geprüft: danach byte-gleich). Bericht als Arbeitsakte.
- **Falle im Testablauf behoben (gefunden beim Entwurf):** Ein nach dem Lauf offen
  gelassener Test-Browser auf demselben Port hätte in Teil B die Verbindung bekommen,
  dann wäre die unbeaufsichtigte Anmeldung gar nicht geprüft worden. Die
  Test-Konfiguration schließt Browser jetzt nach jedem Lauf
  (`leave_browser_running: false`), Teil B nutzt einen eigenen Port. Die Doku zum
  Ablauf von Hand ist entsprechend angepasst.
- Tests: `tests/test_live_testablauf.py` (Auswertung der Ausgaben, u. a. gegen die
  echte Ausgabe des Lösch-Werkzeugs; .env-Leser; Test-Konfiguration ladbar und
  abgeschirmt). 684 Tests grün.

## 0.0.1rc1 — 2026-10-05: Release-Kandidat 1 für 0.0.1

Beschluss des Benutzers (2026-10-05): Umfang von 0.0.1 = der implementierte Stand,
darin nichts offen; Versionsnummer 0.0.1. Kandidaten heißen `0.0.1rcN`
(docs/RELEASE.md).

**Behoben (bisher offene Fehlerbilder):**
- **Verbindung zum Playwright-Treiber weg** („Connection closed while reading from
  the driver“, `ERR-SYNC-CONN-CLOSED`): jetzt fataler, geordneter Abbruch wie beim
  geschlossenen Browser, statt den Fehler zu zählen und weiter anzufragen.
- **`MemoryError` beim Laden einer Konversation** (`ERR-SYNC-MEMORY`): Speicher
  aufräumen und genau einmal neu versuchen, noch vor dem Speichern, ohne
  Doppelzählung; ein zweiter Fehlschlag zählt als einzelner Fehler. Beide
  Fehlerbilder traten nur im Lauf 20260924T214820Z auf (je 2× von 35 Läufen); die
  betroffenen vier Konversationen wurden später fehlerfrei geladen. Tests
  `test_known_errors.py`, vor der Korrektur rot.
- **`task create --startup` ohne Administratorrechte:** Vorher erschien ein roher
  COM-Fehler. Jetzt lautet die Meldung „Windows verweigert den Zugriff (0x80070005):
  … braucht Administratorrechte … '--logon' verwenden“. Auf dem Entwicklungsrechner
  geprüft: abgelehnt, nichts angelegt. Test `test_ts_access_denied.py`
  (gemessener Fehlerwert).
- **Versionsnummer an einer Stelle:** `chatexporter/config/version.py`. Vorher lasen
  Programmkopf und Befehlsprotokoll die Paket-Metadaten. Die der
  Entwicklungsinstallation waren veraltet und wären beim Bauen ins Programm
  gewandert: Das gebaute Programm hätte im Protokoll `0.0.0.dev6` geschrieben,
  während es selbst `0.0.1rc1` meldet. Test `test_version_source.py`.
- **Links:** 19 kaputte Links auf die verschobene Zeitplan-Doku
  (`docs/task_scheduler/TASK_SCHEDULER.md`) berichtigt; der Linkcheck über alle
  Markdown-Dateien (ohne `historie/`) findet keinen mehr.

**Release-Vorbereitung:**
- Version `0.0.1rc1` (`config/version.py`, `pyproject.toml`).
- Neue Dokumente:
  - `docs/V0.0.1_PRODUCT_SCOPE.md` (Umfang, Nicht-Umfang, Abnahmekriterien)
  - `docs/BEKANNTE_EINSCHRAENKUNGEN.md`
  - `docs/RELEASE.md`, `docs/SECURITY.md`, `docs/TESTING.md`,
    `docs/CONTRIBUTING.md`
- `docs/GETTING_STARTED.md` neu gegliedert: Teil A installiertes Programm
  (Installieren, Einrichten, automatische Anmeldung, Ablage, Aktualisieren,
  Deinstallieren, Weg von älteren Testprogrammen), Teil B Entwicklung.
- `.env.example` mit Storage-`.env`, richtigem Vorrang, `CHATEXPORTER_STORAGE`,
  Fenster und Entwicklungsmodus.
- Komplett-Test auf frischem Windows jetzt im Projekt: `packaging/sandbox/`
  (`run_sandbox_test.py`, `sandbox_test.ps1`); neu darin die Prüfung von
  `task create --startup`.
- Testablauf um **Teil B** (geplanter, unbeaufsichtigter Lauf mit neuem Profil und
  automatischer Anmeldung) und **Teil C** (Profilkopie mit Schließen und
  Wiederöffnen des echten Browsers, Edge und Chrome) ergänzt. Er arbeitet jetzt mit
  einer eigenen Test-Konfiguration statt Umgebungsvariablen: Eine geplante Aufgabe
  übernimmt sie über `--config`, und eine Aufgabe nimmt kein vorangestelltes
  `--set` an (geprüft).
- Offene Punkte in Live-Test-Checkliste, Zeitplan-Doku, Roadmap und Fehlerreferenz
  auf den Stand gebracht. Offen bleiben nur die Live-Prüfungen des Benutzers
  (Testablauf A–C) und die menschliche Abnahme.
- Tests: 679 grün, keiner rot.
- **Gebaut:** `_build/0.0.1rc1`, Schnellprüfung 12/12; Installer-SHA-256
  `02738287fa9fb29af7bfeef03a58ce8963feef0859c620d89c3c47a61c022227`. Im gebauten
  Programm melden `--version` und Befehlsprotokoll `0.0.1rc1` (abgeschirmt geprüft).
  Release-Paket: `workspace/_release/0.0.1rc1/` (Installer, `SHA256SUMS.txt`,
  `RELEASE_NOTES.md`, `PRUEFUNGEN.md`, Build-Bericht).
- **Komplett-Test auf frischem Windows (Windows Sandbox, Windows 10.0.26100, Edge,
  kein Python): 41 von 41 bestanden**, mit dem neuen Startprogramm
  `packaging/sandbox/run_sandbox_test.py`. Neu darin: `task create --startup` mit
  Administratorrechten angelegt und wieder entfernt. Zwei Startversuche davor
  scheiterten an der Windows-Sandbox selbst („Fehler beim Initialisieren … 0x8007007F“);
  nach einem Neustart des Rechners (Windows-Update auf Build 26300) lief sie.

## pre-6 — Nachtrag 2026-10-05 (13): Korrekturen aus dem Release-Check, Entwicklungsmodus einstellbar, Testablauf

Grundlage: Release-Check vom 2026-10-05
(`_dokumentation/60_ARBEITSDOKUMENTATION/2026-10-05_release_check_pre-6/BERICHT.md`),
Auftrag des Benutzers: offensichtliche Fehler beheben, `storage migrate` fortsetzbar,
Problem „leerer Ordner“ lösen, Entwicklungsmodus prüfen, Testablauf schreiben.

- **Secrets aus `--set` werden nicht mehr gespeichert.** Vorher stand z. B.
  `--set providers.chatgpt.auth.password=…` im Klartext im Befehlsprotokoll
  (`command`, `argv`), in `state.yaml`/Registry (`storage.last_command`) und während
  des Laufs in `lock.json`. Jetzt verdeckt `cli.main.redact_cli_args` die Werte
  geheimer Schlüssel (`…=(verdeckt)`), bevor die Befehlszeile irgendwohin geschrieben
  wird. Test `tests/cli/test_secret_redaction.py` (durchsucht alle geschriebenen
  Dateien nach dem Wert).
- **Storage-Format „fremd“** (Entscheidung des Benutzers): Ein nicht leerer Ordner
  ohne `.storage/`, `runtime/` oder `raw_storage/` wird nicht mehr ungefragt zum
  Storage, sondern abgelehnt (Exitcode 2, nichts verändert). Systemdateien
  (`desktop.ini`, `Thumbs.db`, `.DS_Store`) zählen nicht. Fremde Dateien **in** einem
  bestehenden Storage bleiben erlaubt. Der bisherige Test, der das alte Verhalten
  festschrieb, ist angepasst.
- **`storage migrate` fortsetzbar:** Neues Format „Umstellung abgebrochen“
  (`.storage/` ohne Marker, mit `runs/` oder `status_registry/`, dazu `raw_storage/`,
  ohne `runtime/`). Befehle verweigern es mit Hinweis, `storage migrate` setzt fort
  (Staging einordnen, Marker schreiben; neue ID). Tests mit nachgestelltem Abbruch
  nach dem Umbenennen, inkl. Probelauf und Prüfsummen der Dateien.
- **Lokal gelöschte Chats werden immer neu geladen:** Vorher bemerkte `auto`
  (sparsames Listing) einen lokal gelöschten **älteren** Chat nicht, weil er hinter
  der Änderungsgrenze liegt. Jetzt merkt sich der Index beim Laden fehlende Dateien
  in `<status_registry>/lost_conversations.json` (eigene Datei, weil der
  Gesamtindex beim Zusammenführen neu geschrieben wird); `auto` wechselt dann auf
  `full` (`escalation: local_files_missing`, `detail.listing.local_missing`), auch
  über einen abgebrochenen Lauf hinweg, bis die Chats wieder da sind. Tests in
  `test_listing_recent.py`.
- **Entwicklungsmodus einstellbar:** Neuer Abschnitt `dev` (`dev.listing_max_pages`,
  `dev.conversation_fetches` mit `0` = kein simuliertes Rate-Limit,
  `dev.refill_minutes`, `dev.rate_limit_wait_minutes`,
  `dev.continuation_delay_minutes`); vorher fest 3 Seiten und 5 Abrufe. Einträge je
  Seite: wie bisher `providers.chatgpt.sync.listing_limit`. Die Hinweiszeile nennt
  die eingestellten Werte. Tests in `test_dev_mode.py`.
- **Altlasten `runtime/` bereinigt:** Ausweichpfad des Sperrvermerks
  (`auto_login.default_block_file` → `.storage/auth/…`, mit Test), veralteter
  Standard `workspace/runtime/edge_user_data` in `config/models.py` und `loader.py`
  (jetzt `browser/profiles/edge`), Kommentar zu `runtime_root`.
- **Doku:** beschädigter Rest in `KONFIGURATION.md` gelöscht (reine Doppelung,
  siehe Release-Check); Tabellenzeilen `dev.*` und Abschnitt 8 neu;
  `STORAGE_KONZEPT.md` (F7 übernommen, Zustandswerte richtig benannt und ergänzt,
  Formate „fremd“/„Umstellung abgebrochen“), `STORAGE-SCHEMA-2.md`, `BEFEHLE.md`,
  `providers/CHATGPT.md` (Grund `local_files_missing`); veraltete Aussagen in
  `ROADMAP.md` und `LIVE_TEST_CHECKLIST.md` berichtigt; `config.example.yaml` neu
  erzeugt.
- **Testablauf** `docs/TESTABLAUF_ENTWICKLUNGSMODUS.md`: neues Profil mit
  automatischer Anmeldung → Erstabruf auf 5 Seiten → Folgelauf → Chats nur lokal
  löschen → `update` lädt genau diese, ohne erneute Anmeldung, mit demselben Profil.
  Dazu das Werkzeug `tools/chatgpt/local_delete_probe.py` (wählt neuesten, mittleren
  und ältesten Chat; ohne `--ausfuehren` nur Anzeige; verweigert Storages mit mehr
  als 200 Konversationen – am echten Bestand geprüft: verweigert), mit Test. Die
  Befehle ohne ChatGPT-Bezug wurden vorab in einem Zwischenordner ohne Registry
  ausprobiert (Storage anlegen, `dev.*` aus der Umgebung, fremder Ordner abgelehnt,
  Fortsetzung per Umgebung abschaltbar). **Der Ablauf selbst ist noch nicht
  ausgeführt.**
- Tests: 674 grün, keiner rot.

## pre-6 — Nachtrag 2026-10-05 (12): Übernahme der Arbeitskopie `pre-6_autologin`

Mit Freigabe des Benutzers (2026-10-05) übernommen; die Einträge der Arbeitskopie
folgen unten. Darin als „in `pre-6` noch nicht enthalten“ bezeichnete Korrekturen
(Zertifikate über `truststore`, Browserstart mit leerer Seite) sind damit enthalten.

- **Vorher:** vollständige Sicherung von `pre-6` unter
  `workspace/_sicherung/ChatExporter_Gen4_pre-6_vor-autologin_2026-10-05_01-35-22`
  (mit dem Original verglichen: identisch). Ausgangsstand: 603 Tests grün.
- **Bestandsaufnahme** (Vergleich mit dem Anlagezeitpunkt der Kopie, 2026-10-03
  10:38): 11 Dateien nur in der Kopie neu und 18 nur in der Kopie geändert →
  übernommen (Zeilenenden wie die bisherige `pre-6`-Datei, `two_factor_tools/core.py`
  byte-gleich, SHA-256 beginnt mit `3dec9b9b042eb7cf`); 70 Dateien nur in `pre-6`
  neu/geändert → unverändert; 9 in beiden geändert → von Hand zusammengeführt:
  `config/schema.py` (Fenster- und Anmelde-Einstellungen), `config/cli.py`
  (Secrets verdeckt, auch in Abschnitten), `providers/chatgpt/config/loader.py`
  (`_auth_config`, `window`), `config.example.yaml` (neu erzeugt), README, BEFEHLE,
  KONFIGURATION (neue Tabellenzeilen, Abschnitt 7a), providers/CHATGPT.md, CHANGELOG.
- **Anpassung an die Storage-Ebene:** Zugangsdaten werden aus der Umgebung, der
  globalen `.env` und der Storage-`.env` (Herkunft `storage .env`) angenommen, aus
  keiner Config-Datei (global oder Storage). Neuer Test
  `test_credentials_from_the_storage_dotenv_but_never_from_the_storage_config`.
  Der Sperrvermerk liegt unter `<storage>/.storage/auth/auto_login_block.json`.
- **Tests:** 661 grün, keiner rot (603 bisherige + 58 aus der Kopie bzw. neu).
- **Installer** neu gebaut nach `_build/0.0.0.dev6-autologin` (Schnellprüfung 12/12).
  **Windows Sandbox** (Windows 10.0.26100, Edge, kein Python): **38 von 38 Prüfungen
  ok** – Installation, Home `~/.chatexporter`, `storage show`, `chatgpt login
  --schrittweise`, `browser.window` = `offscreen`, Secrets verdeckt, status/export/
  task list, Einrichtung mit täglicher Aufgabe, geplanter Lauf (Ergebnis 0), Edge
  verborgen sowie ohne Synchronisierung und stille Kontoanmeldung gestartet,
  ChatGPT-Lauf ohne Anmeldung endet geordnet, Chrome for Testing frisch geladen
  (196 MB), verborgen gestartet, ferngesteuert, geschlossen; Deinstallation
  vollständig, Datenordner bleibt.
- **Nebenwirkung beim Prüfen, behoben:** Ein lokaler Aufruf des gebauten Programms
  (`chatgpt login -h`) legte `C:\Users\<Benutzer>\.chatexporter` und den
  Registry-Eintrag `Storages\d265a94c…` an. Beides war nachweislich gerade erst
  entstanden (alle Einträge 01:47), wurde gesichert (`reg export`) und entfernt; der
  alte Datenordner `~/.chat_exporter` und der Eintrag von `workspace\data` blieben
  unberührt.
- **Vorgefunden, nicht geändert:** In `docs/KONFIGURATION.md` steht nach der
  Schlüsseltabelle ein beschädigter Rest (beginnt mitten in einer Zeile, wiederholt
  ältere Tabellenzeilen); schon in der Sicherung vorhanden.

## Arbeitskopie `pre-6_autologin` — 2026-10-05 (3): Komplett-Test auf frischem Windows

- Installer neu gebaut (`_build/autologin-test`, Schnellprüfung 11/11; im gebauten
  Programm `chatgpt login --schrittweise` vorhanden).
- **Windows Sandbox** (Windows 10.0.26100, Edge vorhanden, kein Python): **37 von 37
  Prüfungen ok** – zusätzlich zu den bisherigen 32: `--schrittweise` vorhanden,
  `browser.window` = `offscreen`, Edge vom ChatExporter gestartet mit
  `--window-position=-32000,-32000`, `--disable-sync` und
  `--disable-features=msImplicitSignin` (Befehlszeile während des Laufs beobachtet),
  Chrome for Testing verborgen und mit `--disable-sync` gestartet. Ersatz-Browser
  frisch heruntergeladen (196 MB), entpackt, gestartet, ferngesteuert, geschlossen;
  Deinstallation vollständig, Datenordner bleibt.

## Arbeitskopie `pre-6_autologin` — 2026-10-05 (2): Neuanmeldung mitten im Lauf

- **HTTP 401 während des Laufs:** `ApiClient` erneuert über `reauthenticate` die
  Anmeldung und wiederholt genau diese Anfrage einmal; höchstens 2 Erneuerungen je
  Lauf (`max_reauth`). `contract.reauthenticator` nutzt dafür den AuthBroker im selben
  Browser (Sitzung neu prüfen → automatische Anmeldung → nur mit Interaktion von
  Hand); der Broker entsteht erst beim ersten 401. Scheitert die Erneuerung, bleibt es
  beim 401 und der Lauf endet wie bisher. Nur 401, nicht 403. Laufbericht: `reauth`
  (Endpunkt, Erfolg, Grund, ob sich der Token geändert hat – nie Tokens).
- Tests: `test_reauth_midrun.py` (8: Erneuern und einmal wiederholen inkl. Zählung,
  ohne Erneuerung bleibt 401, gescheiterte Erneuerung mit Grund, Obergrenze je Lauf,
  Anfragen ohne Bearer und andere Fehler lösen nichts aus, Broker erst bei Bedarf und
  ohne Interaktion nie von Hand, gescheiterte Neuanmeldung endet mit Grund). Vor der
  Umsetzung schlugen die Client-Tests fehl. 627 Tests grün, einer nicht (der bekannte
  `test_the_scheduled_command_really_runs`).
- Neues Prüfwerkzeug `tools/chatgpt/reauth_check.py`: löst mit absichtlich ungültigem
  Token ein echtes 401 aus und prüft die Erneuerung (6 Anfragen; ohne `--live` nur
  Plan).
- **Live geprüft** (mit OK des Benutzers, angemeldetes Testprofil
  `_login_test_profil4`): Sitzung gültig → Listing (limit=1) mit ungültigem Token →
  HTTP 401 → Erneuerung über den Browser (neuer Token) → Wiederholung erfolgreich
  (1 Eintrag). 6 Anfragen (auth 4, listing 2), kein Rate-Limit.

## Arbeitskopie `pre-6_autologin` — 2026-10-05: Seitenwechsel fälschlich als fremde Seite erkannt

- **Live-Test `login --schrittweise` durch den Benutzer:** Abbruch mit „Anmeldefeld auf
  einer nicht erwarteten Seite (password auf https://chatgpt.com)“, obwohl der Browser
  `https://auth.openai.com/log-in/password` zeigte.
- **Ursache:** Die Erkennung las die Seitenadresse vor der Feldsuche. Nach „Weiter“ im
  E-Mail-Schritt wechselte die Seite genau dazwischen: Adresse noch `chatgpt.com`,
  Passwortfeld schon von `auth.openai.com`. Der Seitenschutz verglich also mit einer
  veralteten Adresse. Es wurde nichts falsch eingetragen.
- **Behoben:** Maßgeblich sind jetzt das Dokument, zu dem das Feld gehört, und die
  unmittelbar danach gelesene Seitenadresse. Passen vorher und jetzt gelesene Adresse
  nicht zusammen, gilt das als Seitenwechsel (`loading`, neu erkennen). Bleibt die
  Seite gleich, gehört das Feld aber zu einem anderen Dokument, ist es weiterhin ein
  fremder Rahmen (sofortiger Abbruch). Ist das Feld direkt vor dem Eintragen
  verschwunden, wird neu erkannt statt abgebrochen. Neuer Test
  `test_page_change_between_reading_the_address_and_finding_the_field_is_no_foreign_page`
  (stellt den Live-Fehler mit derselben Meldung nach, besteht nach der Korrektur); alle
  Tests zu fremden Seiten bestehen weiter. 318 ChatGPT-Tests grün.
- **Live bestätigt** (Benutzer, `login --profil .\_login_test_profil4 --schrittweise`):
  vier Halte, Meldung jeweils passend zur Seite (`chatgpt.com/` Anmelde-Button und
  E-Mail-Feld, `auth.openai.com/log-in/password`, `auth.openai.com/mfa-challenge/…`),
  Anmeldung erfolgreich, 3 Anfragen. Schritte `login_button, email, loading, password,
  mfa, auth_wait, chatgpt` – `loading` ist der jetzt abgewartete Seitenwechsel. Damit
  sind auch `--schrittweise`, das menschliche Tempo und die Seitenprüfung live geprüft.

## Arbeitskopie `pre-6_autologin` — 2026-10-04 (4): Fenster verborgen, menschliches Tempo, schrittweise Anmeldung

- **Browserfenster** (neue Einstellung `providers.chatgpt.browser.window`:
  `offscreen` Standard, `minimized`, `visible`): Ein selbst gestarteter Browser startet
  außerhalb des Bildschirms (`--window-position=-32000,-32000`) bzw. wird minimiert;
  gezeigt wird er nur, wenn der Benutzer etwas tun muss (Anmeldung von Hand,
  `login --schrittweise`), danach wieder verborgen; bleibt er nach dem Lauf offen,
  wird er sichtbar abgelegt und minimiert. Versuche auf dem Entwicklungsrechner
  (Edge, lokale Nachbildung, Programmcode): Minimieren/Zeigen per CDP zuverlässig,
  sobald kein Synchronisierungs-Fenster mehr stört (vorher „Browser window not
  found“); Anmeldung außerhalb des Bildschirms rund 2 s, minimiert rund 6 s, die
  Optionen gegen das Bremsen (`--disable-background-timer-throttling` u. a.) ohne
  Wirkung. Mit echtem Edge auf chatgpt.com: verborgen gestartet, gezeigt, der Benutzer
  sah die normale, nicht angemeldete ChatGPT-Seite; ein weiterer Schritt (Klick auf
  „Anmelden“) öffnete das E-Mail-Feld – erkannt als `email` auf `chatgpt.com`.
- **Menschliches Tempo** (Wunsch des Benutzers): zufällige Pause 1,5–4 s vor jedem
  Schritt, Klick ins Feld, Tippen Zeichen für Zeichen (60–180 ms), kurzes Zögern vor
  „Weiter“; Rückfall auf direktes Setzen, wenn beim Tippen Zeichen fehlen.
  Sicherheitsprüfungen werden weiterhin nie umgangen.
- **`chatgpt login --schrittweise`:** Fenster sichtbar; vor jedem Schritt Meldung, was
  erkannt wurde (Seite mit Host und Pfad) und was als Nächstes geschieht; ausgeführt
  erst nach ENTER, `a` bricht ab. Wartezeit auf den Benutzer zählt nicht gegen das
  Zeitlimit; am Ende bleibt der Browser bis ENTER offen. Live geprüft am 2026-10-05
  (siehe oben).
- Tests: `test_browser_window.py` (10: Startoption je Einstellung, Zeigen/Verbergen,
  minimiert, sichtbarer Modus und fremder Browser nie verborgen, Fensterfehler brechen
  nichts ab, offen gelassener Browser nie unsichtbar, Anmeldung von Hand zeigt und
  verbirgt, gültige Sitzung zeigt nichts) und 6 in `test_auto_login.py` (Pausen und
  zeichenweises Tippen, ohne Tempo, Rückfall beim Tippen, schrittweise mit
  Seitenangabe und ohne Zugangsdaten in den Meldungen, Abbruch, Wartezeit). Der
  Ende-zu-Ende-Test mit echtem Edge tippt jetzt wirklich. `config.example.yaml` und
  die Tabelle in `docs/KONFIGURATION.md` nachgezogen. 618 Tests grün, einer nicht (der
  bekannte `test_the_scheduled_command_really_runs`, siehe unten).

## Arbeitskopie `pre-6_autologin` — 2026-10-04 (3): Anmeldedaten nur auf den echten Anmeldeseiten

- **Zweiter Live-Test** (neues leeres Profil): erfolgreich, Einmalcode nur noch einmal
  eingetragen – die Korrektur aus (2) ist damit live bestätigt.
- **Sicherheitslücke behoben (Hinweis des Benutzers):** Der Anmeldeablauf erkannte den
  Schritt nur am Eingabefeld (z. B. irgendein Passwortfeld), prüfte aber nicht, auf
  welcher Seite es steht. Jetzt gilt (`ALLOWED_PAGES`): E-Mail nur auf `chatgpt.com`
  oder `auth.openai.com`, Passwort und Einmalcode nur auf `auth.openai.com`, immer
  https, Hostname exakt (vorher zählten auch Subdomains von `openai.com`). Geprüft beim
  Erkennen und direkt vor dem Eintragen am Feld selbst (Dokument des Felds, gegen
  fremde eingebettete Rahmen). Sonst sofortiger Abbruch ohne Eintragen
  (Zustand `foreign`, Übergabe an den Benutzer).
- Anmeldeseite ohne Eingabefeld (Weiterleitung) heißt jetzt `auth_wait` statt
  `unknown`; das Ergebnis von `chatgpt login` enthält die besuchten Seiten (`pages`,
  Host und Pfad ohne Query).
- Tests: 8 neue (fremde Seite, ChatGPT statt Anmeldeseite, ohne https, Subdomain,
  ähnlicher Name, fremder Rahmen, E-Mail/Code auf fremder Seite, echter Browser mit
  falschem Host); ohne die Prüfung schlagen alle 8 fehl. 298 ChatGPT-Tests grün.
- **Beobachtung:** Edge mit neuem leeren Profil zeigte auf dem
  Entwicklungsrechner von sich aus „Wir synchronisieren Ihre Daten mit all Ihren
  Geräten“ (Anmeldung mit dem Windows-Konto), danach öffneten sich Tabs von
  Erweiterungen. *Beobachtung:* Das Testprofil `_login_test_profil2` aus dem
  Live-Test ist mit einem Konto verbunden (`account_info` 1 Eintrag, Synchronisierung
  eingerichtet) und enthält 4 Erweiterungsordner, die der ChatExporter nie angelegt
  hat. *Deutung (wahrscheinlich, nicht abschließend belegt):* Edge meldet neue Profile
  automatisch mit dem Microsoft-Konto von Windows an und holt Daten und Erweiterungen
  über die Synchronisierung. Betrifft auch den Weg „Edge mit eigenem, leerem Profil“.
- **Behoben (Entscheidung des Benutzers: Startoptionen ausprobieren):** Messreihe mit
  neuen Edge-Profilen, je 20 s, nur Ja/Nein und Anzahlen gelesen:
  ohne Optionen → Konto verbunden, synchronisiert, 11 Erweiterungen (u. a. ein
  Passwortmanager), Synchronisierungs-Fenster; `--disable-sync` → Konto verbunden, nicht
  synchronisiert, 3 Erweiterungen; `--disable-features=msImplicitSignin` (mit und ohne
  `--disable-sync`, zweimal) → kein Konto, nicht synchronisiert, 3 Erweiterungen;
  `msEdgeImplicitSignin` und vorab gesetztes `signin.allowed=false` → wirkungslos.
  Umsetzung: Jeder selbst gestartete Browser bekommt `--disable-sync`, Edge zusätzlich
  `--disable-features=msImplicitSignin` (`IMPLICIT_SIGNIN_OFF`). Probe mit dem
  Programmcode (`EdgeCdpSession`, neues Profil): kein Konto, keine Synchronisierung,
  3 Erweiterungen, keine fremden Seiten. Test
  `test_own_browser_never_syncs_with_an_account`; 301 ChatGPT-Tests grün. Alle
  Test-Browser geschlossen, Testprofile gelöscht.

## Arbeitskopie `pre-6_autologin` — 2026-10-04 (2): erster Live-Test der automatischen Anmeldung

- **Live-Test durch den Benutzer** gegen chatgpt.com mit leerem Profil
  (`chatgpt login --profil .\_login_test_profil`): Anmeldung erfolgreich, Schritte
  Anmelde-Button → E-Mail → Passwort → Einmalcode → ChatGPT, 3 Anfragen.
- **Befund:** Die Ausgabe meldete den Einmalcode zweimal (16 s und 15 s Restzeit).
  Ursache: Die Code-Seite war nach dem Klick auf „Weiter“ noch kurz zu sehen, und der
  nächste Durchgang (0,7 s später) schickte denselben Code noch einmal ab. Es war
  ein einziger Code (gleiches 30-s-Zeitfenster), aber zweimal abgeschickt.
- **Behoben:** Derselbe Schritt wird frühestens nach 10 s wiederholt
  (`RETRY_AFTER_SECONDS`); eine echte Wiederholung des Einmalcodes wartet auf einen
  neuen Code. Neue/geänderte Tests: `test_slow_code_page_gets_the_code_only_once`
  (schlägt ohne die Korrektur fehl), `test_wrong_one_time_code_is_tried_twice_at_most_and_with_a_new_code`.
  289 ChatGPT-Tests grün. **Korrektur noch nicht live geprüft.**

## Arbeitskopie `pre-6_autologin` — 2026-10-04: Test auf frischem Windows, Zertifikatsfehler behoben

- **Test in Windows Sandbox** (Windows 10.0.26100, Edge vorhanden, kein Python) mit dem
  Installer aus dem aktuellen `pre-6` (Stand 2026-10-04, 603 Tests grün): 24 von 25
  Prüfungen ok – stille Installation, 4 Startmenü-Einträge, Eintrag unter „Apps“,
  PATH, Start ohne Python, `config path`, `storage show`, `status`, `export`,
  `task list`, tägliche Aufgabe angelegt, geplanter Lauf über die Aufgabenplanung
  (Ergebnis 0), ChatGPT-Lauf ohne Anmeldung endet geordnet (Edge mit eigenem Profil
  gestartet, Anmeldung geprüft, wieder geschlossen), Deinstallation entfernt
  Programm, Startmenü, Registry, „Apps“-Eintrag, Aufgaben und PATH; Datenordner
  bleibt. Die eine Abweichung (`setup` nahm „n“ nicht an) lag am Testaufbau
  (PowerShell schreibt ein unsichtbares Zeichen vor die Eingabe); lokal mit
  sauberer Eingabe geprüft: `setup` arbeitet richtig.
- **Fehler gefunden und behoben:** Der Download von Chrome for Testing scheiterte auf
  frischem Windows mit `CERTIFICATE_VERIFY_FAILED` (Pythons eigene Prüfung lädt
  fehlende Stammzertifikate nicht nach). Jetzt prüft Windows selbst über
  `truststore` (neue Abhängigkeit). In der Sandbox mit einem Build dieser
  Arbeitskopie bestätigt: Versionsliste geladen. **In `pre-6` noch nicht enthalten.**
- **Zweiter Fehler gefunden und behoben:** Chrome for Testing ließ sich nach dem
  Download nicht fernsteuern – mit ChatGPT als Startseite blieb die Verbindung
  (`connect_over_cdp`) ohne Antwort hängen; auch auf dem Entwicklungsrechner
  nachgestellt. Jetzt startet jeder Browser mit einer leeren Seite, ChatGPT wird
  erst nach dem Verbinden geöffnet (leere Seite wird wiederverwendet, kein
  zusätzlicher Tab). Gemessen: Chrome for Testing und Edge mit leerem Profil
  verbunden nach rund 2 s. Neuer Test `test_browser_starts_empty_and_chatgpt_opens_after_connecting`.
- **Vollständiger Test des Installers dieser Arbeitskopie in Windows Sandbox:
  32 von 32 Prüfungen ok** – zusätzlich zu den obigen: Befehl `chatgpt login`
  vorhanden, Passwort in `config list` nicht angezeigt, `setup` mit täglicher
  Aufgabe, Chrome for Testing heruntergeladen (196 MB), entpackt, gestartet,
  ferngesteuert, Anmeldung geprüft, wieder geschlossen.
- 589 Tests grün in der Arbeitskopie, einer nicht (siehe hier); `test_ts_windows::test_the_scheduled_command_really_runs`
  schlägt hier nur fehl, weil die Aufgabenplanung die venv nutzt, die auf das
  inzwischen geänderte `pre-6` zeigt (Lauf selbst mit Ergebnis 0).

## Arbeitskopie `pre-6_autologin` — 2026-10-03: automatische Anmeldung mit 2FA

Separater Arbeitsstand (Kopie von pre-6), noch nicht nach pre-6 übernommen.

- Neu: automatische ChatGPT-Anmeldung (E-Mail, Passwort, Einmalcode), wenn keine
  gültige Sitzung besteht – auch in geplanten Läufen
  ([docs/providers/CHATGPT.md](docs/providers/CHATGPT.md), Abschnitt 2a).
  Neue Module `auth/auto_login.py`, `auth/totp.py`; `AuthBroker.acquire` versucht
  zuerst die automatische, dann die manuelle Anmeldung.
- Neu: Bibliothek `src/two_factor_tools/` (Two-Factor Tools V4, unveränderte
  Kopie, Prüfsumme im Test), optionale Abhängigkeit `cryptography` (`[autologin]`).
- Neue Einstellungen `providers.chatgpt.auth.*` (`auto_login`,
  `login_timeout_seconds`, Secrets `username`, `password`, `totp_secret`,
  `totp_reference` mit `CHATGPT_USERNAME`, `CHATGPT_PASSWORD`,
  `CHATGPT_2FA_SECRET`, `CHATGPT_2FA_REFERENCE`).
- Neu `chatexporter chatgpt login [--profil DIR]`.
- Sicherheit: Secrets nur aus `.env`/Umgebung; `config list`/`get` maskieren
  Secrets (vorher wären sie im Klartext ausgegeben worden); Sperrvermerk nach
  abgelehnten Zugangsdaten; Captchas werden nie umgangen.
- **Belegt:** 588 Tests grün, davon 17 neu (inkl. 2 Ende-zu-Ende-Tests mit echtem
  Edge gegen eine lokale Nachbildung der Anmeldeseiten). **Nicht live gegen
  chatgpt.com geprüft.**

## pre-6 — Nachtrag 2026-10-03 (11): Storage-Schema versioniert

- Das Format des Datenbestands heißt **Storage-Schema** und hat eine eigene
  Zählung, die nie mit der Programmversion verwechselt werden darf:
  Storage-Schema 1 = Datenordner mit `runtime/`, Storage-Schema 2 = Storage mit
  `.storage/`. Schreibweise: „Storage-Schema N“, `storage-schema-N`,
  Marker-Feld `storage_schema: N`.
- Code: Marker `.storage/storage.yaml` mit `storage_schema: 2` (statt `schema: 1`),
  Formatnamen `storage-schema-1`/`storage-schema-2`, Zustandswert
  `storage.storage_schema`; alle Meldungen nennen das Storage-Schema.
- Neu [docs/storage_schema/](docs/storage_schema/README.md): eigenständige
  Dokumente `STORAGE-SCHEMA-1.md` und `STORAGE-SCHEMA-2.md` (Übersicht mit
  Baum und Regeln, danach vollständige Beschreibung).
- Neu `workspace/.archiv/storage_schema/`: Sicherung des Entwicklungsbestands
  im Storage-Schema 1 als ZIP vor der Umstellung (mit `.json`: Dateianzahl,
  Größen, SHA-256, Prüfergebnis).
- Hinweis: Das Feld `storage_schema_version` im ChatGPT-Envelope ist die
  Formatversion des Envelopes, kein Storage-Schema (in den Dokumenten so gekennzeichnet).
- **Entwicklungsbestand umgestellt:** `workspace/data` vorher als ZIP gesichert
  (`.archiv/storage_schema/storage-schema-1_workspace-data_2026-10-03.zip`:
  11.516 Dateien, 2,77 GB → 1,09 GB, CRC und Dateiliste geprüft), dann mit
  `storage migrate --fix-config` auf Storage-Schema 2 umgestellt
  (`logging.dir` in der `workspace/config.yaml` auskommentiert, Sicherung in
  `.config_backups/`). Rohdaten unverändert (5268 Dateien, gleiche Bytezahl);
  danach `check` ohne Fehler, `index` 3404 Einträge (100 %), `status` mit allen
  vier Quellen.
- **Belegt:** 603 Tests grün.

## pre-6 — Nachtrag 2026-10-03 (10): Storage – Programm und Datenhaltung getrennt

Umsetzung von [docs/STORAGE_KONZEPT.md](docs/STORAGE_KONZEPT.md) (Beschlüsse F1–F9):

- **Storage** = autarke Dateninstanz mit eigenen Daten, Zustand, Konfiguration
  und Registry-Bereich. Standard `~/.chatexporter/storages/default`; Auswahl über
  `--storage PFAD`, `CHATEXPORTER_STORAGE`, `storage.root` (älterer Name
  `storage.data_root`). Aufbau: `.storage/` (bisher `runtime/`) mit
  `storage.yaml` (Marker), `config.yaml`, `.env`, `state.yaml`, `logs/`, `runs/`,
  `status_registry/`, `tasks_sched.json`, `staging/`, `lock`; dazu `raw_storage/`, `exports/`.
- **Konfiguration:** Storage-`config.yaml` und -`.env` sind eine zusätzliche,
  spezifischere Ebene (`layered_config`: neue Scope-Ebene). `config set/reset`
  ändern den Storage, neu `config-global` die globale Datei; Programm-, Orts- und
  Browser-Einstellungen gelten nur global. Befehlsprotokoll standardmäßig im Storage.
- **Schutz:** Formaterkennung nur über eindeutige Marker; ein Ordner im alten
  oder unklaren Format wird von keinem Befehl angefasst (Exitcode 2).
- **Migration:** neu `chatexporter storage migrate [--dry-run] [--fix-config]`
  und `storage show`.
- **Zustand:** Werte in der Registry (`Storages\<id>\State`): letzter Befehl,
  Updates (Anzahl, Ergebnis), erster vollständiger Abruf mit Schätzung, nächster
  geplanter Lauf, Bestand je Quelle. `state.yaml` wird nach jedem Befehl daraus
  erzeugt und enthält zusätzlich die wirksame Konfiguration mit Herkunft und alle Pfade.
- **Sperre:** höchstens ein schreibender Lauf je Storage (`.storage/lock`).
  **Staging** liegt in `.storage/staging/`; leere Ordner werden nach jedem
  Befehl entfernt.
- **Aufgaben** gehören einem Storage (`--storage` im Befehl, Eigentümer
  `chatexporter-<id>`); `uninstall --remove-tasks` (vom Installer genutzt) und
  `uninstall` entfernen die Aufgaben aller bekannten Storages.
- **Belegt:** 603 Tests grün (neu u. a. `test_lc_scope.py`,
  `test_storage_instance.py`, `test_storage_state.py`, `test_storage_cli.py`).
  Migration auf einer **Kopie** des Entwicklungsbestands (2,7 GB): Rohdaten
  unverändert (5268 Dateien, gleiche Größe), danach `check` ohne Fehler, `index`
  3404 Einträge (100 %), `status` mit allen vier Quellen. Gebautes Programm:
  Smoke-Test 12/12 inklusive `storage show`. **Nicht umgestellt:** der echte
  Entwicklungsbestand `workspace/data` (wartet auf Freigabe).

## pre-6 — Nachtrag 2026-10-03 (9): Home `~/.chatexporter`, Storage-Konzept (Entwurf)

- Home-Ordner heißt jetzt `~/.chatexporter` (wie der Befehl) statt
  `~/.chat_exporter`; Code, Installer, Tests und Doku angepasst. Ein vorhandener
  Ordner `~/.chat_exporter` wird **nicht** automatisch übernommen.
- Neu [docs/STORAGE_KONZEPT.md](docs/STORAGE_KONZEPT.md): **Entwurf** zur
  Trennung von Programm und Datenhaltung („Storage“ als autarke Dateninstanz);
  nicht umgesetzt, offene Fragen F1–F9.
- **Belegt:** 571 Tests grün.

## pre-6 — Nachtrag 2026-10-03 (8): Profilkopie – Ablageort, Name, Browser schließt Setup

Rückmeldung aus der ersten echten Einrichtung umgesetzt
([docs/providers/CHATGPT.md](docs/providers/CHATGPT.md), Abschnitt 2):

- **Ablageort:** Browser-Profile und Chrome for Testing liegen nicht mehr im
  Datenordner, sondern im Ordner `browser` neben der config.yaml
  (installiert `~/.chat_exporter/browser`).
- **Name:** Eine Kopie heißt `<JJJJ-MM-TT_hh-mm-ss>_<Profilordner>` statt
  `<art>-kopie-<profil>`; je Quellprofil zählt die neueste Kopie.
- **Browser schließen:** Setup schließt den Browser mit diesem Profil selbst
  (Windows Restart Manager, nur die Prozesse dieses Datenverzeichnisses, erst
  regulär, dann erzwungen) und öffnet ihn danach mit `--restore-last-session`
  wieder; der Benutzer bestätigt nur noch oder überspringt. Neu
  `auth/process_control.py`.
- Bestehende Kopien unter `data/browser/` werden nicht verschoben; eine neue
  Einrichtung (`chatexporter setup` → „neu einrichten“) legt die Kopie am neuen
  Ort an, danach kann `data/browser/` gelöscht werden.
- **Belegt:** 571 Tests grün (neu `test_process_control.py` mit Ersatzprozess,
  Kopie-Ablauf mit Schließen/Wiederöffnen); live mit Wegwerf-Edge geprüft.

## pre-6 — Nachtrag 2026-10-03 (7): Befunde aus der ersten echten Einrichtung

- `setup` wartet am Ende auf Enter, wenn das Konsolenfenster nur ihm gehört
  (Installer/Startmenü); vorher schloss sich das Fenster sofort nach dem letzten
  Schritt, die Zusammenfassung war nicht lesbar. Unerwartete Fehler werden im
  Fenster angezeigt.
- Zeitplanung: Fehlt der Eintrag im globalen State des PyTaskManagers
  (`%LOCALAPPDATA%\PyTaskManager\tasks_sched.json`), fanden `task list`,
  Kurzname und damit `task delete --all`/`uninstall` die Aufgabe nicht mehr,
  obwohl sie lokal und in Windows noch stand (beobachtet: tägliche Aufgabe nur
  noch über die ID erreichbar). Jetzt wird zusätzlich der lokale State
  durchsucht ([docs/TASK_SCHEDULER.md](docs/task_scheduler/TASK_SCHEDULER.md), Abschnitt 6).
- **Belegt:** 566 Tests grün (neu: Warten am Ende, Fehleranzeige, Fallback mit
  Ersatz-Manager und gegen die echte Aufgabenplanung); Installer neu gebaut,
  Smoke-Test 11/11.

## pre-6 — Nachtrag 2026-10-03 (6): Installer getestet, `chatexporter uninstall`

- Neu `chatexporter uninstall [--yes] [--silent]` ([docs/BEFEHLE.md](docs/BEFEHLE.md)):
  im installierten Programm startet er die Deinstallation, aus dem Quellcode
  entfernt er Aufgaben und Registry-Schlüssel; Daten bleiben immer erhalten.
- Behoben: Im gebauten Programm fehlte `win32timezone` (Aufgabe anlegen brach ab).
- Smoke-Test des Builds prüft jetzt einen echten Aufgaben-Durchlauf in einem
  eigenen Testordner der Aufgabenplanung.
- Installer: unbekanntes Flag `foldershortcut` entfernt; kompiliert mit Inno Setup 6.7.3.
- **Belegt:** 562 Tests grün (neu `tests/cli/test_uninstall.py`). Auf dem
  Entwicklungsrechner: Installation, Upgrade, `setup` mit täglicher Aufgabe,
  Lauf einer geplanten Aufgabe (Ergebnis 0), Deinstallation per
  `chatexporter uninstall --silent --yes` (alles entfernt, Home erhalten, PATH
  unverändert); Details in docs/BUILD.md, Abschnitt 5.

## pre-6 — Nachtrag 2026-10-03 (5): gebautes Programm (PyInstaller), Installer-Skript

- Neu `packaging/` (docs/BUILD.md): `build.py` (Build, Smoke-Test,
  Installer, `build_report.json`), `chatexporter.spec`, `entry.py`,
  `installer/chatexporter.iss` (Inno Setup, pro Benutzer).
- Menü im gebauten Programm: Menüpunkte starten `chatexporter.exe` statt `python -m chatexporter`.
- **Belegt:** Build `0.0.0.dev6` (134,9 MB), Smoke-Test 7/7; im gebauten Programm
  `task list`, `export`, `status` im leeren Home sowie `chatgpt browser-setup`
  (Playwright/CDP, 2 `auth`-Anfragen) ok. **Offen:** Installer kompilieren und
  in sauberer Umgebung testen (Inno Setup fehlt auf dem Entwicklungsrechner).

## pre-6 — Nachtrag 2026-10-03 (4): Einrichtung, Vorbereitung der Installation

- Neu `chatexporter setup` ([docs/BEFEHLE.md](docs/BEFEHLE.md)): Konfiguration,
  Browser/ChatGPT-Anmeldung, tägliche Aufgabe – jeder Schritt mit Rückfrage;
  auch Menüpunkt 20.
- Neu `chatexporter chatgpt browser-setup [--neu]`: Browser und Anmeldung
  einrichten oder prüfen, ohne Chats zu laden.
- Neu `chatexporter task delete --all` (alle eigenen Aufgaben, für die Deinstallation).
- Zeitplanung im gebauten Programm: Aufgaben rufen `chatexporter.exe` direkt auf,
  `scheduler_manager.py` wird aus dem Programmordner geladen
  ([docs/TASK_SCHEDULER.md](docs/task_scheduler/TASK_SCHEDULER.md), Abschnitt 2).
- **Belegt:** 558 Tests grün (neu `tests/cli/test_setup.py`, `delete --all`,
  gebautes Programm simuliert in `test_ts_config.py`). Ein echtes gebautes
  Programm gibt es noch nicht (nächster Schritt).

## pre-6 — Nachtrag 2026-10-03 (3): Profilkopie statt Standardprofil, Browser-Labor

- Neue Suchreihenfolge ([docs/providers/CHATGPT.md](docs/providers/CHATGPT.md),
  Abschnitt 2): vorhandene Profilkopie → Kopie eines Edge-/Chrome-Profils mit
  ChatGPT-Cookies anlegen → eigenes leeres Profil → Chrome for Testing. Die direkte
  Verwendung der Standardprofile (bisher Wege 1 und 2) entfällt: ein eingetragenes
  Standardprofil ließ jeden Lauf scheitern, solange der Browser offen war.
- Die Kopie wird nur interaktiv angelegt: Hinweis, Bestätigung, bei offenem
  Browser erneute Prüfung, danach erneute Cookie-Prüfung; Kopie ohne Caches,
  atomar, mit `chatexporter_copy.json`.
- Neu `auth/profiles.py`: Profile aus `Local State`, ChatGPT-Cookie-Status (nur
  Domains und Namen, nie Werte; gesperrte Datei = „unbekannt“), Kopie, vorhandene Kopien.
- `BrowserSetup` meldet jeden Schritt zusätzlich über `trace(ereignis, daten)`.
- Neu (nur Entwicklung) `tools/chatgpt/browser_flow_lab.py`: Erkennung,
  Suchreihenfolge, echter Ablauf mit Haltepunkten; ändert die config.yaml nur mit
  `--persist`.
- **Belegt:** 548 Tests grün (neu `test_browser_profiles.py`, `test_browser_setup.py`
  mit Kopie-Fällen). Live: Erkennung auf dem Entwicklungsrechner (nur lesend) und
  nicht-interaktiver Ablauf im Labor mit Wegwerf-Ablage (Kopie-Wege übersprungen,
  leere Profile ohne Anmeldung geschlossen, 2 `auth`-Anfragen, kein Browser
  übrig). **Nicht live geprüft:** Anlegen einer Kopie und Anmeldung darin.

## pre-6 — Nachtrag 2026-10-03 (2): Entwicklungsmodus

- Neuer Schalter `dev_mode` (oberste Ebene, `CHATEXPORTER_DEV_MODE`), Details in
  [docs/KONFIGURATION.md](docs/KONFIGURATION.md), Abschnitt 8. Er setzt nur
  Grenzwerte (`src/chatexporter/config/dev.py`), die Logik bleibt gleich:
  höchstens 3 Listing-Seiten, nach 5 Konversationsabrufen ein simuliertes HTTP 429
  (wie vom Server, ohne Anfrage), geschätzte Auffüllzeit 5 Minuten, Wartezeit im
  Lauf höchstens 1 Minute, Fortsetzungsaufgabe nach 5 Minuten. Ein gekürztes
  Voll-Listing gilt als Teil-Listing, damit lokal vorhandene Konversationen nicht
  als gelöscht gelten.
- Laufbericht: `dev_mode` im ChatGPT-Bericht; Konsolenzeile `DEV-MODUS AKTIV: …`.
- Vorlage: Beschreibungen von Einstellungen auf oberster Ebene beginnen jetzt mit
  `## ` (vorher fehlte das Leerzeichen).
- **Belegt:** 538 Tests grün, neu `tests/providers/chatgpt/test_dev_mode.py`
  (Seitenbegrenzung, simuliertes Limit wie vom Server, Gesamtablauf mit
  Limit-Stopp und Schätzung, unverändertes Verhalten ohne Schalter, Laden aus der
  config.yaml, Fortsetzung nach 5 Minuten). Nicht live gegen ChatGPT geprüft.

## pre-6 — Nachtrag 2026-10-03: Browser-Suche, automatische Fortsetzung

**Browser und Profil für ChatGPT** ([docs/providers/CHATGPT.md](docs/providers/CHATGPT.md), Abschnitt 2):

- Ohne festes Profil sucht der Provider der Reihe nach: Edge/Chrome mit
  Standardprofil, Edge/Chrome mit eigenem Profil, zuletzt Chrome for Testing
  (Download nur interaktiv und nach Rückfrage, geprüft und atomar entpackt). Je Weg
  wird die ChatGPT-Anmeldung geprüft (interaktiv: Aufforderung zur Anmeldung; sonst
  nächster Weg). Der gewählte Weg wird in die config.yaml eingetragen
  (`ConfigManager.set_many`) und danach direkt verwendet.
- Neu `auth/browsers.py` (Erkennung: Programme, Standardprofile, Version, Profil in
  Benutzung über die gesperrte `lockfile`, freie Ports), `auth/chrome_for_testing.py`,
  `auth/browser_setup.py`; `EdgeCdpSession` steuert jetzt Edge, Chrome und Chrome for
  Testing, prüft den CDP-Port je Browser-Art, startet nie ein Profil, das gerade in
  Benutzung ist, und schließt einen selbst gestarteten Browser im Fehlerfall über
  CDP (`Browser.close`), auch wenn er sich über einen Zwischenprozess neu gestartet hat.
- Die frühere Sperre des Edge-Standardprofils entfällt (ausdrücklich gewünscht).
- Neue Einstellungen `providers.chatgpt.browser.kind`, `.executable`,
  `.allow_download`, `.chrome_for_testing_url`; `edge_executable` bleibt als älterer Name.
- Laufbericht: `sources.chatgpt.detail.browser` mit allen Versuchen und Gründen.

**Automatische Fortsetzung** ([docs/TASK_SCHEDULER.md](docs/task_scheduler/TASK_SCHEDULER.md), Abschnitt 5a):

- Endet ein `update` am Rate-Limit, plant die Bedienschicht eine einmalige Aufgabe
  `fortsetzung-<quelle>` nach dem geschätzten Wiederauffüllen; der nächste Limit-Stopp
  terminiert sie neu, ein vollständiger Lauf entfernt sie.
- Der ChatGPT-Laufbericht meldet dafür `rate_limit.stopped`, `stage`,
  `open_conversations`, `estimated_full_at`.
- Neue Einstellungen `task_scheduler.continuation.enabled`, `.margin_minutes`, `.command`.

**Belegt:** 532 Tests grün (neu u. a. `test_browser_setup.py`, `test_browser_launch.py`,
`test_continuation.py`, ein echter Aufgabenplaner-Test der Fortsetzung). Live ohne
Chat-Abrufe: Suche mit Wegwerf-Profilen (Standardprofile korrekt übersprungen, Edge
und Chrome mit leerem Profil gestartet, ohne Anmeldung erkannt und wieder
geschlossen; 2 `auth`-Anfragen) und fester Entwicklungspfad (Anmeldung ok, 2
`auth`-Anfragen). Dabei gefunden und behoben: Edge startet über einen
Zwischenprozess (Exitcode 0), wodurch ein Test-Browser zunächst offen blieb.
Nicht live geprüft: echter Rate-Limit-Stopp mit Fortsetzung (würde das Kontingent
verbrauchen), Download von Chrome for Testing, Edge-Standardprofil bei geschlossenem Edge.

## pre-6 — Nachtrag 2026-10-02 (2): gemeinsame Konfiguration, Export aller Quellen

**Konfiguration** – eine Stelle für alle Schichten ([docs/KONFIGURATION.md](docs/KONFIGURATION.md)):

- Neue, projektunabhängige Bibliothek **`layered_config`** (`src/layered_config/`,
  [docs/CONFIG_BIBLIOTHEK.md](docs/CONFIG_BIBLIOTHEK.md)) und darauf
  **`chatexporter.config`** mit dem Schema aller Einstellungen. Raw Session Updater,
  ChatGPT-Provider, Exporter, Zeitplanung und Befehlsprotokoll lesen ihre Werte nur
  noch dort; ihre eigenen Kopien von Config-Suche, `.env`- und Umgebungslesen sind entfernt.
- **Vorrang:** Standard < config.yaml < `.env` < Umgebung < CLI-Wert. Neu: globale
  Option `--set SCHLUESSEL=WERT` (mehrfach) und generische Umgebungsnamen
  `CHATEXPORTER__<ABSCHNITT>__<SCHLUESSEL>` für jede Einstellung; die bisherigen
  Kurznamen bleiben.
- **Home** `~/.chat_exporter` (`CHATEXPORTER_HOME`): Standardort von config.yaml,
  `.env`, `data/`, `logs/`. Die Suche ab dem Arbeitsordner gilt nur beim Start aus
  dem Quellcode; das installierte Programm nutzt immer das Home.
- **Fehlende config.yaml** wird als vollständige Vorlage neu angelegt: jede
  Einstellung eine auskommentierte Zeile, Standards echt, sonst erkennbare
  BEISPIEL-Werte. `config.example.yaml` ist genau diese Vorlage.
- **Befehle:** `chatexporter config get|list|set|reset|refresh|path` und
  `chatexporter-config`; Menüpunkte 17–19. `set`/`reset` schreiben in die aktive
  config.yaml, behalten Kommentare, sichern vorher (`.config_backups/`) und stellen
  bei ungültigem Ergebnis den alten Stand wieder her.
- **Registry-Spiegel** (nur schreibend): nach jeder erfolgreich angewendeten
  Konfiguration nach `HKCU\Software\ChatExporter\config\Current`.
- **Geänderte Standards:** `storage.data_root` ist jetzt `data` (vorher kein
  Standard), `logging.dir` ist `logs` neben der config.yaml (vorher
  `<runtime_root>/logs`). Die workspace-Konfiguration setzt beides ausdrücklich
  und ist nicht betroffen. `runtime_root` ist für Updater und ChatGPT einheitlich
  `<data_root>/runtime`.

**Export aller Quellen:**

- Neue Adapter für OpenCode, Codex und Claude Code (`exporter/sources/`);
  `exporter.sources` umfasst standardmäßig alle vier Quellen. Exportiert werden die
  Texte von Benutzer und Assistent; Denkinhalte, Werkzeugaufrufe, Nebenzweige und
  Unteragenten nicht.
- Neue Befehle `chatexporter export json` und `chatexporter export md` (auch `all`).
- **Neue Ablage:** `exports/<format>/<quelle>/<JJJJ-MM>/<id>`. Die Dateien der
  bisherigen Ablage `exports/<format>/<JJJJ-MM>/` werden nicht mehr geschrieben und
  nicht gelöscht; sie sind abgeleitet und können entfernt werden.
- Markdown zeigt jetzt die Quelle und, wo vorhanden, Projekt/Arbeitsordner;
  Archiv-/Stern-Status nur bei Quellen, die ihn kennen.
- In `workspace/config.yaml` wurde `exporter.sources` per `chatexporter config set`
  auf alle vier Quellen gesetzt (Sicherung unter `.config_backups/`).

**Belegt:** 484 Tests grün (neu u. a. `tests/layered_config/`, `tests/config/`,
`tests/exporter/test_exporter_all_sources.py`). Export gegen den Realbestand:
OpenCode, Codex und Claude zusammen 277 Sitzungen ohne Fehler. `config set` gegen
die echte workspace-Konfiguration: Kommentar der Zeile blieb erhalten, Sicherung
angelegt, Registry-Spiegel mit 71 Werten geschrieben. Nicht umgesetzt: die
Browser-Erkennung (Edge/Chrome/Download), siehe [docs/ROADMAP.md](docs/ROADMAP.md).

## pre-6 — Nachtrag 2026-10-02: Exporter als eigene Schicht, übernommene Dokumentation

Die Exporte (Markdown, JSON) gehören nicht zum ChatGPT-Provider. Sie sind eine
eigenständige Schicht **`chatexporter.exporter`** und beginnen dort, wo die
Verantwortung von Raw Session Updater und Providern endet: Sie lesen den Raw
Storage und schreiben nur nach `exports/`.

- **Neu:** `chatexporter export` und `chatexporter-export` (`--format`, `--source`,
  `--export-root`, `--raw-root`), Menüpunkt 10, Konfigurationsabschnitt `exporter`
  (`root`, `formats`, `sources`), Umgebungsvariablen `CHATEXPORTER_EXPORT_ROOT`,
  `_EXPORT_FORMATS`, `_EXPORT_SOURCES`. `export` ist ein planbarer Befehl der Zeitplanung.
  Der Exporter importiert nichts aus anderen Schichten (Test ergänzt) und hat eigene
  Kopien von Config-Suche, Schreibhilfen und der Aufbereitung der ChatGPT-Konversation
  (`exporter/sources/chatgpt.py`; weitere Quellen kommen als Adapter hinzu).
- **Entfernt aus dem ChatGPT-Provider:** `export/`, `transform/`, die Processor-
  Schnittstelle im Sync, `chatexporter-chatgpt export`, `--export-root`, `--no-exports`
  (auch beim Raw Session Updater), `providers.chatgpt.export` samt `CHATEXPORTER_PROCESSORS`
  und das Feld `processor_failures`.
- **Verhaltensänderung:** Ein Update erzeugt keine Exporte mehr. Sie entstehen mit
  `chatexporter export` oder als eigene geplante Aufgabe.
- **Config-Migration:** In `workspace/config.yaml` wurde `providers.chatgpt.export`
  durch den Abschnitt `exporter` ersetzt (Sicherung `config.yaml.bak-2026-10-02`).
- **Dateiformat:** Die JSON-Ansicht enthält zusätzlich das Feld `source`
  (`chatgpt`); sonst sind Markdown und JSON gleich geblieben.
- **Belegt:** Gegen den Realbestand (3099 Konversationen, 6198 Dateien, 0 Fehler)
  stimmen alle Markdown-Dateien mit den früheren Exporten überein, bis auf fünf
  Konversationen, deren Rohdaten nach dem letzten Export neu geladen wurden; die
  JSON-Dateien stimmen bis auf das neue Feld überein.
- **Tests:** 409 grün (davon 38 für den Exporter, 3 für die Beispiel-Konfiguration).
- **Doku:** ARCHITEKTUR (Exporter-Schicht, Kernprinzipien), BEFEHLE, KONFIGURATION,
  ABLAGE, CHATGPT, PROVIDER_VERTRAG, MIGRATION_PRE5, TASK_SCHEDULER nachgezogen.
  Aus pre-5 übernommen und angepasst: `GETTING_STARTED.md`, `DEVELOPMENT_WORKSPACE.md`,
  `ROADMAP.md` (jetzt mit Planung des Deployments per Inno Setup, als Planung
  gekennzeichnet), `LIVE_TEST_CHECKLIST.md`, `PROJECT_INVENTORY.md`; Berichte,
  frühere Checklisten, Bauplan und Roadmap unverändert (mit Hinweis) unter `docs/historie/`.
  Neu: `config.example.yaml` und `.env.example` als Vorlagen.

## pre-6 — Nachtrag 2026-10-01: Zeitplanung (Task Scheduler)

Neues, eigenständiges Modul `chatexporter.task_scheduler`: ChatExporter-Befehle
laufen automatisch, z. B. täglich `update`, als Aufgaben der Windows-
Aufgabenplanung. Die Windows-Seite liefert das vorhandene Script
`tools/task_scheduler/scheduler_manager.py` (PyTaskManager V2), das unverändert
per Dateipfad geladen wird. Doku: [docs/TASK_SCHEDULER.md](docs/task_scheduler/TASK_SCHEDULER.md)
(mit Kopie der Script-README unter `docs/task_scheduler/`).

- **Befehle:** `chatexporter task create | get | list | update | delete | pause | resume`,
  zusätzlich Einzelbefehl `chatexporter-task` (protokolliert) und Menüpunkte 12–16.
  `update` ist neu gegenüber dem Script: der Plan wird im State gespeichert und
  die Aufgabe daraus mit gleicher ID neu aufgebaut.
- **Konfiguration:** neuer Abschnitt `task_scheduler` (`folder`, `owner`,
  `state_file`, `global_state_file`, `python`, `manager_script`, `defaults.*`),
  Umgebungsvariablen `CHATEXPORTER_TASK_*`, Optionen `--folder`, `--owner`,
  `--state-file`, `--global-state-file`, `--python`, `--json`. In
  `workspace/config.yaml` eingetragen.
- **Einrichtung:** `pywin32` ist optionale Abhängigkeit
  (`pip install -e .[scheduler]`) und in der workspace-venv installiert.
- **Unabhängigkeit:** `task_scheduler` importiert nichts aus Raw Session
  Updater oder Providern (Test ergänzt; die Paketwurzel darf nun auch
  `task_scheduler` enthalten).
- **Tests:** 91 neue (config, Dienst gegen Ersatz-PyTaskManager, CLI,
  echte Windows-Aufgaben in einem Testordner, Menü/Einzelbefehl); gesamt
  368 Tests grün. Der geplante Befehl wurde real gestartet (`status`,
  Exitcode 0, im Befehlsprotokoll). Nicht getestet: `--startup`
  (Administratorrechte) und ein unbeaufsichtigter ChatGPT-Lauf.
- **Beobachtung:** In einem ersten Lauf von `test_the_scheduled_command_really_runs`
  fehlte nach 90 s das Ergebnis des geplanten Befehls; in neun Wiederholungen
  trat das nicht mehr auf, die Ursache ist ungeklärt. Die Testmeldung
  enthält jetzt den Zustand der Aufgabe.

## pre-6 — Nachtrag 2026-10-01: Umbenennung zu „Raw Session Updater“

Die Schicht über den Quellen heißt durchgängig **Raw Session Updater**. Der
zuvor verwendete Name kollidierte mit bestehenden Ordnernamen im Projekt und
auf dem System und wurde überall ersetzt (Code, Tests, Doku, Config).

- Paket `chatexporter.raw_session_updater` (Ordner `src/chatexporter/raw_session_updater/`),
  Klasse `RawSessionUpdaterConfig`, Funktion `load_updater_config`.
- Config-Abschnitt `raw_session_updater:` (Schlüssel `sources`), siehe
  [docs/KONFIGURATION.md](docs/KONFIGURATION.md). Eine bestehende
  `config.yaml` muss den Abschnitt entsprechend umbenennen; ohne ihn sind alle
  vier Quellen aktiv.
- Tests unter `tests/raw_session_updater/`; Menü- und Hilfetexte angepasst
  („Alle Quellen aktualisieren/prüfen“, Übersichtstitel „Updater-Übersicht“).
- Unverändert bleiben ChatGPT-Begriffe zum Archiv-Status einer Konversation
  (`is_archived`, `archived`) und der Importtyp `openai_account_data_archive`.
- Verifiziert: 277 Tests grün; `chatexporter check --source codex` und
  `chatexporter --help` laufen mit der umgestellten `workspace/config.yaml`.

## pre-6 — Nachtrag 2026-10-01: Befehlsprotokoll

- **Neu: `cli/command_log.py`.** Jeder Befehl (Menüpunkt, `chatexporter …`,
  alle Einzelbefehle) wird als JSON-Zeile protokolliert. Felder:
  - Zeitpunkt, Ende, Dauer, Befehl/argv, Exitcode (Strg+C = 130)
  - Arbeitsordner, Config, Programmstand
  - `summary`: Gesamtwerte und je Quelle die Angaben der
    Konsolen-Zusammenfassung; beim Update aus dem Laufbericht
- **Config:** `logging.enabled`, `logging.dir` (Default
  `<runtime_root>/logs`), `logging.rotation` (Default `24h`, eine Datei je
  UTC-ausgerichtetem Zeitraum) und `logging.retention` (Default `30d`,
  `0` = nie löschen). Dauerangaben wie `30m`, `24h`, `7d`, `1d12h`.
  Umgebungsvariablen `CHATEXPORTER_LOG_*`.
- **Einstiege:** Die Einzelbefehle `chatexporter-update|index|check|cleanup|status`
  laufen jetzt über `chatexporter.cli.main` (Neuinstallation nötig).
- Ein Fehler im Protokoll bricht nie den Befehl ab (Hinweis auf stderr).
- Tests: **277 grün**. Live, nur lesend: `chatexporter check --source codex`
  schrieb den Datensatz nach `data/runtime/logs/commands_20261001T0000Z.jsonl`.

## pre-6 — Nachtrag 2026-10-01: `out_of_order_change` durch nachziehendes Listing

- **Befund aus Lauf `sync_20261001T010708Z`** (erstmals mit aktuellem Code):
  6 Einträge eingestuft als `content`. Davon waren 5 echte Änderungen auf
  Position 1–5; der ausgeschlossene Chat stand auf Position 42 und wurde
  korrekt ignoriert. Auf Position 100 stand `6a83f3cb…` mit
  `update_time` remote `…29.833364` gegenüber lokal `…29.791121`.
- **Ursache, belegt ohne Anfrage:** Die Detailantwort vom 20.09. hatte bereits
  `…29.833364`. Das Listing führte damals `…29.791121` und hat nun
  nachgezogen. Eine Auswertung aller Envelopes ergab, dass bei **575 von
  3098** Chats die Listing-Zeit beim Abruf vor der Detailzeit lag, nie danach.
- **Korrektur:** `update_time_changed()`: Ein Chat gilt nur als geändert,
  wenn die Listing-Zeit **neuer** ist als Listing- **und** Detailzeit des
  gespeicherten Stands. Neues Indexfeld `raw_update_time` (Pflichtfeld; ein
  älterer Index baut sich selbst neu). Gilt für Grenzbestimmung und Planung.
- **Nachweis:** Offline-Replay des echten Listings aus dem Laufbericht gegen
  den echten Bestand bestätigt die Grenze; erkannt werden genau die 5 echten
  Änderungen, kein Wechsel auf `full`. Danach ChatGPT-Index lokal neu gebaut
  (3098/3098 mit `raw_update_time`) und Prüfung ohne Fehler und Warnungen.
- Strg+C: zusätzlich die Meldung „Task was destroyed but it is pending!“
  (offene Playwright-Anfrage) gezielt unterdrückt.
- Tests: **255 grün**.

## pre-6 — Nachtrag 2026-10-01: Lauf `sync_20261001T003751Z` lief mit veraltetem Code

- **Befund, belegt:** Beide Läufe vom 30.09./01.10. liefen **nicht** mit dem
  korrigierten Code.
  - `chatexporter` löste in PowerShell auf
    `Python312\Scripts\chatexporter.exe` auf, eine feste Kopie von pre-6 im
    globalen Python (installiert 2026-10-01 00:16, vor den Korrekturen um
    00:33–00:35).
  - Der Laufbericht enthält entsprechend weder `items` noch `started_at`;
    OpenCode zählte 48 statt 54 Sitzungen.
  - Zusätzlich wählte die Config-Suche beim Start aus `pre-5/` dessen alte
    `config.yaml`.
- **Config-Suche:** Überspringt `config.yaml` in Codeordnern
  (`src/chatexporter`), in Raw Session Updater und ChatGPT-Provider.
- **Programmstand sichtbar:** Menükopf, `chatexporter-update` und
  `chatexporter-chatgpt update` zeigen Version, Codeordner, Python und Config.
  Läuft eine feste Kopie in `site-packages`, erscheint eine Warnung.
- **Menü:** Jeder Punkt läuft als eigener Prozess, also immer mit aktuellem
  Code; Strg+C beendet nur den Lauf.
- Tests: **253 grün**.

## pre-6 — Nachtrag 2026-10-01: Fehleranalyse Lauf `sync_20260930T221808Z`

Befund des ersten Live-Laufs (Konsole und Laufbericht) und Korrekturen:

- **ChatGPT, `auto` wechselte unnötig auf `full` (`out_of_order_change`).**
  - Ursache (sehr wahrscheinlich): Der manuell ausgeschlossene Chat
    `6aa4942f…` ist lokal nie vorhanden, galt daher bei jedem Lauf als „neu“
    und steht unter den zuletzt geänderten hinter der Grenze.
  - Belege: Der Bestand war laut Laufbericht vom 29.09., 16:32, sonst
    vollständig synchron (3098 unverändert, 1 ausgeschlossen), und keiner der
    100 zuletzt geänderten lokalen Einträge hat ein abweichendes Zeitformat.
  - Nicht direkt belegbar: Der Abbruch verwarf die Diagnose (siehe unten).
  - Korrektur: Ausgeschlossene und quarantänisierte Chats werden als
    `ignored` eingestuft und bilden oder verletzen die Grenze nicht mehr.
- **Härtung Zeitvergleich:** `update_time`/`pinned_time` werden als Zeitpunkt
  statt als Text verglichen, in Grenzbestimmung **und** Planung
  (`envelope.same_time`, `signature_changed`). Im Bestand stehen 198 Einträge
  ohne Nachkommastellen.
- **Diagnose bleibt erhalten:** Beim Wechsel auf `full` wird das
  `recent`-Ergebnis sofort gesichert (`full_completed: false` bis zum Ende).
  Neu sind `listing.entries` (Position, Einstufung, Zeiten je Eintrag),
  außerdem nennt die Konsole die verletzenden Chats.
- **OpenCode: alle 48 Sessions gescheitert.** Ursache belegt, read-only
  geprüft: Neuere OpenCode-Versionen (1.18.32) führen Sitzungen in
  `session_v2`; die alte Tabelle `session` hatte 48 statt 54 Einträge und
  veraltete Zeitstempel. Zudem steht das Verzeichnis im Export unter
  `info.location.directory` in Windows-Schreibweise. Korrektur: `session_v2`
  bevorzugt, Verzeichnis normalisiert verglichen. Nachweis: 54 von 54
  Sessions bestehen die Exportprüfung; Probelauf ohne Fehler.
- **Laufbericht je Quelle nachvollziehbar:** `started_at`, `finished_at`,
  `duration_seconds` und `items` (`fetched`/`failed`, bei ChatGPT zusätzlich
  `files`) je Quelle, geliefert von allen vier Providern. Die Konsole zeigt je
  Quelle eine Zusammenfassung mit den gespeicherten Einträgen.
- **Strg+C einheitlich:** Auch bei OpenCode, Codex und Claude beendet
  Strg+C nur die laufende Quelle. Bisher ging dabei der gesamte Laufbericht
  verloren. Die harmlose Meldung „Future exception was never retrieved
  (TargetClosedError)“ nach einem Abbruch wird gezielt unterdrückt.
- Tests: **250 grün** (neu: `test_opencode_provider.py`,
  `test_edge_close_filter.py`, Ausschluss/Zeitformat/Diagnose/Abbruch im
  Listing, Strg+C im Raw Session Updater).

## pre-6 — Nachtrag 2026-09-30: Grenzprüfung auf Turn-Ebene + Anfragezählung

Details: [docs/providers/CHATGPT.md](docs/providers/CHATGPT.md), Abschnitte 4.3 und 4.4.

- **Grenzprüfung ersetzt die feste Stichprobe** (`verify_unchanged_sample`
  entfällt). Die Chats an der Änderungsgrenze werden per Detailabruf auf
  Turn-Ebene geprüft (letzter Knoten, Knoten-IDs, `update_time`), bis
  `recent_confirm_unchanged` (3) **in Folge** unverändert sind. Jede Abweichung
  wird sofort aus der schon geladenen Antwort gespeichert (kein zweiter
  Abruf), setzt die Folge zurück und hängt den nächsten Chat an. Normalfall:
  genau 3 Detailabrufe.
  - Neue Schlüssel: `sync.verify_boundary` (Default an) und
    `sync.verify_max_requests` (Default 0 = unbegrenzt).
  - Laufbericht: `verification` (`checked`, `mismatches`, `consecutive_ok`,
    `confirmed`, `requests`, `stopped`, `checked_ids`) sowie
    `stats.verify_requests`.
- **Anfragezählung:** Jede an ChatGPT gesendete Anfrage wird je Kategorie
  gezählt. Das umfasst Anmeldung, Listing, Konversation, Canvas,
  Datei-Metadaten, Download-Ticket und Dateiinhalt; Fehlschläge zählen mit,
  HTTP 429 wird getrennt geführt.
  - Ablage im Laufbericht: `requests` und `stats.requests_total`, außerdem
    `totals.requests_total` im Updater- und Einzellauf-Bericht. Die Summe
    erscheint auch in der Übersicht und in der Konsole.
  - Zählstellen: `ApiClient` (zentral) und `AuthBroker`.
- `ConversationFetcher.build()`: Aufbereitung aus einer bereits geladenen
  Detailantwort.
- `workspace/config.yaml` auf die neuen Schlüssel umgestellt.
- Tests: Grenzprüfung (Normalfall, Abweichung verlängert, Folge nötig,
  Obergrenze, abschaltbar) und `test_request_counting.py`; Vollsuite
  **236 grün**. Live-Lauf: offen.

## pre-6 — Nachtrag 2026-09-30: Listing-Modus `auto` + Härtung der Änderungsgrenze

Verhalten (Details: [docs/providers/CHATGPT.md](docs/providers/CHATGPT.md), Abschnitt 4):

- **Neuer Modus `auto` als Standard** (`sync.listing_mode`, `--listing-mode`).
  Ohne lokalen Bestand erfolgt ein Erstabruf `full`. Sonst läuft `recent`,
  und wenn dessen Änderungsgrenze nicht bestätigt ist, im selben Lauf `full`
  (`detail.listing.escalation`). Vorher geprüft: `recent` erfüllte das nicht.
  Er wechselte nie auf `full` und erkannte keinen Erstabruf.
- `recent` bleibt als ausdrücklich sparsamer Modus erhalten und wechselt nie
  selbst.
- **Grenze präziser:** Einstufung `new`/`content`/`meta`/`same`. Nur
  `update_time` bestimmt die Grenze; reine Metadaten-Änderungen werden
  geladen, verschieben sie aber nicht.
- **Grenze bestätigt statt angenommen:** mindestens `recent_confirm_unchanged`
  (3) unveränderte Einträge ab der Grenze, kein `new`/`content` hinter der
  Grenze, absteigende Sortierung, Querprobe mit lokal neueren aktiven Chats.
  Gründe bei Nichtbestätigung: `cap_reached`, `out_of_order_change`,
  `order_violation`, `recent_local_missing`.
- **Stichprobe auf Turn-Ebene** (abgelöst durch die Grenzprüfung, siehe oben): je Lauf `verify_unchanged_sample` (2)
  unveränderte Chats direkt hinter der Grenze per Detailabruf
  (aktueller Knoten, Knoten-IDs, `update_time`). Bei Abweichung wird der Chat
  sofort neu geladen und `verify_mismatches` gezählt.
- Menü: Punkt 1 = Update laut Config (`auto`), Punkt 2 = ChatGPT vollständig,
  Punkt 3 für ChatGPT mit Auswahl auto/recent/full.
- `workspace/config.yaml`: `listing_mode: auto` sowie die zwei neuen Schlüssel
  eingetragen.
- Tests: `tests/providers/chatgpt/test_listing_recent.py` neu gefasst;
  Vollsuite **221 grün**. Live-Lauf: offen.

## pre-6 — 2026-09-30 (Workspace-Stand, nicht promotet)

Umstrukturierung vom ChatGPT-Exporter zum **Raw Session Updater über mehrere
Quellen**. Das Fachverhalten der Quellen und das Datenformat bleiben gleich.
Details zum Umstieg: docs/MIGRATION_PRE5.md.

### Struktur

- Drei Schichten: Bedienschicht `chatexporter.cli`, Raw Session Updater
  `chatexporter.raw_session_updater` (früher „Wrapper“), Provider
  `chatexporter.providers.*`.
- Die gesamte ChatGPT-Logik liegt jetzt als Paket unter
  `providers/chatgpt/`, gleichrangig neben `opencode`, `codex` und `claude`.
- Raw Session Updater und Provider sind voneinander unabhängig. Gemeinsam benötigte Logik
  existiert bewusst in beiden; der Gleichlauf ist per Test abgesichert.
  `tests/test_independence.py` prüft die Importregeln.
- Der Codeordner enthält nur noch Code und Doku. Konfiguration, `.env` und
  Daten kommen aus dem übergeordneten `workspace/`
  (Config-Suche: `--config` > `CHATEXPORTER_CONFIG` > Aufstieg ab
  Arbeitsordner).

### Bedienung

- Menü: `chatexporter` ohne Argumente.
- Installierbare Einzelbefehle (`pyproject.toml`): `chatexporter-update`,
  `-index`, `-check`, `-cleanup`, `-status`, `-chatgpt`, `-opencode`,
  `-codex`, `-claude`.
- `raw_session_updater.sources` in der config.yaml ersetzt die Code-Konstante
  `PROVIDERS`; `chatexporter-update --source <quelle>` wählt einzelne Quellen.
- Store-Mutationstests als `chatexporter-chatgpt scenarios`. Die
  Forschungssonden liegen unter `tools/chatgpt/`.
- Die PowerShell-Skripte aus pre-5 entfallen.

### Provider-Vertrag

- ChatGPT erfüllt den Vertrag jetzt wie die anderen Provider: Er nimmt das
  Vertrags-Mapping des Raw Session Updaters an und liefert ein Vertragsergebnis
  (`contract_result`). Die Übersetzung der Kennzahlen (früher
  `wrapper.map_chatgpt_stats`) liegt beim Provider.
- ChatGPT-Einzellauf (`chatexporter-chatgpt update`) schreibt weiterhin einen
  Laufbericht Schema 4.

### Konfiguration

- ChatGPT versteht jetzt `storage.data_root`. Daraus ergeben sich die
  Defaults für `raw_storage/`, `runtime/`, `exports/` und `user_data/`.
- ChatGPT-Sektionen dürfen unter `providers.chatgpt.{browser,api,sync,export}`
  stehen; die Top-Level-Sektionen gelten weiter.
- Neue Umgebungsvariablen: `CHATEXPORTER_CONFIG`, `CHATEXPORTER_DATA_ROOT`,
  `CHATEXPORTER_SOURCES`.

### Fehlerbehebungen

- `verify_store` legte bei leerem Bestand `raw_storage/library/` an, weil es
  das Layout anders erkannte als `resolve_store_layout`. Die Regel ist jetzt
  einheitlich (Test `test_health_check_on_fresh_store_creates_no_stray_folders`).
- Doppelt definierte Konstanten in `sync/orchestrator.py` entfernt.

### Übernommen aus dem Hardening nach pre-5

- Listing-Modus `recent` (`order=updated`, Stopp an der Änderungsgrenze,
  Deckel `recent_max_pages`). Einzelheiten: [docs/providers/CHATGPT.md](docs/providers/CHATGPT.md).

### Nachweise

- Tests: **209 grün** (`python -m pytest`, Python 3.12.10, 2026-09-30).
- Paket: Wheel offline gebaut (setuptools 83). Es enthält `raw_session_updater`, `cli`,
  `providers` und die 10 Befehle, dagegen keine Tests, Tools oder Configs.
- Live, nur lesend: `chatexporter check` gegen `workspace/config.yaml` und den
  echten Bestand. Die Config wurde automatisch gefunden, alle vier Quellen
  `ok`, ChatGPT mit 0 Fehlern und 0 Warnungen.

### Inbetriebnahme (2026-09-30)

- `workspace/.venv` auf pre-6 umgestellt (`pip install -e`; ersetzt dev4).
  Alle 10 Befehle sind installiert, `chatexporter-check` ist ok.
- `workspace/config.yaml` angepasst und nach der Projektstruktur neu
  gegliedert (ChatGPT unter `providers.chatgpt`). Alle aufgelösten Werte sind
  identisch zur vorherigen Fassung (Backup `config.yaml.bak-2026-09-30`).

### Offen

- Live-Lauf eines Updates, insbesondere im Modus `recent`.
