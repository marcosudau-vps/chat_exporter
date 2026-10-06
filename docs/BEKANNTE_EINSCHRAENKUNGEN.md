# Bekannte Einschränkungen (Stand 0.0.1)

Was das Programm bewusst nicht kann oder wo es Grenzen hat. Alles hier ist
belegt (Code, Tests oder Messung); Fundstellen in Klammern.

## Plattform und Betrieb

- **Nur Windows** (10/11), Installation pro Benutzer. Das installierte Programm
  braucht kein Python (BUILD.md).
- **Geplante Läufe** (Windows-Aufgabenplanung) laufen nur, solange der Benutzer
  angemeldet ist. Ein verpasster Lauf wird nachgeholt, sobald das möglich ist
  (`start_when_available`; [task_scheduler/TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md)).
- **Start beim Hochfahren** (`task create --startup`) braucht
  Administratorrechte. Ohne sie lehnt Windows ab; das Programm meldet das
  verständlich und legt nichts an (geprüft am 2026-10-05). Mit
  Administratorrechten funktioniert es (geprüft in der Windows Sandbox). Ohne
  Administratorrechte `--logon` verwenden.
- Bedienung und Meldungen sind deutsch; Konsolenausgaben teils ohne Umlaute.

## ChatGPT

- **Browser nötig:** Microsoft Edge, Google Chrome oder Chrome for Testing (wird
  nach Rückfrage heruntergeladen). Abgerufen wird über den Browser, nicht über
  eine öffentliche Programmierschnittstelle.
- **Automatische Anmeldung** gibt es nur für Konten mit E-Mail und Passwort,
  optional mit Einmalcode aus einer Authenticator-App (TOTP). Nicht
  automatisiert werden:
  - Anmeldung über Google, Microsoft oder Apple,
  - Passkeys,
  - Codes per E-Mail,
  - Sicherheitsprüfungen wie Captchas; sie werden nie umgangen.

  In diesen Fällen hält die Anmeldung an. Mit dem Benutzer am Rechner zeigt das
  Programm dann das Browserfenster, ohne Interaktion endet der Lauf mit Hinweis
  ([providers/CHATGPT.md](providers/CHATGPT.md), Abschnitt 2a).
- **Neuanmeldung mitten im Lauf** nur bei HTTP 401, höchstens zweimal je Lauf.
  HTTP 403 führt weiter zum Abbruch, weil es auch eine Sicherheitsprüfung oder
  ein gesperrter Inhalt sein kann.
- **Rate-Limits:** Der Erstabruf eines großen Kontos braucht mehrere Läufe. Das
  Programm setzt per geplanter Fortsetzung selbst fort.
- **Gelöschte und archivierte Chats:** Das sparsame Listing (`recent`, Standard
  im Modus `auto`) erkennt auf dem **Server** gelöschte Chats und Wechsel des
  Archiv-Status nicht. Das geschieht erst bei einem vollständigen Listing, das
  `auto` bei Bedarf von selbst wählt. Lokal gelöschte Dateien werden dagegen
  immer erkannt und neu geladen ([providers/CHATGPT.md](providers/CHATGPT.md),
  Abschnitt 4).
- **Profilkopie von Chrome:** Ob Chrome die Cookies einer Profilkopie
  entschlüsseln kann (app-gebundene Verschlüsselung ab Chrome 127), ist nicht
  geprüft. Mit Edge wurde eine Profilkopie am 2026-10-05 mit Anmeldung in der
  Kopie sowie Wiederöffnen des ursprünglichen Browsers mit Tabs erfolgreich
  geprüft (Testablauf Teil C); die Suche nimmt einen Weg nur mit
  vorhandener ChatGPT-Anmeldung an.

## Daten und Storage

- **Zustand an die Registry gebunden:** Zähler und „erster Abruf vollständig“
  eines Storages liegen in der Registry (Beschluss F6,
  [STORAGE_KONZEPT.md](STORAGE_KONZEPT.md)). Wird ein Storage auf einen anderen
  Rechner gebracht, beginnen diese Werte neu. Die Daten selbst sind vollständig im
  Storage-Ordner.
- **Daten älterer Testprogramme** (vor 0.0.1, Home-Ordner `~/.chat_exporter`)
  werden nicht von selbst übernommen. Der Weg von Hand steht in
  [GETTING_STARTED.md](GETTING_STARTED.md). Deren Aufgaben (Eigentümer
  `chatexporter`) entfernt auch die Deinstallation nicht von selbst.
- **Ein nicht leerer, fremder Ordner** wird nicht als Storage verwendet. Gewählt
  werden kann ein leerer oder neuer Ordner oder ein bestehender Storage.
- **Entwicklungsmodus** (`dev_mode`) lädt absichtlich nur einen Teil der Daten
  und ist nicht für den Alltag gedacht.

## Weitere Quellen (OpenCode, Codex, Claude Code)

- Sie lesen nur lokale Daten dieses Rechners. Dafür muss das jeweilige Programm
  bzw. sein Datenordner vorhanden sein
  ([providers/LOKALE_QUELLEN.md](providers/LOKALE_QUELLEN.md)).
