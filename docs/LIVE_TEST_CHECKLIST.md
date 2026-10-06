# Live-Test-Checkliste – pre-6

Zweck: die fachlichen Funktionen unter realen Bedingungen prüfen. Das ist eine
**Checkliste**, kein Prüfbericht: Ein Punkt gilt erst als bestanden, wenn der
Lauf mit Beleg (Laufbericht, Konsolenausgabe) protokolliert ist. Übernommen aus
`LIVE_TEST_CHECKLIST_PRE5.md` und auf die Befehle und Funktionen von pre-6
angepasst; die früheren Stände liegen unter historie/.

Alle Befehle laufen aus der aktivierten workspace-venv (oder mit vollem Pfad).
Ergebnisse gehören in eine Arbeitsakte unter
`workspace/_dokumentation/60_ARBEITSDOKUMENTATION/`. Keine Secrets protokollieren.

## 1. Vorbereitung

```powershell
chatexporter --version
chatexporter-chatgpt doctor
chatexporter-check
```

Prüfen: verwendete `config.yaml`, Datenordner, aktive Quellen (Menükopf),
`bootstrap.venv_path`/`env_file`, Edge-Profil, Rate-Limit-Einstellungen,
Quarantäne-Stand, importierte Konversationen, Konversationen mit offenen Dateien.
Der Programmstand im Menükopf muss den Codeordner pre-6 zeigen, keine feste Kopie
in `site-packages`.

## 2. Gesamtlauf und Laufbericht

```powershell
chatexporter-update --non-interactive
```

- **Erwartung:** pro Quelle eine Zusammenfassung (`ok | neu, geändert, gespeichert,
  fehlgeschlagen, Dateien, Anfragen | Dauer`); genau **ein** Laufbericht
  `data\.storage\runs\sync_<UTC>.json` (Schema 4) mit `sources`, `totals`
  (inklusive `requests_total`) und je Quelle Start/Ende/Dauer/`items`.
- Exitcode `0`, bei fachlichen Fehlern `1`, bei Ausfall einer Quelle `2`.
- Strg+C während einer Quelle: diese Quelle wird als `interrupted` vermerkt, der
  Laufbericht wird trotzdem geschrieben, die nächste Quelle läuft weiter.

## 3. ChatGPT-Listing (Modus `auto`)

- Ohne Bestand: vollständiges Listing. Mit Bestand: `recent` (eine Seite,
  `order=updated`, `limit=100`; eine zweite nur, wenn alle 100 neu/geändert sind).
- **Erwartung:** `sources.chatgpt.detail.listing` mit Modus, Seiten, Grenze;
  `verification` (Grenzprüfung: die Chats an der Grenze werden inhaltlich verglichen,
  jede Abweichung hängt einen weiteren an, bis drei in Folge unverändert sind);
  `requests` je Kategorie. Wird die Grenze nicht bestätigt, wechselt der Lauf im
  selben Lauf auf `full` (Grund im Bericht).
- Gegenprobe `chatexporter-update --source chatgpt --listing-mode full`: dieselbe
  Menge neuer/geänderter Konversationen wie `recent`; `missing_remote = 0`.
- Zweiter unveränderter Lauf: nur das Listing, keine Detailabrufe außer den
  Grenz-Chats.

## 3a. Browser und Profil

- Fester Pfad (`providers.chatgpt.browser.user_data_dir` gesetzt): Lauf verbindet
  sich wie bisher; `detail.browser.mode = configured`.
- Ohne Pfad (z. B. mit einer Test-config.yaml und freiem `cdp_port`): die Versuche
  stehen mit Grund in der Konsole und unter `detail.browser.attempts`; ein Weg ohne
  Anmeldung wird im nicht-interaktiven Lauf übersprungen und sein Browser wieder
  geschlossen; nach Erfolg stehen `user_data_dir`, `kind`, `executable` in der config.yaml.
- Interaktiv: Aufforderung zur Anmeldung im ersten funktionierenden Profil; Chrome
  for Testing nur nach Rückfrage.
- Profilkopie (am besten mit `tools/chatgpt/browser_flow_lab.py --search
  --browser-root <Testordner>`): Hinweis und Bestätigung erscheinen; bei offenem
  Browser folgt die erneute Prüfung; nach dem Schließen wird kopiert
  (`chatexporter_copy.json` vorhanden, keine Caches); die Kopie startet, während der
  normale Browser wieder offen ist, und hat die ChatGPT-Anmeldung.
- **Geprüft (2026-10-05, Teil C):** Edge-Profilkopie einschließlich Anmeldung
  in der Kopie und Wiederöffnen des ursprünglichen Browsers mit Tabs.
  **Bekannte Einschränkung:** Chrome-Profilkopie (Cookie-Entschlüsselung
  in der Kopie) ist nicht live bestätigt. Chrome for Testing mit echtem Download: in der Windows Sandbox
  geprüft (2026-10-05, CHANGELOG). Automatische Anmeldung und Gesamtablauf im
  Entwicklungsmodus: [TESTABLAUF_ENTWICKLUNGSMODUS.md](TESTABLAUF_ENTWICKLUNGSMODUS.md).

## 4. Rate-Limit

- `sync.rate_limit_wait_minutes: 0` setzen und bis zum Limit laufen lassen.
- **Erwartung:** regulärer Laufschluss mit Block `[LIMIT ERREICHT] / [CHATS] / [FILES] /
  [LIMIT WIEDER VOLL]`; `rate_limit_hits > 0` im Bericht, kein Fehlerbudget verbraucht.
- Optional `rate_limit_wait_minutes: 15`: der Lauf wartet und setzt nur die offenen
  Einträge fort.
- Automatische Fortsetzung: nach dem Limit-Stopp steht im Bericht
  `continuation_chatgpt: geplant …` und die Aufgabe `fortsetzung-chatgpt` existiert
  (`chatexporter task get fortsetzung-chatgpt`); nach dem letzten Lauf ist sie
  entfernt. **Nur mit kleinem Bestand testen** (Kontingent schonen).

## 5. Dateien und Vollständigkeit

- Dateien werden unmittelbar nach der jeweiligen Konversation geladen.
- `json_complete` und `files_complete` getrennt: Konversation ohne Datei-Verweise
  ist sofort dateivollständig; fehlt nur die Dateiebene, wird nur sie nachgeholt.
- HTTP 404 auf eine Datei: endgültig, einmal vermerkt (Statusablage, **kein**
  `unavailable.json` in der Library), blockiert die Vollständigkeit nicht.
- Dateien aus Custom GPTs (`gizmo_id`) werden ohne 403 geladen.
- Eigenes Dateifehlerbudget (`sync.max_file_errors_per_run`), getrennt vom API-Budget.

## 6. Quarantäne und manuelle Ausschlüsse

- Quarantäne (`sync.quarantine.enabled`, Standard aus): Aufnahme nur bei allen
  Bedingungen; HTTP 429/401/403/404 nie; `review_after` je Eintrag.
- `sync.manual_exclusions`: ausgeschlossene Konversationen werden nicht abgerufen,
  tauchen aber nicht als neu auf (`IGNORED`).

## 7. Import von Kontodatensätzen

```powershell
chatexporter-chatgpt import-data --source "<ordner>" --limit 15
```

- **Erwartung:** Envelopes mit `acquisition.source: imported_data`, `json_complete: false`;
  das nächste Update lädt sie vollständig über die API nach.

## 8. Lokale Quellen (OpenCode, Codex, Claude)

```powershell
chatexporter-update --source opencode --source codex --source claude
```

- **Erwartung:** je Quelle `ok`; wiederholter Lauf ohne Änderung speichert nichts neu.
- OpenCode: Sitzungsanzahl entspricht der Datenbank (`C:\Users\<name>\.local\share\opencode\opencode.db`).

## 9. Index, Prüfung, Aufräumen

```powershell
chatexporter-index
chatexporter-check
chatexporter-check --deep
chatexporter-cleanup --dry-run
chatexporter-status
```

- Index: `coverage.percent` 100,0; bei jedem Abzug `failed_files` begründet; ein
  ungültiges Fragment lässt den alten Index unverändert (Exitcode 2).
- Prüfung: `ok: true`, keine Fehler; Warnungen nur für bewusst bekannte Reste;
  `raw_storage/` enthält nur Quellen-Ordner.
- Selbstheilung: Index entfernen und `chatexporter-index`; der Index ist vollständig
  rekonstruiert.
- Datenseitige Szenarien (Index/Konversation/Library/Status fehlend oder verfälscht)
  nur auf einer **Kopie**:
  `chatexporter-chatgpt scenarios --source <raw_root> --work <kopie>` – alle PASS;
  nicht automatisch wiederherstellbare Fälle sind markiert.

## 10. Exporter

```powershell
chatexporter-export
chatexporter-export --format json --export-root <testordner>
```

- **Erwartung:** Markdown/JSON aus dem Raw Storage ohne Netz; die Anzahl der
  Konversationen entspricht dem Bestand; Manifest unter `exports\manifests\`;
  der Raw Storage bleibt unverändert; ein zweiter Lauf erzeugt identische Dateien.
- Eine beschädigte Rohdatei: Exitcode `1`, die übrigen Konversationen sind exportiert.

## 11. Befehlsprotokoll

- Jeder Befehl (Menü, `chatexporter …`, Einzelbefehl) erscheint als eine JSON-Zeile
  in `data\.storage\logs\commands_<UTC>.jsonl` mit Zeitpunkt, Befehl, Exitcode und
  der Übersicht je Quelle; Rotation und Aufbewahrung gemäß `logging.*`.

## 12. Zeitplanung

```powershell
chatexporter task create "Test" --daily 03:00 --command status --paused
chatexporter task get test
chatexporter task update test --daily 03:30
chatexporter task resume test
chatexporter task delete test --yes
```

- **Erwartung:** die Aufgabe erscheint im Ordner `\ChatExporter` der Windows-
  Aufgabenplanung; nach dem geplanten Start steht der Lauf im Befehlsprotokoll
  (Exitcode 0) und `task get` zeigt Letzten Lauf und Ergebnis.
- Unbeaufsichtigter ChatGPT-Lauf (`update --non-interactive`) bei fehlender bzw.
  abgelaufener Anmeldung: Teil B des
  [Testablaufs](TESTABLAUF_ENTWICKLUNGSMODUS.md) (geplanter Lauf mit neuem Profil,
  automatische Anmeldung ohne Interaktion).
- `--startup` braucht Administratorrechte. Ohne sie lehnt Windows ab, und das
  Programm meldet es verständlich, ohne etwas anzulegen (geprüft am 2026-10-05). Mit
  Administratorrechten wird sie angelegt (Komplett-Test auf frischem Windows,
  [packaging/sandbox](../packaging/sandbox/README.md), 2026-10-05).

## 13. Robustheit

- Prozessabbruch (Strg+C): Laufbericht und Zustand bleiben konsistent.
- Browser schließen: sofortiger, fataler Abbruch ohne Request-Sturm.
- Anmeldung verloren: kontrollierter Abbruch mit Hinweis, kein Datenverlust.
- „Connection closed while reading from the driver“ (Playwright-Treiber weg):
  sofortiger, geordneter Abbruch wie beim geschlossenen Browser (behoben am
  2026-10-05, Test `test_known_errors.py`).
- `MemoryError` beim Laden einer Konversation: Das Programm räumt den Speicher
  auf und versucht diese Konversation einmal neu; ein zweiter Fehlschlag zählt als
  einzelner Fehler (behoben am 2026-10-05, Test `test_known_errors.py`). Beide
  Fälle traten nur im Lauf 20260924T214820Z auf (je 2×); die vier betroffenen
  Konversationen wurden später fehlerfrei geladen.

## 13a. Storage

- `chatexporter storage show`: Ort, Format `storage-schema-2` (Storage-Schema 2), ID; `config path` nennt
  Storage-config, `state.yaml` und den Registry-Bereich `Storages\<id>`.
- Entwicklungsbestand umstellen: `storage migrate --dry-run`, danach
  `storage migrate --fix-config`; vorher/nachher Anzahl und Größe der Dateien in
  `raw_storage/` gleich; danach `check`, `index`, `status` ohne Fehler.
- `config set exporter.formats json` landet in `.storage/config.yaml`,
  `config-global set …` in der globalen Datei; `state.yaml` zeigt die Herkunft.
- Zweites `update`, während eines läuft: Exitcode 2 „Storage belegt“ mit Inhaber.
- Nach `update`: `state.yaml` mit `update_counter`, `update_last`, Bestand je
  Quelle; nach `task create`: `update_next_scheduled_at`.
- Aufgaben: Befehl enthält `--storage`; `uninstall --remove-tasks` entfernt sie.

## 14. Abschluss

- Laufbericht vorhanden und plausibel; keine Secrets in Bericht, Protokoll
  oder Konsole.
- Offene Fehlerfälle in der Arbeitsakte erfasst; Doku mit dem tatsächlichen
  Stand abgeglichen.
