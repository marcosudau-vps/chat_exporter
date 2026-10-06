# Storage-Schemas

Das Format des Datenbestands (Verzeichnisaufbau, Dateien, Bezeichnungen,
Regeln) ist versioniert und heißt **Storage-Schema**. Je Storage-Schema gibt es
hier ein eigenständiges Dokument, das genau diesen Stand beschreibt.

| Storage-Schema | Dokument | erkannt an |
| --- | --- | --- |
| Storage-Schema 1 | [STORAGE-SCHEMA-1.md](STORAGE-SCHEMA-1.md) | `runtime/` + `raw_storage/`, kein `.storage/` (kein Marker) |
| Storage-Schema 2 | [STORAGE-SCHEMA-2.md](STORAGE-SCHEMA-2.md) | `.storage/storage.yaml` mit `storage_schema: 2` |

## Kennzeichnung

Die Storage-Schema-Nummer ist eine eigene Zählung und **nie** die
Programmversion (z. B. `0.0.0.dev6`). Sie wird immer so geschrieben:

| Ort | Schreibweise |
| --- | --- |
| Text | „Storage-Schema 2“ |
| Dateinamen, Kennungen, Formatnamen | `storage-schema-2` |
| Marker `.storage/storage.yaml`, Zustand, `state.yaml` | Feld `storage_schema: 2` |

Andere Versionsnummern im Datenbestand sind **Formatversionen einzelner
Dateien** und keine Storage-Schema-Nummern: `schema_version` von Index,
Laufbericht, Export-Manifest, Aufgaben-State sowie das Feld
`storage_schema_version` im ChatGPT-Envelope (Formatversion des Envelopes).

## Sicherungen

Vor jeder Umstellung auf ein neues Storage-Schema wird der Datenbestand im alten
Storage-Schema als ZIP gesichert: `workspace/.archiv/storage_schema/`,
Dateiname `storage-schema-<N>_<bestand>_<datum>.zip` mit gleichnamiger
`.json` (Prüfsumme, Dateianzahl, Größen, Prüfergebnis).
