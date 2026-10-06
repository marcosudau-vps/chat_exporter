# 2-FA Tools – Begleitreferenz V4

Diese Referenz beschreibt ausschließlich die **öffentliche API** von `two_factor_tools.py`. Interne Funktionen beginnen mit `_` und gehören nicht zur Bedienoberfläche des Moduls.

## Grundidee in 30 Sekunden

Für den normalen Anwender gibt es **keinen Encryption-Key mehr zu konfigurieren** und **keine Secret-Datei mehr zu verwalten**.

- Der interne Encryption-Key wird beim ersten Bedarf automatisch erzeugt.
- Er wird geschützt im Windows Credential Manager gespeichert.
- Verschlüsselte verwaltete Secrets werden unter dem aktuellen Windows-Benutzer in der Registry gespeichert.
- Der Key wird von keiner öffentlichen Funktion zurückgegeben.
- Für ein gespeichertes Secret genügt anschließend dessen Identifier oder Alias.

Minimaler Normalfall:

```python
from two_factor_tools import get_totp_code

code = get_totp_code("fleischwurst")
```

Ein neues Secret speichern:

```python
from two_factor_tools import save_secret

identifier = save_secret(
    "JBSWY3DPEHPK3PXP",
    issuer="GitHub",
    name="alice@example.com",
)
```

Ein Google-Authenticator-Export mit vielen Einträgen:

```python
from two_factor_tools import import_secrets

result = import_secrets(export_string)
```

Ein portabler verschlüsselter Wert ohne Registry-Lookup:

```python
from two_factor_tools import encrypt_secret, get_totp_code_from_encrypted_secret

encrypted_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
code = get_totp_code_from_encrypted_secret(encrypted_secret)
```

---

# Abschnitt 1: Übersicht

## 1.1 Öffentliche Funktionen

| Funktion | Vollständige Signatur | Ausgabe | Typischer Zweck |
|---|---|---|---|
| `create_secret_data` | `create_secret_data(secret_value: str, *, name: str = "", issuer: str = "", alias: str \| None = None, algorithm: str = "SHA1", digits: int = 6, otp_type: str = "TOTP", period: int = 30, counter: int = 0)` | `dict` | Kanonischen Secret-Datensatz erzeugen |
| `encrypt_secret` | `encrypt_secret(secret: str \| dict, *, name: str = "", issuer: str = "", alias: str \| None = None, algorithm: str = "SHA1", digits: int = 6, period: int = 30)` | `str` | Secret mit internem System-Key als portablen Wert verschlüsseln |
| `decrypt_secret` | `decrypt_secret(encrypted_secret: str)` | `dict` | Portablen verschlüsselten Wert entschlüsseln |
| `change_encryption_key` | `change_encryption_key()` | `bool` | Internen Master-Key rotieren |
| `save_secret` | `save_secret(secret: str \| dict, *, name: str = "", issuer: str = "", alias: str \| None = None, algorithm: str = "SHA1", digits: int = 6, period: int = 30, on_conflict: str = "auto")` | `str` | Ein Secret verschlüsselt im Windows-Speicher ablegen |
| `import_secrets` | `import_secrets(value: str, *, name: str = "", issuer: str = "", alias: str \| None = None, on_conflict: str = "auto")` | `dict` | Google-Export, `otpauth://`, Base32 oder portablen Blob erkennen und speichern |
| `get_secret` | `get_secret(secret_reference: str)` | `dict` | Ein verwaltetes Secret entschlüsselt laden |
| `list_secrets` | `list_secrets()` | `list[str]` | Verfügbare Identifier/Aliase auflisten, ohne Secrets zu entschlüsseln |
| `set_secret_alias` | `set_secret_alias(secret_reference: str, alias: str \| None)` | `str` | Privacy-Alias setzen oder entfernen |
| `delete_secret` | `delete_secret(secret_reference: str)` | `bool` | Ein Secret löschen |
| `get_totp_code` | `get_totp_code(secret_reference: str, min_remain_seconds: int = 5, *, timestamp: int \| float \| None = None, details: bool = False)` | `str` oder `dict` | TOTP für gespeichertes Secret erzeugen |
| `get_totp_code_from_encrypted_secret` | `get_totp_code_from_encrypted_secret(encrypted_secret: str, min_remain_seconds: int = 5, *, timestamp: int \| float \| None = None, details: bool = False)` | `str` oder `dict` | TOTP direkt aus portablem verschlüsseltem Wert erzeugen |
| `get_totp_code_from_secret_data` | `get_totp_code_from_secret_data(secret_data: dict, min_remain_seconds: int = 5, *, timestamp: int \| float \| None = None, details: bool = False)` | `str` oder `dict` | TOTP direkt aus Klartext-`secret_data` erzeugen |
| `verify_totp_code` | `verify_totp_code(secret_reference: str, code: str \| int, *, tolerance_windows: int = 1, timestamp: int \| float \| None = None, details: bool = False)` | `bool` oder `dict` | TOTP gegen gespeichertes Secret prüfen |
| `verify_totp_code_from_encrypted_secret` | `verify_totp_code_from_encrypted_secret(encrypted_secret: str, code: str \| int, *, tolerance_windows: int = 1, timestamp: int \| float \| None = None, details: bool = False)` | `bool` oder `dict` | TOTP gegen portablen verschlüsselten Wert prüfen |
| `detect_otp_format` | `detect_otp_format(value: str)` | `str` | OTP-Eingabeformat erkennen |
| `parse_otpauth_uri` | `parse_otpauth_uri(uri: str)` | `dict` | `otpauth://` in `secret_data` umwandeln |
| `create_otpauth_uri` | `create_otpauth_uri(secret_data: dict)` | `str` | Gegenstück zu `parse_otpauth_uri` |
| `parse_google_export` | `parse_google_export(export_string: str)` | `dict` | Google-Authenticator-Migrationsexport dekodieren |
| `create_google_export` | `create_google_export(secret_data: dict \| list[dict])` | `str` | Gegenstück zu `parse_google_export` |

## 1.2 Welchen Weg nehme ich?

### Ich will nur einen Login-Code

```python
code = get_totp_code("meinAlias")
```

### Ich habe einen Google-Authenticator-Export

```python
result = import_secrets(export_string)
```

### Ich habe nur ein Base32-Secret

```python
identifier = save_secret(
    secret_value,
    issuer="GitHub",
    name="alice@example.com",
)
```

### Der echte Accountname soll nicht als Registry-Identifier sichtbar sein

```python
new_identifier = set_secret_alias(
    "githubAliceExampleCom",
    "fleischwurst",
)
```

Danach ist `fleischwurst` der öffentliche Lookup-Identifier. `issuer`, `name` und `secret_value` bleiben im verschlüsselten Datensatz.

### Ich möchte überhaupt keinen verwalteten Registry-Eintrag

```python
encrypted_secret = encrypt_secret(secret_value)
code = get_totp_code_from_encrypted_secret(encrypted_secret)
```

Der portable Wert ist an den internen Key-Bestand dieses Windows-Benutzers gebunden. Ein anderer Windows-Benutzer oder ein neu aufgesetztes System besitzt diese Keys nicht automatisch.

## 1.3 System-Speicher

### Encryption-Key

Der Anwender erzeugt, speichert oder übergibt keinen Encryption-Key.

Beim ersten Vorgang, der Verschlüsselung benötigt, wird innerhalb der Blackbox geprüft:

```text
Credential vorhanden?
    |
    +-- ja -> bestehenden Key-Bestand lesen
    |
    +-- nein -> neuen Key erzeugen -> speichern -> zurücklesen/verifizieren
```

Ein vorhandener Credential-Eintrag wird bei der normalen Initialisierung **nicht überschrieben**.

Der Credential wird als Windows Generic Credential mit lokaler Maschinen-Persistenz gespeichert. Die öffentliche API besitzt keine Methode, die den Master-Key zurückgibt.

### 5-Zeichen-Marker

Jede Key-Version besitzt einen zufälligen fünfstelligen Marker, zum Beispiel:

```text
AbCdE
```

Ein verschlüsseltes Secret beginnt mit diesem Marker:

```text
AbCdE<fernet-token>
```

Der Marker ist keine eigenständige starke Sicherheitsgrenze. Er erfüllt zwei Aufgaben:

1. zusätzliche Obfuskation des intern gespeicherten Master-Key-Materials;
2. Versionierung: Die Blackbox erkennt, mit welcher internen Key-Version ein Wert verschlüsselt wurde.

### Key-Rotation

`change_encryption_key()` erzeugt einen neuen Master-Key und macht ihn zur aktuellen Version. Verwaltete Registry-Secrets werden anschließend auf die neue Version umgeschlüsselt.

Alte Key-Versionen werden nicht automatisch gelöscht. Dadurch bleiben bereits erzeugte portable Blobs weiterhin lesbar und auch ein Abbruch mitten in einer Rotation führt nicht dazu, dass die noch nicht umgeschlüsselten Registry-Werte plötzlich unlesbar werden.

### Secret-Speicher

Verwaltete Secrets werden unter `HKEY_CURRENT_USER` gespeichert. Die öffentlichen Identifier sind die Registry-Value-Namen, die verschlüsselten Datensätze die Values.

Der normale Anwender muss diesen Speicherort nicht kennen oder konfigurieren.

## 1.4 Öffentliche Fehlerklassen

Jeder erwartbare Fehler ist ein `TwoFactorError` und besitzt zusätzlich eine von genau fünf stabilen Kategorien in `error_type`:

| `error_type` | Bedeutung |
|---|---|
| `INPUT` | Eingabe oder OTP-Format ist ungültig |
| `NOT_FOUND` | Secret oder benötigter Eintrag existiert nicht |
| `CONFLICT` | Identifier/Alias kollidiert mit vorhandenem Inhalt |
| `SECURITY` | Entschlüsselung, Key-Version oder interner Key-Speicher ist problematisch |
| `SYSTEM` | Windows-/Registry-/Abhängigkeitsproblem |

Zusätzlich besitzt jeder Fehler einen spezifischen `code`, eine verständliche `message` und gegebenenfalls einen `hint`.

Beispiel:

```python
from two_factor_tools import TwoFactorError, get_totp_code

try:
    code = get_totp_code("fleischwurst")
except TwoFactorError as exc:
    print(exc.error_type)
    print(exc.code)
    print(exc.message)
    if exc.hint:
        print(exc.hint)
```

Interne Rohfehler der Blackbox werden nicht als Originaltext nach außen weitergereicht.

---

# Abschnitt 2: Funktionen

## create_secret_data

```python
create_secret_data(
    secret_value: str,
    *,
    name: str = "",
    issuer: str = "",
    alias: str | None = None,
    algorithm: str = "SHA1",
    digits: int = 6,
    otp_type: str = "TOTP",
    period: int = 30,
    counter: int = 0,
) -> dict[str, Any]
```

**Beschreibung:** Erstellt und validiert einen kanonischen `secret_data`-Datensatz. Es wird nichts gespeichert und nichts verschlüsselt.

| Parameter | Required | Default | Bedeutung |
|---|---:|---|---|
| `secret_value` | ja | – | Base32-OTP-Secret |
| `name` | nein | `""` | echter Account-/Labelname |
| `issuer` | nein | `""` | Dienst/Anbieter |
| `alias` | nein | `None` | frei gewählter Privacy-/Lookup-Alias |
| `algorithm` | nein | `"SHA1"` | OTP-Hashalgorithmus |
| `digits` | nein | `6` | Code-Länge, unterstützt: 6 oder 8 |
| `otp_type` | nein | `"TOTP"` | `TOTP` oder `HOTP` |
| `period` | nein | `30` | TOTP-Zeitfenster in Sekunden |
| `counter` | nein | `0` | HOTP-Counter |

**Ausgabe:** normalisiertes `secret_data`-Dictionary.

---

## encrypt_secret

```python
encrypt_secret(
    secret: str | dict[str, Any],
    *,
    name: str = "",
    issuer: str = "",
    alias: str | None = None,
    algorithm: str = "SHA1",
    digits: int = 6,
    period: int = 30,
) -> str
```

**Beschreibung:** Verschlüsselt entweder ein nacktes Base32-TOTP-Secret oder einen bestehenden `secret_data`-Datensatz. Der interne Encryption-Key wird automatisch aus der Blackbox verwendet und kann nicht als Argument übergeben werden.

**Pflicht:** Nur `secret`.

**Ausgabe:** portabler verschlüsselter String mit fünfstelligem Key-Marker als Präfix.

---

## decrypt_secret

```python
decrypt_secret(encrypted_secret: str) -> dict[str, Any]
```

**Beschreibung:** Entschlüsselt einen von `encrypt_secret()` erzeugten Wert. Der Encryption-Key bleibt dabei vollständig intern.

**Pflicht:** `encrypted_secret`.

**Ausgabe:** kanonisches `secret_data`.

---

## change_encryption_key

```python
change_encryption_key() -> bool
```

**Beschreibung:** Rotiert den internen Master-Key. Es gibt keinen Parameter für alten oder neuen Key und die Keys werden nicht ausgegeben.

**Ablauf:** neue Key-Version anlegen → Credential verifizieren → verwaltete Registry-Secrets einzeln entschlüsseln und mit neuer Version neu verschlüsseln. Historische Key-Versionen bleiben für alte portable Werte erhalten.

**Ausgabe:** `True`, wenn eine neue Key-Version aktiviert wurde.

---

## save_secret

```python
save_secret(
    secret: str | dict[str, Any],
    *,
    name: str = "",
    issuer: str = "",
    alias: str | None = None,
    algorithm: str = "SHA1",
    digits: int = 6,
    period: int = 30,
    on_conflict: str = "auto",
) -> str
```

**Beschreibung:** Speichert genau ein Secret verschlüsselt im Windows-Benutzerspeicher.

**Identifier-Regel:**

- `alias` vorhanden → Identifier wird aus `alias` gebildet.
- kein Alias → Identifier wird aus `issuer + name` gebildet.

**`on_conflict`:**

- `"auto"` → bei echtem Namenskonflikt wird verlustfrei ein numerisches Suffix gewählt;
- `"error"` → Konflikt wird als `SecretConflictError` gemeldet;
- `"replace"` → vorhandener anderer Datensatz mit gleichem Identifier wird bewusst ersetzt.

**Ausgabe:** tatsächlich verwendeter Identifier.

---

## import_secrets

```python
import_secrets(
    value: str,
    *,
    name: str = "",
    issuer: str = "",
    alias: str | None = None,
    on_conflict: str = "auto",
) -> dict[str, Any]
```

**Beschreibung:** Bequeme Import-Fassade. Erkennt das Format automatisch.

Unterstützt:

- `otpauth-migration://offline?data=<data>`
- `otpauth://totp/<label>?secret=<secret>`
- `otpauth://hotp/<label>?secret=<secret>&counter=<counter>`
- nacktes Base32-Secret
- portablen verschlüsselten Wert aus `encrypt_secret()`

`name`, `issuer` und `alias` werden bei einem nackten Base32-Secret benötigt bzw. verwendet. Ein Google-Export bringt seine Metadaten selbst mit.

**Ausgabe:** Ergebnisbericht mit `detected_format`, Zählern und den verwendeten `identifiers`.

---

## get_secret

```python
get_secret(secret_reference: str) -> dict[str, Any]
```

**Beschreibung:** Lädt einen Registry-Eintrag über seinen Identifier/Alias und entschlüsselt den Datensatz.

**Ausgabe:** kanonisches `secret_data` inklusive `secret_identifier`.

**Hinweis:** Für Login-Automation ist meist `get_totp_code()` besser, weil das Secret dann nicht unnötig an den aufrufenden Code gegeben wird.

---

## list_secrets

```python
list_secrets() -> list[str]
```

**Beschreibung:** Listet die öffentlichen Identifier/Aliase auf. Dafür werden die verschlüsselten Secret-Werte nicht entschlüsselt.

**Ausgabe:** alphabetisch sortierte Liste.

---

## set_secret_alias

```python
set_secret_alias(
    secret_reference: str,
    alias: str | None,
) -> str
```

**Beschreibung:** Setzt einen Alias oder entfernt ihn wieder.

- `alias="fleischwurst"` → neuer öffentlicher Identifier wird aus `fleischwurst` gebildet.
- `alias=None` → Rückkehr zum Standard-Identifier aus `issuer + name`.

Bei einer Kollision wird nichts still überschrieben.

**Ausgabe:** neuer Identifier.

---

## delete_secret

```python
delete_secret(secret_reference: str) -> bool
```

**Beschreibung:** Löscht ein verwaltetes Secret. Vor dem Löschen wird der Datensatz einmal erfolgreich entschlüsselt; dadurch wird ein beschädigter oder nicht mehr lesbarer Wert nicht blind entfernt.

**Ausgabe:** `True` bei erfolgreichem Löschen.

---

## get_totp_code

```python
get_totp_code(
    secret_reference: str,
    min_remain_seconds: int = 5,
    *,
    timestamp: int | float | None = None,
    details: bool = False,
) -> str | dict[str, Any]
```

**Beschreibung:** Hauptfunktion für normale Login-Automation.

```python
code = get_totp_code("fleischwurst", min_remain_seconds=10)
```

Wenn der aktuelle TOTP-Code nicht mehr mindestens `min_remain_seconds` gültig wäre, wird direkt der nächste Zeit-Slot verwendet.

**Standardausgabe:** nur der Code als String.

Bei `details=True` enthält die Ausgabe unter anderem `code`, `valid_from`, `valid_until`, `remain_seconds` und `used_next_window`.

---

## get_totp_code_from_encrypted_secret

```python
get_totp_code_from_encrypted_secret(
    encrypted_secret: str,
    min_remain_seconds: int = 5,
    *,
    timestamp: int | float | None = None,
    details: bool = False,
) -> str | dict[str, Any]
```

**Beschreibung:** TOTP direkt aus einem portablen verschlüsselten Wert. Weder Identifier noch Encryption-Key sind notwendig.

```python
code = get_totp_code_from_encrypted_secret(encrypted_secret)
```

---

## get_totp_code_from_secret_data

```python
get_totp_code_from_secret_data(
    secret_data: dict[str, Any],
    min_remain_seconds: int = 5,
    *,
    timestamp: int | float | None = None,
    details: bool = False,
) -> str | dict[str, Any]
```

**Beschreibung:** Direkter Klartext-Weg für bewusste Spezialfälle. Für normalen Betrieb sind `get_totp_code()` oder `get_totp_code_from_encrypted_secret()` vorzuziehen.

---

## verify_totp_code

```python
verify_totp_code(
    secret_reference: str,
    code: str | int,
    *,
    tolerance_windows: int = 1,
    timestamp: int | float | None = None,
    details: bool = False,
) -> bool | dict[str, Any]
```

**Beschreibung:** Prüft einen Code gegen ein verwaltetes Secret.

`tolerance_windows=1` berücksichtigt vorheriges, aktuelles und nächstes Zeitfenster.

**Standardausgabe:** `True` oder `False`.

---

## verify_totp_code_from_encrypted_secret

```python
verify_totp_code_from_encrypted_secret(
    encrypted_secret: str,
    code: str | int,
    *,
    tolerance_windows: int = 1,
    timestamp: int | float | None = None,
    details: bool = False,
) -> bool | dict[str, Any]
```

**Beschreibung:** Gegenstück zur Verifikation für portable verschlüsselte Werte.

---

## detect_otp_format

```python
detect_otp_format(value: str) -> str
```

**Ausgabe:** einer der Werte:

```text
google_authenticator_migration
otpauth_totp
otpauth_hotp
base32_secret
encrypted_secret
unknown
```

---

## parse_otpauth_uri

```python
parse_otpauth_uri(uri: str) -> dict[str, Any]
```

**Beschreibung:** Wandelt eine Standard-`otpauth://totp/<label>?secret=<secret>`- oder `otpauth://hotp/<label>?secret=<secret>&counter=<counter>`-URI in kanonisches `secret_data` um.

---

## create_otpauth_uri

```python
create_otpauth_uri(secret_data: dict[str, Any]) -> str
```

**Beschreibung:** Gegenstück zu `parse_otpauth_uri()`. Erstellt eine standardisierte `otpauth://`-URI.

---

## parse_google_export

```python
parse_google_export(export_string: str) -> dict[str, Any]
```

**Beschreibung:** Dekodiert `otpauth-migration://offline?data=<value>` über URL/Base64/Protobuf und liefert alle enthaltenen OTP-Einträge als `secret_data`.

Diese Funktion **speichert nichts**. Zum direkten Import in den verwalteten Speicher `import_secrets()` verwenden.

---

## create_google_export

```python
create_google_export(
    secret_data: dict[str, Any] | list[dict[str, Any]],
) -> str
```

**Beschreibung:** Gegenstück zu `parse_google_export()`. Erzeugt einen Google-Authenticator-Migrationstring aus einem oder mehreren Datensätzen.

---

# Abschnitt 3: Entitäten

Die folgenden Namen sind innerhalb der öffentlichen API verbindlich. Besonders bei geheimen oder verschlüsselten Werten sollen keine alternativen Bezeichnungen eingeführt werden.

| Entität | Typ | Vertraulich | Bedeutung |
|---|---|---:|---|
| `secret_value` | `str` | **ja** | Unverschlüsseltes Base32-OTP-Secret |
| `secret_data` | `dict` | **ja** | Kanonischer Datensatz inklusive Secret und Metadaten |
| `encrypted_secret` | `str` | eingeschränkt | Verschlüsselter portabler `secret_data`-Wert mit 5-Zeichen-Key-Marker |
| `secret_identifier` | `str` | standardmäßig nein | Aktiver öffentlicher Lookup-Identifier |
| `secret_reference` | `str` | nein | Vom Aufrufer angegebener Identifier/Alias zum Nachschlagen |
| `alias` | `str \| None` | nein | Frei gewählter öffentlicher Privacy-Name, z. B. `fleischwurst` |
| `name` | `str` | potenziell ja | Echter Account-/Labelname aus Authenticator oder Nutzerangabe |
| `issuer` | `str` | potenziell ja | Dienst/Anbieter, z. B. `GitHub` |
| `algorithm` | `str` | nein | OTP-Hashalgorithmus, typischerweise `SHA1` |
| `digits` | `int` | nein | Anzahl OTP-Ziffern |
| `period` | `int` | nein | TOTP-Zeitfenster in Sekunden |
| `counter` | `int` | nein | HOTP-Counter |
| `otp_type` | `str` | nein | `TOTP` oder `HOTP` |
| `key_marker` | intern, 5 Zeichen | nein | Interne Key-Version, Präfix verschlüsselter Werte |
| `encryption_key` | **nur intern** | **streng** | Master-Key der Blackbox; keine öffentliche API nimmt oder liefert diesen Wert |

## Kanonisches `secret_data`-Schema

TOTP:

```python
{
    "schema_version": 2,
    "secret_value": "JBSWY3DPEHPK3PXP",
    "name": "alice@example.com",
    "issuer": "GitHub",
    "alias": None,
    "algorithm": "SHA1",
    "digits": 6,
    "otp_type": "TOTP",
    "period": 30,
}
```

Gespeicherte Datensätze enthalten zusätzlich den tatsächlich verwendeten `secret_identifier` und `reference_source`.

## Identifier-Regel

```text
alias vorhanden
    -> secret_identifier aus alias

kein alias
    -> secret_identifier aus issuer + name
```

Beispiele:

```text
issuer="GitHub", name="alice@example.com"
-> githubAliceExampleCom

alias="Fleischwurst"
-> fleischwurst
```

## Blackbox-Grenze

Innerhalb der Blackbox:

- sind alle Funktionen privat;
- gibt es keine Prints und keine Logs;
- wird der Master-Key erzeugt, gespeichert, entschlüsselt und verwendet;
- verlässt der Master-Key die Blackbox niemals als Returnwert oder Exception-Detail;
- wird ein vorhandener Credential bei normaler Initialisierung nicht überschrieben;
- werden interne Fehler an der öffentlichen Grenze auf definierte Fehlerklassen/-typen übersetzt.

Secrets selbst dürfen außerhalb der Blackbox als Klartext verarbeitet werden, wenn eine öffentliche Funktion dies ausdrücklich bezweckt. Empfohlen bleiben kurze Lebensdauer, keine Logs und keine unnötigen Kopien.

### Technische Grenze von Python

CPython garantiert kein forensisch sicheres Überschreiben aller zwischenzeitlich erzeugten Kopien von `str`/`bytes`. Die Implementierung hält den Master-Key deshalb möglichst kurzlebig, benutzt mutable Puffer, wo dies praktikabel ist, und überschreibt diese aktiv. Eine Garantie, dass zu keinem Zeitpunkt eine interne Interpreter-Kopie im Prozessspeicher existiert, wäre technisch falsch.
