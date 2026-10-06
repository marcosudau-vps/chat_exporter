# Provider `chatgpt`

Sichert ChatGPT-Konversationen, Canvas-Dokumente und Dateien über die
ChatGPT-Weboberfläche. Paket: `src/chatexporter/providers/chatgpt/`.
Kommandozeile: `chatexporter-chatgpt` (siehe [BEFEHLE.md](../BEFEHLE.md)).

## 1. Aufbau des Pakets

| Modul | Aufgabe |
| --- | --- |
| `contract.py` | die fünf Vertragsfunktionen; `run_sync` (eigentlicher Lauf), `contract_result` (Übersetzung in das Vertragsergebnis) |
| `operations.py` | Einzellauf mit Laufbericht, Import, Diagnose, `migrate-store`, `migrate-layout`, `rebuild-index` |
| `cli.py` | Kommandozeile |
| `config/` | Einstellungen aus der gemeinsamen config.yaml (`discover_config`, `load_config`) |
| `auth/` | Browser-Erkennung, Profile/Profilkopie, Browser-Suche, Steuerung per CDP, Sitzungsprüfung, Token-Beschaffung |
| `api/` | dünne Backend-API: Listing, Konversation, Canvas, Datei-Download |
| `sync/` | Listing (`full`/`recent`), Planung, Orchestrierung (Rate-Limit, Budgets, Quarantäne) |
| `fetch/` | Abruf, Graph-Validierung, Datei-/Tool-Referenzen |
| `storage/` | Envelope, Rohdatenablage, Library, Index, Statusablage, Quarantäne, Prüfung, Layout-Migration, Mutationstests |
| `importing/` | Import eines OpenAI-Kontodatenexports |
| `common/` | Hilfsfunktionen (Hashing, atomares Schreiben, Redaktion, Zeit) |

## 2. Browser, Profil und Anmeldung

Der Provider steuert einen Browser per CDP (`browser.cdp_host`/`cdp_port`) und
nutzt dessen ChatGPT-Anmeldung. Zugangsdaten und Tokens werden nie
gespeichert oder ausgegeben.

**Fester Pfad:** Ist `providers.chatgpt.browser.user_data_dir` gesetzt, wird genau
dieses Profil verwendet (`kind` und `executable` wählen den Browser, Standard
Edge). Läuft der Browser schon am CDP-Port, verbindet sich der Lauf damit,
sonst startet er ihn.

**Automatische Suche** (kein Pfad gesetzt): Die Wege werden in dieser
Reihenfolge versucht; der erste, der startet, per CDP erreichbar ist **und** eine
ChatGPT-Anmeldung hat, gewinnt (`auth/browser_setup.py`, `auth/browsers.py`):

| Nr. | Weg | wird übersprungen, wenn … |
| --- | --- | --- |
| 1 | vorhandene Profilkopie `<browser>/profiles/<JJJJ-MM-TT_hh-mm-ss>_<Profilordner>` (je Quellprofil die neueste) | der zugehörige Browser nicht installiert ist |
| 2 | Kopie eines Edge-/Chrome-Profils anlegen (je Profil mit ChatGPT-Sitzungs-Cookie oder nicht lesbaren Cookies, für das es noch keine Kopie gibt; Profile mit Sitzung zuerst) | Lauf nicht interaktiv; Benutzer lehnt ab; Browser lässt sich nicht schließen; nach dem Schließen zeigt das Profil keine ChatGPT-Cookies; Kopie scheitert |
| 3 | Edge mit eigenem, leerem Profil `<browser>/profiles/edge` | Edge nicht installiert |
| 4 | Chrome mit eigenem, leerem Profil `<browser>/profiles/chrome` | Chrome nicht installiert |
| 5 | Chrome for Testing, eigenes Profil | nur bei interaktivem Start: nach Rückfrage wird die aktuelle stabile Version heruntergeladen (rund 150 MB, nach `<browser>/chrome-for-testing/<version>/`), geprüft und entpackt; `allow_download: false` schaltet das ab |

`<browser>` ist der Ordner `browser` neben der config.yaml, installiert also
`~/.chatexporter/browser`. Browser-Profile gehören nicht zu den Daten und liegen
deshalb nicht im Datenordner. Eine Kopie heißt nach Zeitpunkt (Ortszeit) und
Profilordner, z. B. `2026-10-03_04-54-16_Default`; Browser-Art, Quelle und
Anzeigename stehen in `chatexporter_copy.json` in der Kopie.

**Warum eine Kopie statt des Standardprofils?** Ein geöffneter Browser sperrt
sein Standard-Datenverzeichnis, und Chrome erlaubt dort ab Version 136 keine
Fernsteuerung. Ein eingetragenes Standardprofil würde also jeden Lauf scheitern
lassen, solange der Browser offen ist. Die Kopie ist ein eigenes
Datenverzeichnis: Der Abruf läuft, während der normale Browser weiter benutzt
wird. Das Standardprofil wird nie ferngesteuert.

**Keine Kontoanmeldung, keine Synchronisierung** (`auth/edge_cdp.py`): Ein vom
ChatExporter gestarteter Browser bekommt immer `--disable-sync`, Edge zusätzlich
`--disable-features=msImplicitSignin`. Ohne diese Optionen meldet Edge ein neues,
leeres Profil still mit dem Microsoft-Konto von Windows an und holt per
Synchronisierung Daten und Erweiterungen (gemessen am 2026-10-04 auf dem
Entwicklungsrechner: Konto verbunden, 11 Erweiterungen, Fenster „Wir
synchronisieren Ihre Daten …“). Mit beiden Optionen, gestartet über den
Programmcode: kein Konto, keine Synchronisierung, nur die 3 in Edge eingebauten
Erweiterungen, kein Fenster. `--disable-sync` allein verhinderte nur die
Synchronisierung, nicht die Kontoverbindung; die Option `msEdgeImplicitSignin` und
eine vorab gesetzte Profileinstellung `signin.allowed` wirkten nicht. Bei einer
Profilkopie bleibt ein im Original verbundenes Konto verbunden; `--disable-sync`
verhindert dort das Synchronisieren (für Kopien nicht eigens gemessen).

**Erkennung** (`auth/profiles.py`, ohne Seiteneffekte):

- Profile je Browser aus `Local State` (Anzeigename) und den Profilordnern
  (`Default`, `Profile N`).
- ChatGPT-Anmeldung: In der Cookie-Datenbank des Profils (`Network/Cookies`)
  werden nur **Domains und Namen** gelesen, nie Werte. „Ja“ = Sitzungs-Cookie
  `__Secure-next-auth.session-token` für `chatgpt.com`/`openai.com`; „nein“ =
  keine oder nur sonstige ChatGPT-Cookies; „unbekannt“ = Datei gesperrt (Browser
  mit diesem Profil geöffnet).

**Ablauf der Kopie** (nur interaktiv, einmalig):

1. Hinweis: welches Profil, wohin kopiert wird; ist der Browser offen, dass
   Setup ihn dafür kurz schließt und danach wieder öffnet.
2. Eine Bestätigung: `Enter`/`j` = Kopie anlegen, `n` = Weg überspringen. Der
   Benutzer muss den Browser **nicht** selbst schließen.
3. Ist der Browser offen, schließt Setup genau die Prozesse, die die Sperrdatei
   `lockfile` dieses Datenverzeichnisses halten (Windows Restart Manager,
   `auth/process_control.py`): erst regulär wie beim Abmelden von Windows, nach
   20 Sekunden ohne Reaktion erzwungen. Andere Browser-Instanzen mit eigenem
   Datenverzeichnis (z. B. ein per CDP gesteuertes Profil) bleiben offen.
4. Die Cookie-Prüfung wird wiederholt; ohne ChatGPT-Cookies wird nicht kopiert.
5. Kopiert werden `Local State` und der Profilordner ohne Caches (atomar über
   `<ziel>.partial`). In der Kopie von `Local State` wird nur das kopierte Profil
   geführt und als zuletzt benutzt markiert; der Cookie-Schlüssel bleibt
   unverändert.
6. Der Browser wird wieder geöffnet – auch wenn die Kopie scheitert –, mit
   `--restore-last-session` (zuvor offene Tabs kommen wieder; Edge und Chrome
   melden sich nicht beim Restart Manager zum Neustart an, daher startet Setup
   das Programm selbst).
7. Der Lauf startet die Kopie per CDP und prüft die Anmeldung.

- **Anmeldung:** Startet ein Weg, wird die ChatGPT-Sitzung geprüft. Fehlt sie,
  fordert ein interaktiver Lauf zur Anmeldung in genau diesem Browserfenster
  auf; ohne Interaktion (`--non-interactive`, geplante Läufe) gilt der Weg als
  gescheitert, der Browser wird wieder geschlossen und es geht mit dem nächsten
  Weg weiter.
- **Merken:** Der gewählte Weg wird in die config.yaml eingetragen
  (`user_data_dir`, `kind`, `executable`, bei Bedarf `cdp_port`); ab dem nächsten
  Lauf gilt er als fester Pfad. Wer selbst einen Pfad einträgt, überspringt die
  Suche (auch ein Standardprofil ist als fester Pfad möglich, dann gelten die
  oben genannten Grenzen).
- **Aufräumen:** Ein Browser, den der Lauf selbst gestartet hat und der nicht
  verwendet wird, wird über CDP geschlossen (auch wenn er sich beim Start über
  einen Zwischenprozess neu gestartet hat). Ein bereits laufender Browser wird
  nie geschlossen.
- **Port:** Ist der CDP-Port bei der Suche schon belegt, wird ein freier Port
  verwendet und mit eingetragen.
- **Protokoll:** Jeder Versuch steht mit Grund in der Konsole und im Laufbericht
  unter `sources.chatgpt.detail.browser` (`mode`, gewählter Weg, `attempts`).
- **Entwicklungswerkzeug:** `tools/chatgpt/browser_flow_lab.py` zeigt Erkennung,
  Suchreihenfolge und den echten Ablauf Schritt für Schritt mit Haltepunkten
  (siehe DEVELOPMENT_WORKSPACE.md).

Gemessen am 2026-10-03 auf dem Entwicklungsrechner (Edge 154 und Chrome 154,
beide geöffnet), Erkennung: Edge `Default` „unbekannt“ (Cookies gesperrt),
Edge `Profile 1` ohne ChatGPT-Cookies; Chrome `Default` mit Sitzungs-Cookie,
`Profile 1` mit ChatGPT-Cookies ohne Sitzungs-Cookie, `Profile 2` „unbekannt“.
Nicht-interaktiver Ablauf mit Wegwerf-Ablage: die drei Kopie-Wege wurden
übersprungen (nur interaktiv); Edge und Chrome mit eigenem, leerem Profil
starteten, hatten keine Anmeldung und wurden wieder geschlossen (2 Anfragen,
Kategorie `auth`). Am 2026-10-03 hat der Benutzer mit dem installierten
Programm (`setup`, damals noch „Browser selbst schließen“) eine Kopie seines
Edge-Profils angelegt; die Einrichtung endete erfolgreich. Schließen und
Wiederöffnen über den Restart Manager: mit einem Wegwerf-Edge (eigenes
Datenverzeichnis) geprüft – nur dieser Prozess wurde geschlossen (regulär, 0,4 s),
mit demselben Datenverzeichnis wieder geöffnet und erneut geschlossen.
**Live geprüft am 2026-10-05:** Kopie des echten Edge-Profils, Anmeldung in
der Kopie (`already_logged_in=True`) sowie Wiederöffnen des ursprünglichen
Browsers mit Tabs (Angabe des Benutzers, Testablauf Teil C).
**Nicht live geprüft:** der entsprechende Chrome-Ablauf einschließlich
Cookie-Entschlüsselung in der Kopie (App-gebundene Verschlüsselung ab Chrome 127).

## 2a. Automatische Anmeldung (E-Mail, Passwort, Einmalcode)

Fehlt im verwendeten Browser-Profil eine gültige ChatGPT-Sitzung, meldet sich
der Provider selbst an – auch in geplanten Läufen ohne Interaktion
(`auth/auto_login.py`, eingebunden im `AuthBroker`). Danach geht es wie gewohnt
mit `/api/auth/session` weiter.

**Einrichten** (nur in der `.env` oder Umgebung; aus der config.yaml oder per
`--set` werden Zugangsdaten verworfen, mit Hinweis):

```text
CHATGPT_USERNAME=name@example.org
CHATGPT_PASSWORD=...
CHATGPT_2FA_REFERENCE=chatgpt-konto     # empfohlen: Alias im verschlüsselten Windows-Speicher
# oder: CHATGPT_2FA_SECRET=<Base32 | otpauth://totp/... | verschlüsselter Wert>
```

Der Einmalcode kommt aus den **Two-Factor Tools V4** (unveränderte Kopie unter
`src/two_factor_tools/`, Referenz `REFERENCE.md`). Mit `CHATGPT_2FA_REFERENCE`
liegt das Secret verschlüsselt im Windows Credential Manager/der Registry und
steht nirgends im Klartext (anlegen z. B. mit `save_secret(...)` und
`set_secret_alias(...)` der Two-Factor Tools; dafür braucht es `cryptography`).
`providers.chatgpt.auth.auto_login`: `auto` (Standard, aktiv sobald E-Mail und
Passwort gesetzt sind), `on`, `off`.

**Ablauf** (Zustandsautomat nach der Aufzeichnung des Benutzers vom 2026-10-03,
`ChatExporter/AutomatischerLogin_AblaufImBrowser.md`): Auf jeder Seite wird
erkannt, was zu sehen ist, und genau ein Schritt ausgeführt – „Anmelden“
klicken → E-Mail (`input#mobile-auth-email`) → Passwort
(`auth.openai.com/log-in/password`, `input[name=current-password]`) →
Einmalcode (`auth.openai.com/mfa-challenge/…`, `autocomplete=one-time-code`) →
zurück zu `chatgpt.com`, Sitzung prüfen. Selektoren nutzen stabile Attribute,
keine generierten CSS-Klassen. Der Code wird so gewählt, dass er noch mindestens
10 Sekunden gilt.

**Grenzen und Schutz:**

- Sicherheitsprüfungen (Cloudflare/Turnstile/Captcha) werden **nie** umgangen:
  Die Anmeldung stoppt; interaktiv übernimmt der Benutzer im Browserfenster,
  ohne Interaktion endet der Lauf mit Hinweis.
- Ein Code per E-Mail (Geräte-/E-Mail-Bestätigung) wird nicht automatisiert
  (Übergabe an den Benutzer).
- Das Passwort wird höchstens einmal je Anmeldung abgeschickt, der Einmalcode
  höchstens zweimal. Derselbe Schritt wird frühestens nach 10 s wiederholt (die
  Seite bekommt Zeit, auf den Klick zu reagieren), eine Wiederholung des
  Einmalcodes nimmt immer einen neuen Code. Lehnt die Seite die Zugangsdaten ab, wird das in
  `<storage>/.storage/auth/auto_login_block.json` vermerkt (Zeitpunkt, Grund und ein
  12-stelliger Fingerabdruck – kein Passwort); weitere Läufe versuchen es erst
  wieder, wenn sich E-Mail oder Passwort ändern oder nach `chatexporter chatgpt
  login`. Eine erfolgreiche Anmeldung hebt den Vermerk auf.
- **Eingetragen wird nur auf den erwarteten Seiten:** E-Mail auf `chatgpt.com` oder
  `auth.openai.com`, Passwort und Einmalcode nur auf `auth.openai.com` – immer über
  https, Hostname exakt (keine Subdomains, keine ähnlichen Namen). Geprüft wird beim
  Erkennen der Seite und unmittelbar vor dem Eintragen am Eingabefeld selbst (zu
  welchem Dokument es gehört, damit auch ein eingebetteter fremder Rahmen nichts
  bekommt). Steht ein Anmeldefeld anderswo, endet der Versuch sofort, ohne etwas
  einzutragen, und übergibt an den Benutzer.
- **Menschliches Tempo:** vor jedem Schritt eine zufällige Pause von 1,5–4 s;
  E-Mail, Passwort und Code werden nach einem Klick ins Feld Zeichen für Zeichen
  getippt (60–180 ms Abstand). Kommt beim Tippen nicht alles an, wird der Wert direkt
  gesetzt (ohne ihn auszugeben). Sicherheitsprüfungen werden dadurch nicht umgangen –
  sie beenden den Versuch weiterhin sofort.
- Zugangsdaten und Codes erscheinen in keiner Ausgabe, keinem Laufbericht und
  keinem Spiegel; `config list`/`get` zeigen nur „gesetzt“.

**Browserfenster** (`providers.chatgpt.browser.window`, nur für einen vom
ChatExporter gestarteten Browser): `offscreen` (Standard) startet das Fenster
außerhalb des sichtbaren Bildschirms, `minimized` minimiert es nach dem Start,
`visible` zeigt es immer. Gezeigt wird es, wenn der Benutzer etwas tun muss – bei
der Anmeldung von Hand (auch wenn die automatische Anmeldung an einer
Sicherheitsprüfung oder einem Code per E-Mail stoppt) und bei `login
--schrittweise`; nach erfolgreicher Anmeldung wird es wieder verborgen. Bleibt der
Browser nach dem Lauf offen (`leave_browser_running`), wird er auf den Bildschirm
gelegt und minimiert, nie unsichtbar zurückgelassen. Ein Browser, der schon lief,
wird nie verborgen. Gemessen am 2026-10-04 (Edge, lokale Nachbildung der
Anmeldung): außerhalb des Bildschirms kein Aufblitzen beim Start und Anmeldung in
rund 2 s; minimiert rund 6 s (Edge bremst minimierte Fenster; die Optionen gegen das
Bremsen änderten nichts). Zeigen aus dem verborgenen Zustand mit echtem Edge auf
chatgpt.com geprüft (Benutzer sah die normale ChatGPT-Seite).

**Prüfen:** `chatexporter chatgpt login` prüft die Sitzung im eingetragenen
Profil und meldet sich bei Bedarf an; `--profil <leerer Ordner>` testet die
Anmeldung von Grund auf in einem eigenen, leeren Profil; `--schrittweise` hält vor
jedem Schritt an (Fenster sichtbar, Meldung „Erkannt: … auf <Seite> / Nächster
Schritt: …“, weiter mit ENTER, `a` bricht ab, ohne weiter etwas einzutragen). Ausgabe: Schritte,
Ergebnis, besuchte Seiten (Host und Pfad, ohne Query), Konto (maskiert), Anzahl
der Anfragen.

Belegt am 2026-10-03: 13 Tests (Einmalcode inkl. RFC-6238-Testvektor,
Zugangsdaten-Quellen, Maskierung, Zustandsautomat, Sperrschutz, Broker) sowie
2 Ende-zu-Ende-Tests mit echtem Edge (headless) gegen eine **lokale Nachbildung**
der Anmeldeseiten mit echtem TOTP.

Live geprüft am 2026-10-04 vom Benutzer gegen chatgpt.com (`chatgpt login
--profil <leerer Ordner>`): Anmeldung erfolgreich, Schritte Anmelde-Button →
E-Mail → Passwort → Einmalcode → ChatGPT, 3 Anfragen. Befund dabei: Der
Einmalcode wurde zweimal abgeschickt (derselbe Code, die Code-Seite war nach dem
Klick noch kurz sichtbar); behoben durch die 10-s-Wartezeit, Test
`test_slow_code_page_gets_the_code_only_once`. Zweiter Live-Test am 2026-10-04
mit neuem leeren Profil: erfolgreich, Einmalcode nur noch einmal eingetragen.
Live am 2026-10-05 mit `--schrittweise` (neues leeres Profil, Seitenprüfung,
menschliches Tempo): vier Halte mit jeweils passender Seitenangabe, Anmeldung
erfolgreich. Ein erster Versuch davor brach fälschlich mit „nicht erwartete Seite“
ab, weil die Seitenadresse während des Seitenwechsels veraltet gelesen wurde
(behoben, siehe CHANGELOG).

## 3. Ablauf eines Updates

1. **Listing** – welche Konversationen gibt es, und wann wurden sie geändert?
2. **Planung** – Vergleich mit dem lokalen Index. Reihenfolge: neue
   Konversationen, dann geänderte, dann unvollständige, zuletzt reine
   Datei-Nachläufe.
3. **Abruf und Commit** je Konversation: Graph laden und validieren, Envelope
   atomar schreiben, danach sofort die zugehörigen Dateien.
4. **Grenzprüfung** an der Änderungsgrenze auf Turn-Ebene (Abschnitt 4.3).
5. **Quarantäne-Review** am Ende (nur wenn aktiviert, max. 3 Einträge je Lauf).
6. **Laufbericht**: im Updater-Lauf der gemeinsame, im Einzellauf ein eigener
   (Schema 4).

Nach einem Rate-Limit entfallen Grenzprüfung und Quarantäne-Review, weil sie
sofort wieder abrufen würden.

**Neuanmeldung mitten im Lauf** (`api/client.py`, `contract.reauthenticator`):
Antwortet ChatGPT während des Laufs mit HTTP 401, wird die Anmeldung im selben
Browser erneuert – erst die Sitzung neu geprüft (frischer Token aus
`/api/auth/session`), fehlt sie, die automatische Anmeldung (Abschnitt 2a), nur mit
Interaktion auch die Anmeldung von Hand (Fenster wird gezeigt). Danach wird genau
diese Anfrage einmal wiederholt und der Lauf geht weiter. Höchstens 2 Erneuerungen
je Lauf; scheitert die Erneuerung, endet der Lauf wie bisher mit dem 401 (Abbruch,
Grund im Laufbericht). Nur 401 löst das aus – 403 nicht (kann auch eine
Sicherheitsprüfung oder ein gesperrter Inhalt sein) und bleibt ein Abbruch.
Laufbericht: `reauth` (je Erneuerung Endpunkt, Erfolg, Grund; nie Tokens).
Live-Prüfwerkzeug: `tools/chatgpt/reauth_check.py` (6 Anfragen, ohne `--live` nur
Plan). Live geprüft am 2026-10-05: echtes 401 mit ungültigem Token, Erneuerung über
den Browser, Wiederholung erfolgreich.

### Planungsaktionen

| Aktion | Wann |
| --- | --- |
| `FETCH_FULL` | neu, Signatur geändert (Titel, `update_time`, Archiv-/Stern-/Pin-Status), lokal unvollständig oder Integritätsfehler |
| `FETCH_FILES_ONLY` | Graph vollständig, nur Dateien fehlen (spart den teuren Konversationsabruf) |
| `SKIP` | unverändert und vollständig |
| `MISSING_REMOTE` | lokal vorhanden, aber in keinem Listing – **nur** bei tatsächlich vollständigem Listing (`full`, oder `auto` nach Wechsel) |
| `QUARANTINED`, `EXCLUDED` | aussortiert bzw. manuell ausgeschlossen |

## 4. Listing-Modi

| Modus | Abruf | Kosten | Erfasst |
| --- | --- | --- | --- |
| `auto` (**Standard**) | kein lokaler ChatGPT-Bestand → `full` (Erstabruf); sonst `recent`, und wenn dessen Änderungsgrenze **nicht bestätigt** ist, im selben Lauf zusätzlich `full` | im Alltag **eine** Anfrage, sonst wie `full` plus die `recent`-Seiten | wie `full`, sobald nötig |
| `full` | alle Seiten der aktiven **und** archivierten Konversationen (`limit=100`) | eine Anfrage je 100 Konversationen (bei ~3.100 Chats über 30) | alles, inkl. verschwundener und archivierter |
| `recent` | aktive Konversationen, sortiert nach `order=updated`, ab Seite 1 | in der Regel **eine** Anfrage | die zuletzt geänderten; wechselt **nie** selbst auf `full`, warnt nur |

Ohne Angabe gilt `sync.listing_mode` aus der Config, Default `auto`. Pro Lauf
überschreibbar mit `--listing-mode auto|full|recent`. Im Laufbericht steht
`detail.listing` mit `mode`, `effective` (tatsächlich verwendet),
bei `auto` gegebenenfalls `escalation` (Grund des Wechsels) und `recent`
(Ergebnis des vorherigen Versuchs).

`auto` wechselt auf `full`, wenn einer dieser Fälle eintritt:

| Grund (`escalation`) | Typische Ursache |
| --- | --- |
| `initial` | noch kein lokaler Bestand (Erstabruf) |
| `cap_reached` | mehr als `recent_max_pages` × `listing_limit` (derzeit 300) geänderte Chats, z. B. ein unterbrochener Erstabruf oder lange kein Update |
| `out_of_order_change` | hinter der Grenze taucht noch ein neuer oder inhaltlich geänderter Chat auf; der lokale Stand hat Lücken, z. B. nach einem vom Rate-Limit abgebrochenen Lauf |
| `recent_local_missing` | ein lokal aktiver Chat, der neuer ist als die Grenze, fehlt im Listing, wurde also archiviert oder gelöscht |
| `order_violation` | das Listing ist nicht absteigend nach `update_time` sortiert (Annahme verletzt) |
| `local_files_missing` | Konversationen wurden lokal (im Storage) gelöscht: Der Index verwies noch auf ihre Dateien. Sie stehen in `<status_registry>/lost_conversations.json`, bis sie wieder geladen sind (auch über einen abgebrochenen Lauf hinweg); `detail.listing.local_missing` nennt bis zu 20 IDs |

`recent` allein erfasst **nicht**: archivierte Konversationen und Wechsel des
Archiv-Status, auf dem Server gelöschte Konversationen (`MISSING_REMOTE`),
lokal unvollständige Altbestände außerhalb der geholten Seiten. `auto` fängt
davon ab, was die Prüfungen unten sichtbar machen. Alles Übrige deckt nur ein
gelegentlicher `full`-Lauf ab.

### 4.1 Wann gilt ein Chat als geändert?

Das Listing liefert je Chat nur Metadaten. `mapping` und `current_node` sind
dort immer `null` (API_CONTRACT). Aus ihnen wird eine von vier Einstufungen:

| Einstufung | Bedingung | Folge |
| --- | --- | --- |
| `new` | lokal unbekannt | wird geladen |
| `content` | `update_time` ist **neuer** als der gespeicherte Stand (siehe unten) | wird geladen |
| `meta` | `update_time` gleich, aber Titel, Stern, Pin oder Archiv-Status geändert | wird geladen, verschiebt die Grenze **nicht** |
| `same` | alles gleich | wird übersprungen, sofern lokal vollständig und die Integrität ok ist |

**Gespeicherter Stand = Listing- UND Detailzeit.** Das Listing führt
`update_time` teils verzögert. Beim Abruf lag die Listing-Zeit bei 575 von
3098 Chats **vor** der Detailzeit, nie danach (Auswertung 2026-10-01): meist
unter 1 Minute, in 15 Fällen Stunden bis Wochen. Zieht das Listing später
nach, ist das keine Änderung, denn der gespeicherte Inhalt hat diesen Stand
bereits. Ein Chat gilt deshalb nur als geändert, wenn die Listing-Zeit neuer
ist als **beide** gespeicherten Werte: `remote_updated_at`, die Listing-Zeit
beim Abruf, und `raw_update_time`, die Detailzeit beim Abruf (seit
2026-10-01 im Index). Belegter Auslöser war Chat `6a83f3cb…` an Position 100:
lokal `…29.791121`, Detailantwort `…29.833364`; das Listing zog auf
`…833364` nach.

Zeitfelder werden als **Zeitpunkt** verglichen, nicht als Text. Das Listing
liefert `update_time` in wechselnder Schreibweise, mit oder ohne
Nachkommastellen, mit `Z` oder `+00:00`. Im Bestand vom 2026-10-01 hatten
198 von 3098 Einträgen keine Nachkommastellen.

Eine fünfte Einstufung `ignored` erhalten Chats, die **bewusst nicht
synchron** gehalten werden, weil sie manuell ausgeschlossen sind oder in
Quarantäne stehen. Sie werden gelistet und in der Planung als
`EXCLUDED`/`QUARANTINED` geführt. Die Grenze bilden oder verletzen sie aber
nicht: Ein solcher Chat ist lokal nie vorhanden und sähe sonst bei jedem Lauf
wie ein „neuer Chat hinter der Grenze“ aus.

Lokal kommt zusätzlich die Integrität hinzu. Ist der gespeicherte Hash von
`raw` falsch oder fehlen Teile, wird der Chat unabhängig vom Listing neu
geladen.

### 4.2 Wie wird die Änderungsgrenze bestimmt und bestätigt?

Der Server sortiert nach `update_time` absteigend. Geänderte Chats bilden
daher einen zusammenhängenden Anfang der Liste. Die **Grenze** ist der erste
Eintrag, dessen `update_time` dem lokalen Stand entspricht (`same` oder
`meta`). Sie gilt nur als **bestätigt**, wenn alle vier Prüfungen bestehen:

1. **Bestätigung:** Ab der Grenze liegen mindestens
   `sync.recent_confirm_unchanged` (Default 3) Einträge mit unveränderter
   `update_time` vor, die Grenze eingeschlossen. Liegt die Grenze am
   Seitenende, wird dafür die nächste Seite geholt.
2. **Zusammenhang:** In **allen geholten Einträgen hinter der Grenze** taucht
   kein `new`/`content` mehr auf. Alle Einträge der geholten Seiten werden
   ohnehin geplant, also auch Nachzügler hinter der Grenze.
3. **Sortierung:** `update_time` ist über alle geholten Einträge nicht
   steigend.
4. **Querprobe:** Jeder lokal aktive Chat, dessen `update_time` neuer ist als
   die Grenze, muss im Listing vorkommen.

**Diagnose:** `detail.listing.entries` (bei `auto` nach einem Wechsel:
`detail.listing.recent.entries`) hält jeden gelisteten Eintrag mit Position,
Einstufung und beiden Zeitstempeln fest. `anomalies` nennt die IDs, die die
Grenze verletzt haben; die Konsole zeigt sie vor einem Wechsel auf `full` an.
Diese Diagnose wird **vor** dem Voll-Abruf gesichert und bleibt deshalb auch
bei einem Abbruch (Strg+C, Rate-Limit) erhalten; `full_completed: false`
kennzeichnet das.

Einträge hinter der letzten geholten Seite werden nicht einzeln geprüft; das
wäre nur mit einem Voll-Abruf möglich. Die Prüfungen 2 bis 4 und die
Grenzprüfung (4.3) decken die realistischen Ursachen für Lücken ab.

### 4.3 Grenzprüfung auf Turn-Ebene

Die Einstufung in 4.1 vertraut darauf, dass `update_time` jede inhaltliche
Änderung anzeigt. Belegen lässt sich das nur mit einem Detailabruf. Die
Grenzprüfung (`sync.verify_boundary`, Default an) prüft deshalb die Chats, die
die Grenze bestätigen, zusätzlich **inhaltlich**:

1. Kandidaten sind die als unverändert eingestuften Chats in
   Listing-Reihenfolge, also beginnend direkt an der Grenze.
2. Jeder Kandidat wird einzeln abgerufen und verglichen: aktueller Knoten
   (letzter Turn), Menge aller Knoten-IDs (damit auch die Turn-Anzahl) und
   `update_time` der Detailantwort. Ein Hash über das ganze JSON wird bewusst
   nicht verwendet, weil flüchtige Felder Fehlalarme erzeugen würden.
3. **Gleich:** Der Chat zählt zur Folge der bestätigten Chats.
4. **Abweichend:** Der neue Stand wird sofort aus der schon geladenen
   Detailantwort gespeichert (kein zweiter Abruf), die Folge beginnt von vorn,
   und der **nächste** Chat wird zusätzlich geprüft.
5. Fertig, sobald `sync.recent_confirm_unchanged` (Default 3) Chats **in
   Folge** unverändert sind. Dann gilt die Grenze als inhaltlich abgesichert
   (`confirmed`).

Stimmt `update_time` wie erwartet, ändert sich am Ergebnis nichts. Es kostet
genau 3 Detailabrufe je Lauf. Nur wenn `update_time` eine Änderung nicht
anzeigt, greift die Absicherung. Die Prüfung endet vorher nur durch ein
Rate-Limit, durch `sync.verify_max_requests` (Default `0` = unbegrenzt) oder
wenn keine Kandidaten mehr übrig sind. Diese Fälle stehen im Laufbericht mit
`confirmed: false` und einem Grund in `stopped`.

Im Laufbericht:

- `verification`: `required`, `checked`, `matched`, `mismatches`,
  `consecutive_ok`, `confirmed`, `requests`, `stopped`, `checked_ids`
- `stats`: `verified_unchanged`, `verify_mismatches`, `verify_requests`
  und je Abweichung ein Eintrag in `verify_events` (Knoten und `update_time`
  lokal gegenüber Server)

Die Prüfung läuft auch bei `full` (dann an der Grenze in der
Standard-Sortierung des aktiven Listings).

### 4.4 Anfragezählung

Jeder Lauf zählt **jede an ChatGPT gesendete Anfrage**. Gezählt wird auch,
wenn eine Anfrage fehlschlägt; HTTP 429 wird zusätzlich getrennt geführt. Die
Einordnung nach Endpunkt:

| Kategorie | Endpunkt |
| --- | --- |
| `auth` | `/api/auth/session`, `/backend-api/me` (Sitzungsprüfung) |
| `listing` | `/backend-api/conversations` |
| `conversation` | `/backend-api/conversation/<id>` (inkl. Grenzprüfung) |
| `textdocs` | `/backend-api/conversation/<id>/textdocs` |
| `file_metadata` / `file_ticket` | `/backend-api/files/<id>` bzw. `…/download` |
| `file_content` | signierte Download-URL |
| `other` | alles Übrige |

Im Laufbericht: `requests` mit `total`, `by_category`, `rate_limited_total`
und `rate_limited_by_category`. Außerdem steht `stats.requests_total` im
Vertragsergebnis und in den Gesamtwerten (`totals.requests_total`) des
Laufberichts. Die Konsole zeigt die Summe am Ende des Laufs.

Gemessen ist ein eigenes Kontingent nur für `listing` und `conversation`. Ob
die übrigen Endpunkte eigene Kontingente haben, ist nicht untersucht; die
Zählung sammelt dafür die Daten.

### 4.5 Einordnung

Einordnung: Dass die ChatGPT-Weboberfläche selbst mit `order=updated` lädt,
stammt aus einer Beobachtung in den Browser-DevTools (2026-09-30), nicht aus
einer Messreihe. Ebenso ist die Wiederauffüllung des Listing-Kontingents von
etwa einer Anfrage pro Minute eine Beobachtung. Ein Live-Lauf im Modus
`recent` steht noch aus.

## 5. Rate-Limit und Fehlerbudgets

- **Konversationsabruf**: gemessene Kapazität rund 210 Anfragen, Wiederauffüllung
  rund 0,97 Anfragen pro Minute (Forschungsakte 2026-09-21). Beim Limit wird
  der Lauf **regulär** beendet (`sync.rate_limit_wait_minutes: 0`) oder nach
  der Wartezeit fortgesetzt. Fortgesetzt werden nur die noch offenen Einträge.
  Ein Rate-Limit zählt nicht gegen das Fehlerbudget.
- **Listing**: eigenes Kontingent. Transiente Transportfehler werden bis zu
  3-mal wiederholt (5 s, 15 s, 30 s). HTTP 429 wird wie ein Rate-Limit
  behandelt.
- **Budgets**: `max_errors_per_run` (Default 5) für Konversationen,
  `max_file_errors_per_run` (Default 50) für Dateien.
- **Sofortiger Abbruch**: HTTP 401/403 (Sitzung neu prüfen) und ein
  geschlossener Browser. Der Lauf endet dann kontrolliert mit Laufbericht.

## 6. Dateien

Dateien landen in `library/files/<file_id>/` bzw. `library/audio/<file_id>/`
(`content.<ext>` + `metadata.json` mit Herkunft). Jede Datei wird nur einmal
geladen, auch wenn mehrere Konversationen sie referenzieren. Dateien aus
Custom GPTs werden mit `gizmo_id` angefordert.

Antwortet der Server mit HTTP 404, wird die Datei **einmal** als `UNAVAILABLE`
in `file_status.json` vermerkt und nie wieder angefragt. Die Konversation gilt
dann trotzdem als dateivollständig.

## 7. Quarantäne und manuelle Ausschlüsse

- **Quarantäne** (`sync.quarantine.enabled`, Default aus): Ein Eintrag wird
  erst aussortiert, wenn er in mehreren getrennten Läufen mit einer echten
  Serverantwort scheitert (`min_failed_runs`, `min_age_hours`). Außerdem muss
  im selben Lauf etwas anderes funktioniert haben. Nach `review_after_days`
  wird der Eintrag erneut geprüft. Ablage: `status_registry/quarantine.json`.
- **Manuelle Ausschlüsse** (`sync.manual_exclusions`): sofort und bewusst
  übersprungen, jeweils mit Begründung.

## 8. Import

- `import-data`: übernimmt einen OpenAI-Kontodatenexport als **bewusst
  unvollständige** Datensätze (`acquisition.source = imported_data`,
  `json_complete = false`). Das nächste Update lädt sie vollständig über die
  API nach.

Exporte (Markdown/JSON) gehören nicht zum Provider: Sie erzeugt der
**Exporter** (`chatexporter export`) aus dem Raw Storage, siehe
[BEFEHLE.md](../BEFEHLE.md).

## 9. Forschungsgrundlagen

Die Verträge zur ChatGPT-Backend-API (Endpunkte, Parameter, Fehlerbilder,
Evidenzstatus) liegen unverändert unter
Forschungsverträge im Archiv
(aus pre-5 übernommen). Maßgeblich
für Aussagen zur API ist deren Evidenzstatus.
