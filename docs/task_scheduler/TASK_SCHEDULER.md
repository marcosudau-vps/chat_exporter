# Zeitplanung (Task Scheduler)

Mit der Zeitplanung laufen ChatExporter-Befehle automatisch, zum Beispiel
einmal täglich `chatexporter update`. Sie verwaltet dafür **Aufgaben der
Windows-Aufgabenplanung**. Die Windows-Seite (COM-Zugriff, stabile IDs,
State-Dateien) übernimmt das Script `tools/task_scheduler/scheduler_manager.py`
(PyTaskManager V2). ChatExporter ergänzt Befehlsaufbau, Standardwerte,
Eingabeprüfung, gespeicherten Plan und Ausgabe.

Stand: pre-6, durch Tests belegt (siehe Abschnitt 9). Nur unter Windows.

## 1. Voraussetzungen

| Voraussetzung | Hinweis |
| --- | --- |
| Windows | die Aufgabenplanung ist Windows-spezifisch |
| `pywin32` in der venv | `pip install pywin32` oder `pip install -e .\ChatExporter_Gen4_pre-6[scheduler]` |
| `tools/task_scheduler/scheduler_manager.py` im Codeordner | wird beim ersten Zugriff per Dateipfad geladen; bei einer Installation ohne `-e` Pfad über `task_scheduler.manager_script` angeben |
| `config.yaml` | geplante Befehle zeigen fest auf die verwendete Datei (`--config`); fehlt sie, wird die Vorlage angelegt |

Hilfe und Eingabeprüfung funktionieren auch ohne pywin32; erst der Zugriff auf
die Aufgabenplanung braucht es.

## 2. Was ist eine Aufgabe?

Eine Aufgabe führt zu den eingestellten Zeiten diesen Befehl aus:

```text
<python> -m chatexporter --config <config.yaml> --storage <storage> <befehl ...>
```

- **Jede Aufgabe gehört einem Storage** (dem beim Anlegen gewählten): Der Befehl
  enthält `--storage <storage>`, die Eigentümer-Kennung ist
  `chatexporter-<erste 8 Zeichen der Storage-ID>` (sofern `task_scheduler.owner`
  nicht ausdrücklich gesetzt ist), der lokale State liegt in
  `<storage>/.storage/tasks_sched.json`. `task list` zeigt nur die Aufgaben des
  gewählten Storages; mit `--storage` werden die eines anderen verwaltet.

- `<python>` ist standardmäßig `workspace\.venv\Scripts\python.exe`
  (`bootstrap.venv_path`), sonst der aktuelle Interpreter.
- Im gebauten Programm (Installation) ruft die Aufgabe direkt
  `chatexporter.exe --config <config.yaml> --storage <storage> <befehl ...>` auf (ohne
  `-m chatexporter`), und `scheduler_manager.py` kommt aus dem Programmordner
  (`_internal\tools\task_scheduler\`). Ein ausdrücklich gesetztes
  `task_scheduler.python` bleibt ein Python-Aufruf mit `-m chatexporter`.
- Arbeitsordner ist der Ordner der `config.yaml` (`workspace/`).
- `<befehl>` ist einer der planbaren Befehle: `update`, `index`, `check`,
  `cleanup`, `status`, `export`, `config`, `chatgpt`, `opencode`, `codex`, `claude`. `task` selbst
  ist nicht planbar. Der geplante Lauf steht wie jeder andere Aufruf im
  [Befehlsprotokoll](../BEFEHLE.md).
- Jede Aufgabe hat einen **Anzeigenamen**, einen **Kurzname** (slug, aus dem
  Namen gebildet) und eine **technische ID** (`tsk_…`). Alle drei lassen sich
  als Referenz verwenden. Die ID bleibt beim Ändern und Umbenennen gleich.
- Die Aufgabe läuft unter dem angemeldeten Benutzer („nur ausführen, wenn der
  Benutzer angemeldet ist“). Verpasste Läufe (Rechner aus) werden
  standardmäßig nachgeholt (`start_when_available`).

Für ChatGPT gilt: Der Standardbefehl enthält `--non-interactive`, damit im
geplanten Lauf keine interaktive Anmeldung gestartet wird
([BEFEHLE.md](../BEFEHLE.md)). Ob die ChatGPT-Anmeldung für einen unbeaufsichtigten
Lauf ausreicht, ist hier **nicht** getestet; der geplante Befehl selbst
(`status`) ist belegt.

## 3. Schnellstart

```powershell
# täglich um 03:00 alle Quellen aktualisieren (Standardbefehl und -zeit)
chatexporter task create "Täglicher Update"

# nur Codex und Claude, werktags 07:30
chatexporter task create "Lokale Quellen" --command "update --source codex --source claude" --weekly 07:30 --days mo,di,mi,do,fr

chatexporter task list
chatexporter task get taeglicher-update
chatexporter task update taeglicher-update --daily 04:15
chatexporter task pause taeglicher-update
chatexporter task resume taeglicher-update
chatexporter task delete taeglicher-update
```

Dieselben Befehle gibt es als `chatexporter-task …` und im Menü (Punkte 12–16).

## 4. Befehle

Globale Optionen (vor oder nach dem Befehl): `--config`, `--folder`, `--owner`,
`--state-file`, `--global-state-file`, `--python`, `--json`.
`--json` gibt `get`, `list`, `create`, `update`, `delete`, `pause` und `resume`
maschinenlesbar aus.

| Befehl | Wirkung |
| --- | --- |
| `task create NAME` | legt eine Aufgabe an; ohne Angaben gelten die Standardwerte aus `task_scheduler.defaults`. Existiert der Kurzname schon, bricht der Befehl ab |
| `task get REF` | zeigt eine Aufgabe: Zustand, Befehl, Zeitplan, nächster/letzter Lauf, letztes Ergebnis |
| `task list` | alle Aufgaben dieses Ordners und Eigentümers als Tabelle |
| `task update REF` | ändert nur die angegebenen Felder; ID und Kurzname bleiben, eine pausierte Aufgabe bleibt pausiert |
| `task delete REF` | löscht die Aufgabe in Windows und in den State-Dateien; fragt nach, außer mit `-y/--yes` |
| `task delete --all` | löscht alle Aufgaben des gewählten Storages (Eigentümer); fragt nach, außer mit `-y/--yes`. Die Aufgaben **aller** bekannten Storages entfernt `chatexporter uninstall --remove-tasks` |
| `task pause REF` | deaktiviert die Aufgabe (sie bleibt erhalten, läuft aber nicht) |
| `task resume REF` | aktiviert eine pausierte Aufgabe wieder |

### Optionen von `create` und `update`

| Option | Bedeutung |
| --- | --- |
| `--command "…"` | Befehl ohne `chatexporter`, z. B. `"update --source chatgpt"` |
| `--description` | Beschreibung in der Aufgabenplanung |
| `--slug` (`create`) | Kurzname statt des aus dem Namen gebildeten |
| `--name` (`update`) | neuer Anzeigename |
| `--paused` (`create`) | pausiert anlegen |
| `--daily HH:MM` | täglich (`--every N` = alle N Tage) |
| `--weekly HH:MM --days mo,mi,fr` | wöchentlich (`--every N` = alle N Wochen); Tage: `mo di mi do fr sa so` (auch englisch/ausgeschrieben) |
| `--once "JJJJ-MM-TT HH:MM"` | einmalig |
| `--logon [--delay SEK]` | bei Anmeldung |
| `--startup [--delay SEK]` | bei Systemstart (braucht Administratorrechte) |
| `--max-runtime MIN` | Zeitlimit je Lauf |
| `--wake-to-run` / `--no-wake-to-run` | Rechner dafür wecken |
| `--allow-on-battery` / `--no-allow-on-battery` | im Akkubetrieb starten |
| `--start-when-available` / `--no-start-when-available` | verpassten Lauf nachholen |
| `--hidden` / `--no-hidden` | Aufgabe in der Aufgabenplanung verbergen |
| `--multiple-instances parallel\|queue\|ignore_new\|stop_existing` | wenn der vorige Lauf noch läuft |

Genau ein Trigger je Aufgabe. Bei `update` ersetzt ein angegebener Trigger den
bisherigen; ohne Triggerangabe bleibt er. Uhrzeiten sind Ortszeit.

### Exitcodes

| Code | Bedeutung |
| --- | --- |
| `0` | ok |
| `1` | fachlicher Fehler: Aufgabe nicht gefunden oder existiert schon, ungültige Eingabe, Löschen abgebrochen |
| `2` | Einrichtung: config.yaml nicht ladbar, kein Windows/pywin32, `scheduler_manager.py` fehlt |

## 5. Konfiguration

Abschnitt `task_scheduler` der `config.yaml`, gelesen über die gemeinsame
Konfiguration ([KONFIGURATION.md](../KONFIGURATION.md)). Vorrang wie überall:
CLI-Werte > Umgebung > `.env` > `config.yaml` > Standard. Ändern zum Beispiel mit
`chatexporter config set task_scheduler.defaults.command "update --source codex"`.

| Schlüssel | Default | Umgebungsvariable | Bedeutung |
| --- | --- | --- | --- |
| `folder` | `\ChatExporter` | `CHATEXPORTER_TASK_FOLDER` | Ordner in der Aufgabenplanung; eigene Aufgaben liegen getrennt von allen anderen |
| `owner` | `chatexporter` | `CHATEXPORTER_TASK_OWNER` | Eigentümer-Kennung; `list` zeigt nur diese Aufgaben |
| `state_file` | `<storage>/.storage/tasks_sched.json` | `CHATEXPORTER_TASK_STATE_FILE` | lokaler State im Storage |
| `global_state_file` | `%LOCALAPPDATA%\PyTaskManager\tasks_sched.json` | `CHATEXPORTER_TASK_GLOBAL_STATE` | globaler State des PyTaskManagers |
| `python` | `<bootstrap.venv_path>\Scripts\python.exe`, sonst aktueller Interpreter | `CHATEXPORTER_TASK_PYTHON` | Interpreter der geplanten Befehle |
| `manager_script` | `<Codeordner>/tools/task_scheduler/scheduler_manager.py` | `CHATEXPORTER_TASK_MANAGER_SCRIPT` | Ort des PyTaskManager-Scripts |
| `defaults.command` | `update --non-interactive` | `CHATEXPORTER_TASK_COMMAND` | Befehl neuer Aufgaben |
| `defaults.trigger` | `{type: daily, at: "03:00"}` | – | Zeitplan neuer Aufgaben (`daily`, `weekly`, `once`, `logon`, `startup`) |
| `defaults.description` | leer | – | Beschreibung neuer Aufgaben (leer = „ChatExporter: <befehl>“) |
| `defaults.max_runtime_minutes` | `360` | – | Zeitlimit je Lauf |
| `defaults.start_when_available` | `true` | – | verpassten Lauf nachholen |
| `defaults.allow_on_battery` | `true` | – | im Akkubetrieb starten |
| `defaults.wake_to_run` | `false` | – | Rechner wecken |
| `defaults.multiple_instances` | `ignore_new` | – | Verhalten bei noch laufendem Vorlauf |
| `defaults.hidden` | `false` | – | Aufgabe verbergen |

```yaml
task_scheduler:
  folder: '\ChatExporter'
  owner: chatexporter
  defaults:
    command: update --non-interactive
    trigger: {type: daily, at: "03:00"}
    max_runtime_minutes: 360
```

Die `defaults` gelten beim Anlegen und werden **in der Aufgabe gespeichert**.
Spätere Änderungen der Defaults wirken nicht auf bestehende Aufgaben.

## 5a. Automatische Fortsetzung nach einem Rate-Limit-Stopp

Beim Erstabruf ist das ChatGPT-Kontingent nach rund 200 Konversationen
erschöpft; der Lauf endet dann regulär und schätzt, wann das Limit wieder voll
ist. Endet ein `update` so (`sources.<quelle>.detail.rate_limit.stopped`), plant
die Bedienschicht automatisch eine **einmalige Aufgabe** `fortsetzung-<quelle>`
zum geschätzten Zeitpunkt plus `continuation.margin_minutes`. Sie führt
`continuation.command` aus (Standard `update --source chatgpt --listing-mode full
--non-interactive`; das vollständige Listing ist nötig, damit auch noch nie
geladene Konversationen erfasst werden). Endet auch dieser Lauf am Limit, wird
dieselbe Aufgabe neu terminiert; ist alles geladen (Lauf ok, kein Limit-Stopp),
wird sie entfernt. So läuft der Abruf ohne Zutun weiter, bis alle Daten da sind.

| Schlüssel | Standard | Bedeutung |
| --- | --- | --- |
| `task_scheduler.continuation.enabled` | `true` | Fortsetzung planen |
| `task_scheduler.continuation.margin_minutes` | `10` | Abstand nach dem geschätzten Wiederauffüllen |
| `task_scheduler.continuation.command` | siehe oben | Befehl der Fortsetzung |

- Gilt für jedes `update` über `chatexporter update`/`chatexporter-update`
  (auch geplante), nicht für den Einzellauf `chatexporter chatgpt update`.
- Abgebrochene oder fehlgeschlagene Läufe ändern nichts; eine geplante
  Fortsetzung bleibt bestehen.
- Ein Fehler beim Planen (z. B. pywin32 fehlt) bricht das Update nie ab; er steht
  in der Konsole und im abschließenden Bericht (`continuation_error`), der Erfolg
  dort als `continuation_<quelle>` (z. B. `geplant 2026-10-03 06:40`).
- Die Fortsetzung läuft ohne Interaktion; die ChatGPT-Anmeldung muss also im
  verwendeten Profil vorhanden sein.
- Im Entwicklungsmodus (`dev_mode: true`, siehe
  [KONFIGURATION.md](../KONFIGURATION.md), Abschnitt 8) startet die Fortsetzung fest
  5 Minuten nach dem Stopp; das Rate-Limit wird dort nach 5 Abrufen simuliert. So
  lässt sich die ganze Kette in Minuten und mit wenigen Anfragen prüfen.

## 6. Wo wird was gespeichert?

- **Aufgabenplanung:** Ordner `<folder>`, Aufgabenname = technische ID (`tsk_…`).
  Die Windows-Aufgabenplanung zeigt daher die ID als Namen; die Beschreibung
  enthält den Befehl (oder die eigene `--description`).
- **State (PyTaskManager):** lokal `state_file` und global `global_state_file`.
  Dort stehen ID, Kurzname, Eigentümer und der **gespeicherte Plan** (Befehl,
  Trigger, Einstellungen) unter `metadata.chatexporter`. `task update` baut die
  Aufgabe aus diesem Plan neu auf. Eine Aufgabe ohne gespeicherten Plan (State
  verloren oder nicht mit `chatexporter task` angelegt) lässt sich ansehen,
  pausieren und löschen, aber nicht ändern.
- Der globale State liegt standardmäßig in
  `%LOCALAPPDATA%\PyTaskManager\tasks_sched.json` (gemeinsam für alle Programme,
  die `scheduler_manager.py` nutzen). Fehlt dort ein Eintrag (Datei gelöscht oder
  zurückgesetzt), finden `task list`, Kurzname/Name und damit auch
  `task delete --all` und `chatexporter uninstall` die Aufgabe trotzdem über den
  lokalen State. Ist **auch** der lokale State weg, kennt ChatExporter die
  Aufgabe nicht mehr; sie bleibt in der Windows-Aufgabenplanung (Ordner
  `<folder>`) und muss dort von Hand gelöscht werden.
- **Befehlsprotokoll:** jeder geplante Lauf steht im normalen Befehlsprotokoll.

## 7. Wie hängt das zusammen?

```text
chatexporter task …  ──►  chatexporter.task_scheduler.cli
                              │ (Eingaben prüfen, Standardwerte, Ausgabe)
                              ▼
                          service.TaskService ──►  scheduler_manager.PyTaskManager ──► Windows COM
                              ▲                              (tools/task_scheduler/, per Dateipfad geladen)
                          config.load_config  (Abschnitt task_scheduler der config.yaml)
```

`chatexporter.task_scheduler` ist eine eigenständige Schicht: Sie importiert
weder den Raw Session Updater noch einen Provider (Test
`tests/test_independence.py`). Die Config-Suche existiert deshalb dort ein
weiteres Mal. Das Script `scheduler_manager.py` bleibt unverändert und wird
nicht kopiert. Seine Original-Dokumentation steht als Kopie in
[task_scheduler/README_PyTaskManager_V2.md](README_PyTaskManager_V2.md);
ihre Python-Beispiele beschreiben die Modul-API des Scripts, nicht die
`chatexporter task`-Befehle.

## 8. Grenzen

- Nur Windows; die Aufgabe läuft nur, wenn der Benutzer angemeldet ist.
- `--startup` erfordert Administratorrechte. Ohne sie lehnt Windows ab (Zugriff
  verweigert); `task create` meldet das verständlich, nennt `--logon` als Ausweg und
  legt nichts an (geprüft am 2026-10-05). Mit Administratorrechten wird die Aufgabe
  angelegt (Komplett-Test auf frischem Windows, 2026-10-05).
- Kein Dienst-Supervisor: Die Aufgabenplanung startet nur nach Plan.
- `update` legt die Windows-Aufgabe vollständig neu an (gleiche ID).
- Aufgaben aus anderen Ordnern oder mit anderem Eigentümer sieht `list` nicht.

## 9. Tests

```powershell
cd ChatExporter_Gen4_pre-6
..\.venv\Scripts\python.exe -m pytest tests\task_scheduler -p no:cacheprovider
```

| Datei | Prüft |
| --- | --- |
| `tests/task_scheduler/test_ts_config.py` | Defaults, Vorrang (CLI > Umgebung > config.yaml), Pfade, Fehler |
| `tests/task_scheduler/test_ts_service.py` | Eingaben (Befehl, Trigger, Tage), `create`/`get`/`list`/`update`/`delete`/`pause`/`resume` gegen einen Ersatz-PyTaskManager |
| `tests/task_scheduler/test_ts_cli.py` | alle Befehle der Kommandozeile, JSON, Exitcodes, Rückfrage beim Löschen |
| `tests/task_scheduler/test_ts_windows.py` | **echte** Aufgaben in einem Testordner der Aufgabenplanung (wird danach entfernt): Anlegen, Windows-Inhalt, State, Ändern, Pausieren, Löschen, und dass der geplante Befehl wirklich läuft |
| `tests/cli/test_cli.py` | Verteilung von `task`, Einzelbefehl `chatexporter-task`, Menüpunkte 12–16 |
| `tests/cli/test_continuation.py` | Entscheidung (planen, neu terminieren, beenden), Fehler bricht nichts ab, Anbindung an `update` |

`test_ts_windows.py` wird ohne Windows oder pywin32 übersprungen und berührt den
Ordner `\ChatExporter` nicht. Die Tests des Scripts selbst
(`tools/task_scheduler/test_scheduler_manager.py`) gehören zum Script und laufen
separat: `python tools\task_scheduler\test_scheduler_manager.py`.
