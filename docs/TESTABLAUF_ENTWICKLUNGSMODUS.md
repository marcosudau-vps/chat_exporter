# Testablauf im Entwicklungsmodus – Gesamtablauf mit wenigen Anfragen

**Art:** Testablauf (Checkliste), kein Prüfbericht. Ein Schritt gilt erst als
bestanden, wenn sein Ergebnis mit Beleg protokolliert ist (Konsolenausgabe,
Laufbericht), in einer Arbeitsakte unter
`workspace/_dokumentation/60_ARBEITSDOKUMENTATION/<Datum>_testablauf_dev/`.
Keine Zugangsdaten protokollieren.

**Ziel:** der ganze Weg mit echtem ChatGPT, aber begrenzt.

**Teil A** (Schritte 1–6):
1. neues Browserprofil mit automatischer Anmeldung,
2. neuer Storage, Erstabruf auf 5 Listing-Seiten begrenzt,
3. unveränderter Folgelauf,
4. Chats **nur lokal im Storage** löschen (nie auf der Webseite),
5. `update` lädt genau diese neu, ohne erneute Anmeldung und mit demselben Profil,
6. Kontrolllauf.

**Teil B** (Schritt 7): ein geplanter, unbeaufsichtigter Lauf mit einem weiteren
neuen Profil; die automatische Anmeldung klappt ohne Interaktion.

**Teil C** (Schritt 8): Profilkopie mit geöffnetem echtem Browser. Er wird
geschlossen und samt Tabs wieder geöffnet; das gilt für Edge und, falls
vorhanden, für Chrome.

Alles läuft mit einer **eigenen Test-Konfiguration** unter `workspace/_testlauf/`:
eigener Storage, eigene Browserprofile, eigener Port. Dein echter Bestand
(`workspace/data`), dein normales Browserprofil und `workspace/config.yaml`
bleiben unberührt. Eine geplante Aufgabe übernimmt die Test-Konfiguration von
selbst (`--config`).

**Umfang** (5 Seiten zu je 5 Einträgen):
- je Bereich (aktiv, archiviert) höchstens 25 Konversationen;
- Erstabruf: höchstens rund 10 Listing-Anfragen, bis zu 50 Konversationsabrufe
  plus Canvas-Dokumente und Dateien;
- Folgeläufe: wenige Anfragen.

Kleiner geht es mit `listing_limit: 2`; Dateien lassen sich mit
`update --no-files` auslassen.

## Automatisch: Gesamttest-Skript (empfohlen)

Ein Befehl führt Teil A, Teil B und die Zusatzfälle aus und prüft jedes Ergebnis
selbst. Teil C ist interaktiv und läuft nur mit `--teil-c`. Im Ordner `workspace`:

```powershell
.\.venv\Scripts\python.exe ChatExporter_Gen4_pre-6\tools\chatgpt\live_testablauf.py --teil-c
```

- Die Test-Konfiguration legt das Skript selbst an, unter
  `_testlauf\<Zeitpunkt>\`.
- Jede Prüfung erscheint als `OK`, `FEHLER` oder `HINWEIS`.
- Außerdem prüft es, dass kein Zugangsdatum aus der `.env` in einer Ausgabe oder
  Storage-Datei auftaucht. Die Werte werden nur im Speicher verglichen.
- Am Ende räumt es auf: Test-Browser, Aufgabe, Testordner, Registry-Eintrag des
  Test-Storages; den Registry-Spiegel deiner echten Konfiguration stellt es aus
  einer Sicherung wieder her. Mit `--behalten` bleibt der Testordner stehen, mit
  `--nur-a` läuft nur Teil A.
- Bericht: `workspace\_dokumentation\60_ARBEITSDOKUMENTATION\<Datum>_testablauf_dev_<Uhrzeit>\BERICHT.md`,
  mit den Ausgaben je Befehl (Zugangsdaten darin verdeckt).
- Exitcode 0, wenn keine Prüfung `FEHLER` meldet.

Die folgenden Abschnitte beschreiben denselben Ablauf von Hand.

## 0. Vorbereitung

Im Ordner `workspace`, in einem PowerShell-Fenster. Die venv zeigt auf
`ChatExporter_Gen4_pre-6`; prüfen:

```powershell
.\.venv\Scripts\python.exe -c "import chatexporter; print(chatexporter.__file__)"
```

Erwartung: Der Pfad endet auf `ChatExporter_Gen4_pre-6\src\chatexporter\__init__.py`.

Der Ordner `_testlauf` darf noch nicht existieren:

```powershell
Test-Path "$PWD\_testlauf"
```

Erwartung: `False`.

Test-Konfiguration anlegen:
- Die Zugangsdaten kommen aus `workspace\.env` (`CHATGPT_USERNAME`,
  `CHATGPT_PASSWORD`, `CHATGPT_2FA_SECRET` oder `CHATGPT_2FA_REFERENCE`).
- Die automatische Fortsetzung ist aus. Eine Fortsetzung würde sonst später einen
  weiteren Lauf auslösen.

```powershell
$t = "$PWD\_testlauf"
New-Item -ItemType Directory $t | Out-Null
@"
dev_mode: true
dev:
  listing_max_pages: 5
  conversation_fetches: 0
bootstrap:
  env_file: '$PWD\.env'
storage:
  root: '$t\storage'
raw_session_updater:
  sources: [chatgpt]
task_scheduler:
  continuation:
    enabled: false
providers:
  chatgpt:
    browser:
      user_data_dir: '$t\profil'
      cdp_port: 9333
      leave_browser_running: false
    sync:
      listing_limit: 5
"@ | Set-Content -Encoding UTF8 "$t\config.yaml"
$env:CHATEXPORTER_CONFIG = "$t\config.yaml"
```

Wird später ein neues Fenster gebraucht, nur `$t = "$PWD\_testlauf"` und die
letzte Zeile erneut ausführen. Prüfen:

```powershell
.\.venv\Scripts\chatexporter.exe config get dev.listing_max_pages
```

Erwartung: `5` mit Herkunft `config`.

## 1. Neues Profil – automatische Anmeldung

```powershell
.\.venv\Scripts\chatexporter.exe chatgpt login
```

Variante zum Mitschauen: `chatgpt login --schrittweise`.

Erwartung:
- [ ] Zeile `Keine gueltige ChatGPT-Sitzung – automatische Anmeldung ...`, dann
  Anmeldedialog, E-Mail, Passwort, Einmalcode (**einmal**), `Automatische
  Anmeldung erfolgreich.`
- [ ] JSON: `"ok": true`, `"already_logged_in": false`, `steps` mit
  `login_button, email, … password, mfa, … chatgpt`, `pages` nur `chatgpt.com/…`
  und `auth.openai.com/…`.
- [ ] Das Browserfenster bleibt unsichtbar (außerhalb des Bildschirms). Es gibt
  kein Fenster „Wir synchronisieren Ihre Daten …“ und keine fremden Tabs.
- [ ] Der Storage ist angelegt:

```powershell
.\.venv\Scripts\chatexporter.exe storage show
```

  Erwartung: Format `storage-schema-2`, eine ID. Die ID notieren, sie wird beim
  Aufräumen gebraucht.

## 2. Speicher füllen – Erstabruf (5 Seiten)

```powershell
.\.venv\Scripts\chatexporter.exe update
```

Erwartung:
- [ ] Zeile `DEV-MODUS AKTIV: hoechstens 5 Listing-Seiten je Bereich, ohne
  simuliertes Rate-Limit, …`.
- [ ] `Browser: Microsoft Edge (konfiguriertes Profil) – …\_testlauf\profil`.
- [ ] **Keine** Zeile `automatische Anmeldung`: Die Sitzung aus Schritt 1 gilt.
- [ ] `Listing-Modus auto: kein lokaler Bestand -> Erstabruf (full).`, danach
  höchstens 25 aktive und höchstens 25 archivierte Konversationen gefunden; alle
  geladen; Exitcode 0.
- [ ] `storage show`: `storage.update_counter = 1`, `update_last_result = ok`.
- [ ] Laufbericht `_testlauf\storage\.storage\runs\sync_*.json`: unter
  `sources.chatgpt.detail.listing` steht `"escalation": "initial"`; dazu
  `dev_mode: true`.

## 3. Folgelauf ohne Änderung

```powershell
.\.venv\Scripts\chatexporter.exe update
```

Erwartung:
- [ ] Keine Anmeldung.
- [ ] `Listing-Modus` bleibt bei `recent`, die Änderungsgrenze ist bestätigt.
- [ ] Keine Konversation wird neu geladen. Die Grenzprüfung liest zur Bestätigung
  nur wenige Konversationen (`verify_boundary`).

## 4. Chats nur lokal löschen

Zuerst anzeigen, welche Chats gelöscht würden (neuester, mittlerer, ältester):

```powershell
.\.venv\Scripts\python.exe ChatExporter_Gen4_pre-6\tools\chatgpt\local_delete_probe.py --storage $t\storage
```

Dann wirklich löschen:

```powershell
.\.venv\Scripts\python.exe ChatExporter_Gen4_pre-6\tools\chatgpt\local_delete_probe.py --storage $t\storage --ausfuehren
```

- [ ] Die drei IDs notieren. Das Werkzeug löscht nur Dateien unter
  `_testlauf\storage\raw_storage\chatgpt\`. Storages mit mehr als 200
  Konversationen verweigert es.

## 5. Update nach dem lokalen Löschen

```powershell
.\.venv\Scripts\chatexporter.exe update
```

Erwartung:
- [ ] `Listing-Modus auto: 3 Conversation(s) fehlen lokal (Dateien geloescht) ->
  full, damit sie neu geladen werden.`
- [ ] Es werden **genau die drei** notierten Konversationen geladen, auch der
  älteste Chat, der hinter der Änderungsgrenze liegt.
- [ ] **Keine** Zeile `automatische Anmeldung`. Dasselbe Profil wie zuvor wird
  verwendet (`…\_testlauf\profil`).
- [ ] Laufbericht: `sources.chatgpt.detail.listing.escalation =
  "local_files_missing"`, `local_missing` mit den drei IDs.
- [ ] Die Datei `_testlauf\storage\.storage\status_registry\lost_conversations.json`
  gibt es danach nicht mehr:

```powershell
Test-Path $t\storage\.storage\status_registry\lost_conversations.json
```

  Erwartung: `False`.
- [ ] Prüfung ohne Fehler:

```powershell
.\.venv\Scripts\chatexporter.exe check
```

## 6. Kontrolllauf

```powershell
.\.venv\Scripts\chatexporter.exe update
```

- [ ] Wieder `recent`, nichts neu geladen, keine Anmeldung.

## 7. Teil B – geplanter, unbeaufsichtigter Lauf mit automatischer Anmeldung

Damit der geplante Lauf die automatische Anmeldung braucht, bekommt er ein
**weiteres neues** Profil. `config-global set` schreibt in die Test-Konfiguration:

```powershell
.\.venv\Scripts\chatexporter.exe config-global set providers.chatgpt.browser.user_data_dir "$t\profil_geplant"
```

```powershell
.\.venv\Scripts\chatexporter.exe config-global set providers.chatgpt.browser.cdp_port 9334
```

Der eigene Port und `leave_browser_running: false` stellen sicher, dass sich der
Lauf nicht mit einem noch offenen Test-Browser des ersten Profils verbindet.

Aufgabe in 3 Minuten anlegen. Sie erhält `--config` (Test-Konfiguration) und
`--storage` von selbst:

```powershell
$wann = (Get-Date).AddMinutes(3).ToString("yyyy-MM-dd HH:mm")
.\.venv\Scripts\chatexporter.exe task create Testlauf-geplant --once "$wann" --command "update --non-interactive"
```

Zur geplanten Zeit öffnet sich ein Konsolenfenster des Laufs. Den Rechner dafür
nicht sperren. Danach:

```powershell
.\.venv\Scripts\chatexporter.exe task get testlauf-geplant
```

- [ ] Im Konsolenfenster des Laufs stehen `DEV-MODUS AKTIV …`, `Keine gueltige
  ChatGPT-Sitzung – automatische Anmeldung ...` und `Automatische Anmeldung
  erfolgreich.`; das Browserfenster bleibt unsichtbar.
- [ ] `task get`: `Letztes Ergebnis: 0`.
- [ ] Beleg, dass das neue Profil jetzt angemeldet ist:

```powershell
.\.venv\Scripts\chatexporter.exe chatgpt login
```

  Erwartung: `"already_logged_in": true`, keine Anmeldeschritte.
- [ ] Aufgabe entfernen:

```powershell
.\.venv\Scripts\chatexporter.exe task delete testlauf-geplant --yes
```

## 8. Teil C – Profilkopie mit geöffnetem Browser

Prüft die Einrichtung: Ein vorhandenes Edge- oder Chrome-Profil mit
ChatGPT-Anmeldung wird kopiert. Der geöffnete Browser wird dafür geschlossen und
danach samt Tabs wieder geöffnet. Die Kopie landet im Testordner, die
Konfiguration bleibt unverändert (kein `--persist`). Vorher **Edge mit einigen
Tabs öffnen**:

```powershell
.\.venv\Scripts\python.exe ChatExporter_Gen4_pre-6\tools\chatgpt\browser_flow_lab.py --search --browser-root $t\browser
```

Das Werkzeug hält an jedem Schritt an und fragt bei der Kopie nach.

- [ ] Die Profile werden mit ihrem ChatGPT-Stand angezeigt (ja / nein /
  unbekannt).
- [ ] Bei der Kopie eines Edge-Profils mit Anmeldung: Hinweis und Rückfrage. Nach
  `j` schließt das Programm **nur** diesen Edge, kopiert das Profil nach
  `$t\browser\profiles\<Zeitpunkt>_<Profilordner>` und öffnet Edge **mit den
  vorherigen Tabs** wieder.
- [ ] Die Kopie startet, während der normale Edge wieder offen ist, und hat die
  ChatGPT-Anmeldung. Es gibt kein Fenster „Wir synchronisieren Ihre Daten …“.
- [ ] **Chrome** (nur wenn ein Chrome-Profil mit ChatGPT-Anmeldung angezeigt
  wird): das Werkzeug erneut starten, die Edge-Kopie ablehnen (`n`) und die
  Chrome-Kopie annehmen. Die Kopie muss die Anmeldung tragen. Gelingt das nicht,
  ist das ein Befund für [BEKANNTE_EINSCHRAENKUNGEN.md](BEKANNTE_EINSCHRAENKUNGEN.md)
  (app-gebundene Verschlüsselung ab Chrome 127).

## 9. Zusätzliche Fälle (optional, ohne Anfragen an ChatGPT)

**Fremder Ordner wird kein Storage:**

```powershell
New-Item -ItemType Directory "$t\fremd" | Out-Null
Set-Content "$t\fremd\notiz.txt" "x"
.\.venv\Scripts\chatexporter.exe --storage "$t\fremd" status
```

- [ ] Exitcode 2 und die Meldung `Ordner ist nicht leer und kein Storage …`.
  Danach enthält `$t\fremd` weiterhin nur `notiz.txt`.

**Sperre:** In einem zweiten Fenster, mit `$t` und `CHATEXPORTER_CONFIG` aus
Schritt 0, `update` starten, während in diesem Fenster einer läuft.
- [ ] Der zweite endet mit Exitcode 2 und `Storage belegt` mit Inhaber.

**Passwort über `--set` wird nie gespeichert** (Fantasiewert):

```powershell
.\.venv\Scripts\chatexporter.exe --set providers.chatgpt.auth.password=TEST-GEHEIM-1 status
Select-String -Path $t\storage\.storage\logs\*.jsonl, $t\storage\.storage\state.yaml -Pattern "TEST-GEHEIM-1"
```

- [ ] Keine Treffer. In Protokoll und `state.yaml` steht `(verdeckt)`.

## 10. Aufräumen

1. Offen gelassene Edge-Fenster der Testprofile schließen (minimiert in der
   Taskleiste). Die Aufgabe `testlauf-geplant` muss gelöscht sein:
   `task list` zeigt sie nicht mehr.
2. Den Testordner löschen:

```powershell
Remove-Item -Recurse -Force $t
```

3. Den Registry-Eintrag des Test-Storages entfernen. `<ID>` ist die ID aus
   Schritt 1:

```powershell
Remove-Item -Recurse "HKCU:\Software\ChatExporter\Storages\<ID>"
```

4. Die Test-Einstellung des Fensters entfernen, oder das Fenster schließen:

```powershell
Remove-Item Env:CHATEXPORTER_CONFIG
```
