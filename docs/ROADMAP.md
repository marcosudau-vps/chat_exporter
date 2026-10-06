# Roadmap bis zur ersten Release-Version `v0.0.1`

**Status: PLANUNG / Arbeitsrahmen.** Dieses Dokument beschreibt Ziele und
Reihenfolge, **keinen Ist-Zustand**. Was umgesetzt ist, steht in
[CHANGELOG.md](../CHANGELOG.md), [ARCHITEKTUR.md](ARCHITEKTUR.md) und den
übrigen Dokumenten. (Übernommen aus `ROADMAP_TO_V0.0.1.md` von pre-5; der rote
Faden und die Phasen bleiben, Begriffe und Voraussetzungen sind auf den Stand
pre-6 angepasst. Anpassungen sind mit „pre-6:“ gekennzeichnet.)

**Ziel:** Einen klaren roten Faden schaffen, ohne die inhaltliche
Release-Ausgestaltung zu früh festzuschreiben.

---

## Übergreifende Regeln

1. Die offizielle Versionsgeschichte beginnt erst mit ausdrücklich freigegebenem `v0.0.1`.
2. Bis dahin werden interne Stände als `pre-1`, `pre-2`, … geführt (aktuell `pre-6`).
3. Veränderliche Entwicklungsdaten liegen außerhalb austauschbarer `pre-X`-Codeordner (DEVELOPMENT_WORKSPACE.md).
4. Jede Phase besitzt explizite Eintritts- und Austrittskriterien.
5. Phasen werden bewusst abgeschlossen; abgeschlossene Entscheidungen werden nur bei neuer belastbarer Evidenz wieder geöffnet.
6. Datenintegrität, Secret-Hygiene und reproduzierbare Tests sind Release-Gates, keine optionalen Qualitätsverbesserungen.
7. Das Product-Modell und der Normalbetrieb werden vor `v0.0.1` organisatorisch festgelegt und dokumentiert.
8. Reihenfolge je Arbeitsschritt: implementieren → testen → dokumentieren; Planung wird als Planung gekennzeichnet (`ChatExporter/AGENTS.md`).

**pre-6:** Der Aufbau ist jetzt mehrschichtig: Raw Session Updater (Daten holen
und im Raw Storage ablegen) mit eigenständigen Providern, daneben Exporter
(Raw Storage → Markdown/JSON) und Zeitplanung ([ARCHITEKTUR.md](ARCHITEKTUR.md)).
Wo die frühere Roadmap von „RawStorage, Sync und Exporten“ als einem Block
sprach, sind das heute getrennte Verantwortungen.

---

## 1. HARDENING-PHASE – aktuellen Stand stabilisieren und härten

### Ziel

Alles, was der aktuelle Stand bereits enthält, muss unter realen Daten
zuverlässig funktionieren. Neue Funktionen sind nur zulässig, wenn sie
unmittelbar der Robustheit, Diagnostik, Datenintegrität oder Bedienbarkeit des
vorhandenen Umfangs dienen.

### Arbeitspakete

- Entwicklungs-Workspace entkoppeln: gemeinsame venv, externer Raw Storage, externes Edge-Profil, externe `.env`. *(pre-6: umgesetzt, siehe DEVELOPMENT_WORKSPACE.md)*
- Erst-Update gegen den realen Bestand stabilisieren; Folge-Update mit unverändertem Bestand verifizieren (zweiter Lauf überspringt Unverändertes).
- Browser-/CDP-Abbruch, Anmeldeverlust, Netzwerkfehler, 4xx/5xx und Fehlerbudgets verifizieren.
- Raw-Storage-/Index-Neuaufbau und Abbruch-/Wiederaufnahme-Verhalten praktisch prüfen.
- Datei-Erfassung isoliert härten; bekannte 403/404-Klassen systematisch unterscheiden.
- Datei-Deduplizierung, Cache-Treffer und Wiederholungslogik verifizieren.
- Export aus dem vorhandenen Raw Storage ohne Netz verifizieren. *(pre-6: der Exporter ist eigenständig und gegen den Realbestand verglichen, siehe CHANGELOG)*
- Große Konversationen/Graphen und große Dateimengen als Skalierungsfälle testen.
- Secret-/Privacy-Redaktion insbesondere in Ausnahme-/Playwright-Logs absichern.
- Fortschritts-, Fehler- und Abschlussausgaben so gestalten, dass der Zustand eines langen Laufs jederzeit verständlich ist. *(pre-6: Konsolen-Zusammenfassung je Quelle, Laufbericht Schema 4, Befehlsprotokoll)*
- **pre-6 neu:** Zeitplanung (täglicher unbeaufsichtigter Lauf) unter realen Bedingungen prüfen, inklusive ChatGPT-Anmeldung ohne Interaktion.
- **pre-6 neu:** Live-Lauf aller vier Quellen mit dem aktuellen Code (Listing-Modus `auto`, Grenzprüfung, Anfragezählung).

### Austrittskriterien

- Alle bestehenden Funktionen haben definierte Live-Testfälle ([LIVE_TEST_CHECKLIST.md](LIVE_TEST_CHECKLIST.md)) und bestehen diese reproduzierbar.
- Keine bekannten stillen Datenverluste oder Teil-Commit-Probleme.
- Browser-/Transportverlust erzeugt keinen Request-Sturm.
- Das Fehlerbudget funktioniert.
- Der Raw Storage ist nach einem Abbruch wiederverwendbar.
- Der Gesamtindex lässt sich aus dem Raw Storage vollständig neu aufbauen.
- Ein zweiter unveränderter Lauf überspringt unveränderte Konversationen korrekt.
- Bekannte Datei-Fehlerklassen sind behoben oder sauber als unterstützte/nicht unterstützte Zustände modelliert.
- Offline-Tests grün, Live-Testprotokoll vollständig.
- Das Hardening wird in einer ausdrücklichen Abnahme als beendet erklärt.
  *(2026-10-05: Der Benutzer hat den Release-Umfang festgelegt; das Hardening endet mit
  der Abnahme des Release-Kandidaten 0.0.1rc1, siehe RELEASE.md.)*

---

## 2. BERATUNGSPHASE 1 – Produktentwurf und Zuschnitt von `v0.0.1`

### Ziel

Nach Abschluss der Härtung wird erstmals bewusst festgelegt, **was das erste
Release als Produkt sein soll**.

### Themen

- den vorhandenen Stand gemeinsam bewerten;
- Nutzergruppen und primäre Anwendungsfälle definieren;
- gewünschtes Bedien-/CLI-Erlebnis festlegen;
- Funktionen und Verbesserungen für `v0.0.1` auswählen;
- ebenso wichtig: ausdrückliche **Nicht-Ziele** für `v0.0.1` festlegen;
- Einrichtungs- und Konfigurationserlebnis aus Anwendersicht definieren;
- Fehlermeldungen, Diagnose, Wiederaufnahme und Statusberichte aus Anwendersicht definieren;
- Ablage-/Export-Vertrag aus Produktsicht festziehen;
- Kompatibilitäts-/Migrationsanforderungen für vorhandene pre-X-Raw-Stores festlegen;
- **pre-6:** welche Quellen (ChatGPT, OpenCode, Codex, Claude) gehören zu `v0.0.1`, und ob der Exporter weitere Quellen unterstützen soll.

### Ergebnis

Eine priorisierte, aber nicht bewertend gerankte Umsetzungsliste. Jeder Eintrag
enthält mindestens: Zweck/Nutzerwert, Umfang, Nicht-Umfang, gewünschtes
Verhalten, technische Eckdaten, Daten-/Ablage-Auswirkungen, Fehlerverhalten,
Akzeptanzkriterien, benötigte Tests, benötigte Dokumentation.

Ergebnisdokument: [V0.0.1_PRODUCT_SCOPE.md](V0.0.1_PRODUCT_SCOPE.md) – **beschlossen am 2026-10-05**:
Umfang = der implementierte Stand, darin nichts offen; Version 0.0.1.

---

## 3. IMPLEMENTIERUNGSPHASE – festgelegten Release-Umfang umsetzen

1. Einträge aus `V0.0.1_PRODUCT_SCOPE.md` nacheinander umsetzen.
2. Tests und Dokumentation gemeinsam mit der Umsetzung nachziehen.
3. Nach Abschluss aller Einträge gezielt auf Seiteneffekte, Randfälle, Regressionen und Wechselwirkungen prüfen.
4. Vollständige Regression gegen Raw Storage, Folge-Update, Dateien und Exporte.
5. Inhaltliche Gesamtabnahme.

Austrittskriterium: Der abgenommene Stand ist der **inhaltlich finale
Release-Umfang**. Danach werden keine neuen Produktfunktionen mehr aufgenommen,
außer ein Release-Blocker erzwingt es.

---

## 4. BERATUNGSPHASE 2 – Build, Deployment, Releaseprozess und dauerhafter Normalbetrieb

### Ziel

Den inhaltlich finalen Produktstand in einen reproduzierbaren, auditierbaren
und dauerhaft wartbaren Betrieb überführen.

### 4.1 Release-/Plattformstrategie

**pre-6: Richtung festgelegt, Umsetzung offen (BESCHLOSSEN, UMSETZUNG OFFEN):**
Die Anwendung soll als **fest installierte Windows-Anwendung** mit
**Inno Setup** ausgeliefert werden, mit festen Ordnern für Programm und Daten,
damit der tägliche automatische Lauf (Zeitplanung) stabil auf einem
unveränderlichen Programmstand läuft. Die Entwicklungs-venv bleibt der
Entwicklungsweg; der Installer ist der Betriebsweg.

Zu klären (siehe 4.2a):

- unterstützte Plattformen (derzeit nur Windows 11, Python 3.12, Microsoft Edge);
- Distributionsform: eingefrorene Programmdatei oder mitgelieferte Python-Laufzeit;
- Installationsart (pro Benutzer oder pro Rechner) und Ordner für Programm, Konfiguration, Daten, Edge-Profil;
- Umgang mit Entwicklungs-venv und Endanwenderinstallation;
- Release-Artefakte und Versionierungsmodell; ggf. Release-Candidate-Modell.

### 4.2 Build-Prozess

Festlegen: reproduzierbarer Build; Build-Voraussetzungen; Tests vor dem Build;
zu erzeugende Artefakte (Installer, Prüfsummen, Manifest); Abhängigkeits-/SBOM-
Information, falls sinnvoll; Clean-Room-/Neuinstallationstest; Upgrade-/Migrationstest.
Ergebnis: BUILD.md (Programm und Installer umgesetzt; Test auf frischem Windows in der Windows Sandbox am 2026-10-05: 38 von 38 Prüfungen, CHANGELOG).

### 4.2a Deployment mit Inno Setup (Planung, teilweise umgesetzt)

Vorgesehene Schritte, in dieser Reihenfolge:

1. **Entscheidungen** (Abschnitt „Entscheidungen zum Deployment“ unten) treffen und festhalten. *(2026-10-02: weitgehend getroffen.)*
2. **Code installationsfähig machen:** Version aus einer einzigen Quelle (`pyproject.toml`); Config-Auffindung für den installierten Betrieb (*umgesetzt: `~/.chatexporter`, Suche ab dem Arbeitsordner nur beim Start aus dem Quellcode*); kein Bezug mehr auf eine venv im Betrieb; Zeitplanung startet die installierte Programmdatei statt `python -m`; `scheduler_manager.py` und `pywin32` im Paket enthalten. *(2026-10-03: umgesetzt, dazu `chatexporter setup` und `task delete --all`.)*
3. **Programm bauen:** reproduzierbar aus sauberem Stand (Tests grün, dann Build). Entweder eingefrorene Programmdatei (z. B. PyInstaller; pywin32 und Playwright-Treiber brauchen besondere Aufmerksamkeit) oder Python-Laufzeit plus Wheels im Installer. Danach Rauchtest der gebauten Datei (`--version`, `check`, `task list`, `export` gegen Testdaten). *(2026-10-03: umgesetzt mit PyInstaller, `packaging/build.py`, siehe BUILD.md.)*
4. **Installer-Skript** (`.iss`) schreiben: feste Ordner; Programmdateien ersetzbar, Daten und Konfiguration **nie** überschreiben oder beim Deinstallieren löschen; Eintrag in „Apps & Features“; optional Schritt „tägliche Aktualisierung einrichten“ (`task create`); Deinstallation entfernt die geplante Aufgabe; Upgrade über dieselbe `AppId`. *(2026-10-03: `packaging/installer/chatexporter.iss` umgesetzt, auf dem Entwicklungsrechner installiert, aktualisiert und deinstalliert; dazu `chatexporter uninstall`.)*
5. **Datenschutz im Installer:** keine Secrets, keine Konfiguration mit persönlichen Werten, keine Rohdaten im Installer; `.env` wird nie mitgeliefert.
6. **Tests:** Neuinstallation in sauberer Umgebung (Windows Sandbox/VM), Upgrade von der Vorversion mit vorhandenem Datenbestand, Deinstallation, tägliche Aufgabe nach Neustart.
7. **Artefakte:** Installer, SHA-256-Prüfsumme, Build-Manifest; optional Codesignatur (gegen SmartScreen-Warnungen).
8. **Freigabe:** Promotion nach `workspace_product/` nur nach menschlicher Abnahme (`AGENTS.md`, `PROMOTION_RULES.md`).

Voraussetzungen auf dem Build-Rechner: Inno Setup 6, Python 3.12 mit Build-venv
und dem Build-Werkzeug, optional ein Codesignatur-Zertifikat, eine saubere
Testumgebung.

### 4.3 Releaseprozess

Festlegen: Release-Gates; CI/CD; Branch-/Tag-Regeln; Freigabeprozess; manuelle
Kontrollpunkte; Rollback-/Hotfix-Prinzipien; Release Notes; Artefaktarchivierung.
Ergebnis: RELEASE.md (angelegt 2026-10-05; ohne CI/CD, Ablauf von Hand mit
Prüfskripten).

### 4.4 Product-Ordner

Zusammenführen und dokumentieren: Zweck und Rolle des Product-Ordners;
welche Artefakte hineindürfen (Installer, Prüfsummen, Release Notes); Promotion-
Regeln Development → Product; Voraussetzungen für Promotion; Verhältnis zum
übergeordneten Projekt `ChatToolSuite`; Versionierungs- und Archivierungsregeln;
welche Entwicklungs- und Research-Artefakte ausdrücklich draußen bleiben.

### 4.5 Dauerhafte Projektorganisation

Festlegen und dokumentieren: Branching-Modell; Pull Requests und Reviews;
Merge-Regeln; Test- und Dokumentationspflichten; Qualitätsstandards;
Abnahme-Regeln; Issue-/Fehler-/Funktions-Lebenszyklus; Migrations-/Schema-Regeln;
Umgang mit Breaking Changes; Security-/Secret-Regeln; Arbeitsweise von Agenten
inklusive Beleg- und Evidenzpflichten; Definition of Done; Archiv-/Aufbewahrungs-
regeln für Research und Build-Belege; Verantwortlichkeit für Faktenprüfung und
Release-Freigabe.

Kerndokumente: `AGENTS.md`, BUILD.md, CONTRIBUTING.md,
RELEASE.md, SECURITY.md, TESTING.md – alle
angelegt (2026-10-05). (`ARCHITEKTUR.md` und die
Entwicklungs-Beschreibung bestehen als [ARCHITEKTUR.md](ARCHITEKTUR.md) und
DEVELOPMENT_WORKSPACE.md.) Vor Phasenabschluss wird
ein Dokumentations-Vollständigkeitscheck durchgeführt.

### 4.6 Planung nach `v0.0.1`

Noch vor dem Release organisatorisch festlegen: wie neue Funktionen initiiert
werden; wie Roadmaps geführt werden; wie Wartungs-/Patch-Releases entstehen;
wie API-Drift und Änderungen am ChatGPT-Backend überwacht und behandelt werden;
wie Regressionen gegen vorhandene Raw-Stores geprüft werden; wie Produkt- und
Research-Arbeit getrennt bleiben.

---

## 5. PRE-RELEASE-PHASE – praktische Umsetzung der organisatorischen Entscheidungen

Abhängig von Phase 4, voraussichtlich: Repository final einrichten;
Branch-/Schutzregeln konfigurieren; CI/CD-Abläufe umsetzen; reproduzierbaren Build
und Installer umsetzen; Release-Prüfungen automatisieren; Neuinstallations-,
Upgrade- und Migrationstests durchführen; Product-Ordner vorbereiten;
Dokumentation konsolidieren und faktisch prüfen; Secret-/Privacy-/Abhängigkeits-
Scan; Entwicklungsreste und Laufzeit-/Log-/Cache-Artefakte entfernen; den
Releaseprozess mindestens einmal vollständig proben.

Austrittskriterien: Arbeitsbereich sauber; alle Tests grün; keine ungeklärten
Release-Blocker; Dokumentation konsistent und faktisch geprüft; Build und
Installer reproduzierbar; Upgrade/Migration dokumentiert und getestet;
Product-Ordner vorbereitet; Releaseprozess erfolgreich geprobt.

---

## 6. RELEASE-PHASE – `v0.0.1`

Keine neuen Produktänderungen mehr außer zwingenden Release-Blockern.

1. Finale Release Notes.
2. Den vorbereiteten Releaseprozess ausführen.
3. Erzeugte Artefakte (Installer) manuell prüfen.
4. Prüfsummen und Manifeste kontrollieren.
5. Release-Artefakte archivieren.
6. Release-Tag/Freigabe gemäß `RELEASE.md`.
7. Den freigegebenen Stand nach den Promotion-Regeln in den Product-Ordner überführen.
8. Abschlussprotokoll erstellen.

---

## Entscheidungen zum Deployment (Phase 4)

**Getroffen am 2026-10-02 (BESCHLOSSEN, Umsetzung teilweise):**

| Frage | Entscheidung | Stand |
| --- | --- | --- |
| Installation pro Benutzer oder pro Rechner? | **pro Benutzer** (keine Administratorrechte; passt zur geplanten Aufgabe und zum benutzerbezogenen Browser-Profil) | **umgesetzt** (Installer, BUILD.md) |
| Wo liegen Konfiguration und Daten? | standardmäßig alles in **`~/.chatexporter`**: `config.yaml`, `.env`, `data/`, `logs/`, Sicherungen; abweichend über `CHATEXPORTER_HOME`, `--config` oder die Pfade in der config.yaml | **umgesetzt** (Home, Suche, Vorlage; siehe [KONFIGURATION.md](KONFIGURATION.md)) |
| Wie wird die Konfiguration im installierten Betrieb gefunden? | `--config` > `CHATEXPORTER_CONFIG` > `~/.chatexporter/config.yaml`; die Suche ab dem Arbeitsordner gilt nur beim Start aus dem Quellcode | **umgesetzt** |
| Fehlende Konfiguration | wird als vollständige, auskommentierte Vorlage neu angelegt | **umgesetzt** |
| Persistenter Spiegel der angewendeten Einstellungen | Windows-Registry `HKCU\Software\ChatExporter\config\Current`, nur schreibend, nach jeder erfolgreich angewendeten Einstellung | **umgesetzt** (Grundlage für eine spätere Funktion) |
| Eingefrorene Programmdatei oder Python-Laufzeit? | **eingefrorene Programmdatei** | **umgesetzt** (PyInstaller und Inno Setup, BUILD.md) |
| Browser für ChatGPT ohne konfigurierten Pfad | Reihenfolge: vorhandene Profilkopie, dann **Kopie** eines Edge-/Chrome-Profils mit ChatGPT-Cookies (einmalig, Browser dafür schließen, nach Bestätigung), dann Edge/Chrome mit eigenem Profil, dann Chrome for Testing (Download nach Bestätigung); Anmeldeprüfung je Profil; gewählter Weg wird in die Konfiguration eingetragen | **umgesetzt** ([providers/CHATGPT.md](providers/CHATGPT.md), Abschnitt 2); eine Edge-Kopie wurde bei der ersten echten Einrichtung am 2026-10-03 angelegt (CHANGELOG Nachtrag (7)); ob sie die Anmeldung trug, ist nicht belegt; Chrome-Kopie ungeprüft. Grund für die Kopie: ein geöffneter Browser sperrt sein Standardprofil, Chrome ab 136 erlaubt dort keine Fernsteuerung |
| Codesignatur | vorerst **keine** (private Nutzung); SmartScreen-Warnung beim Erststart wird hingenommen | beschlossen 2026-10-03 |
| Migration des vorhandenen Datenbestands in die Installation | übernimmt der Benutzer selbst | beschlossen 2026-10-03 |
| Geplante Aufgaben im installierten Betrieb | Aufgaben starten `chatexporter.exe` direkt | **umgesetzt** ([TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md), Abschnitt 2) |
| Entwicklungshilfen | Schalter `dev_mode`, Browser-Labor `tools/chatgpt/browser_flow_lab.py` | **umgesetzt** (DEVELOPMENT_WORKSPACE.md) |
| Programm und Datenhaltung trennen | **Storage** als autarke Dateninstanz (eigene Daten, Zustand, Konfiguration, Registry-Bereich); Standard `~/.chatexporter/storages/default` | **umgesetzt** 2026-10-03 ([STORAGE_KONZEPT.md](STORAGE_KONZEPT.md)) |
| Erstabruf über mehrere Läufe | automatische Fortsetzung per einmaliger Aufgabe nach jedem Rate-Limit-Stopp, bis alles geladen ist | **umgesetzt** ([TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md), Abschnitt 5a) |

**Noch offen:**

| Frage | Hinweis |
| --- | --- |
| Automatische Updates | nicht Teil von `v0.0.1` vorgesehen; ein neuer Installer aktualisiert über dieselbe `AppId` |
| Migration des Datenbestands bei Versionswechsel | Raw-Storage-Schemaänderungen nur additiv oder mit ausdrücklicher Migration; vor einem Upgrade Sicherung der Statusdateien |

---

## Zusätzliche Querschnitts-Gates

### Datenkompatibilität

Vor `v0.0.1` muss geklärt sein, wie mit Raw-Storage-Schemaänderungen zwischen
pre-X-Ständen umgegangen wird. Bevorzugt: additive Änderungen oder ausdrückliche
Migration; niemals stilles Überschreiben inkompatibler Daten.

### Wiederherstellung

Ausdrücklich testen: Prozessabbruch; Browser geschlossen; Anmeldung verloren;
Netzwerk weg; einzelner 4xx/5xx; Fehlerbudget erreicht; beschädigter Index;
fehlender Index; Datei teilweise vorhanden; Exportfehler (der Exporter ist vom
Raw Storage getrennt und kann ihn nicht beschädigen).

### Skalierung

Mindestens reale Größenordnungen des vorhandenen Kontos abdecken: tausende
Konversationen, Konversationen mit mehreren tausend Graph-Knoten und mit vielen
Datei-Verweisen.

### Security / Privacy

Keine Secrets in Logs und Laufberichten; keine Session-Cookies in Ausnahmen;
kein Token auf der Platte; das dedizierte Browser-Profil klar vom privaten
Standardprofil getrennt; **pre-6:** der Installer enthält nie Secrets, `.env` oder Daten.

### Reproduzierbarkeit

Jeder abgenommene Entwicklungsstand soll anhand dokumentierter Befehle testbar
sein. Ab der Pre-Release-Phase muss der Build (inklusive Installer) aus einem
sauberen Stand reproduzierbar sein.
