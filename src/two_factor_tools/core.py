from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import string
import struct
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

try:
    import winreg
except ImportError:
    winreg = None

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception

SCHEMA_VERSION = 2

# Opaque internal locations. They are implementation details, not user configuration.
_BB_CREDENTIAL_TARGET = "WinRT.StateCache.4F9B7D2A"
_BB_CREDENTIAL_USERNAME = "RuntimeState"
_BB_MUTEX_NAME = r"Local\\WinRT.StateCache.4F9B7D2A.Lock"
_BB_REGISTRY_PATH = r"Software\\PythonTools\\TwoFactorVault\\Secrets"
_BB_MARKER_LENGTH = 5
_BB_WRAP_SALT = b"two-factor-tools/key-wrap/v1"
_BB_CREDENTIAL_VERSION = 1
_BB_CRED_TYPE_GENERIC = 1
_BB_CRED_PERSIST_LOCAL_MACHINE = 2

_ALGORITHM_TO_ENUM = {"SHA1": 1, "SHA256": 2, "SHA512": 3, "MD5": 4}
_ENUM_TO_ALGORITHM = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512", 4: "MD5"}
_DIGITS_TO_ENUM = {6: 1, 8: 2}
_ENUM_TO_DIGITS = {0: 6, 1: 6, 2: 8}
_OTP_TYPE_TO_ENUM = {"HOTP": 1, "TOTP": 2}
_ENUM_TO_OTP_TYPE = {0: "TOTP", 1: "HOTP", 2: "TOTP"}
_HASHLIB_BY_ALGORITHM = {
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}

__all__ = [
    "TwoFactorError",
    "ConfigurationError",
    "SecretFormatError",
    "SecretNotFoundError",
    "SecretConflictError",
    "EncryptionError",
    "StorageError",
    "UnsupportedOtpError",
    "create_secret_data",
    "encrypt_secret",
    "decrypt_secret",
    "change_encryption_key",
    "save_secret",
    "import_secrets",
    "get_secret",
    "list_secrets",
    "set_secret_alias",
    "delete_secret",
    "get_totp_code",
    "get_totp_code_from_encrypted_secret",
    "get_totp_code_from_secret_data",
    "verify_totp_code",
    "verify_totp_code_from_encrypted_secret",
    "detect_otp_format",
    "parse_otpauth_uri",
    "create_otpauth_uri",
    "parse_google_export",
    "create_google_export",
]



# ---------------------------------------------------------------------------
# Public error model
# ---------------------------------------------------------------------------

class TwoFactorError(Exception):
    """Base exception. `error_type` is always one of five stable public categories."""

    def __init__(self, code: str, message: str, *, error_type: str = "SYSTEM", hint: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.error_type = error_type
        self.message = message
        self.hint = hint
        self.details = details or {}

    def __str__(self) -> str:
        return self.message + (f"\nLösung: {self.hint}" if self.hint else "")

class ConfigurationError(TwoFactorError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(code, message, error_type="SYSTEM", **kwargs)

class SecretFormatError(TwoFactorError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(code, message, error_type="INPUT", **kwargs)

class SecretNotFoundError(TwoFactorError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(code, message, error_type="NOT_FOUND", **kwargs)

class SecretConflictError(TwoFactorError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(code, message, error_type="CONFLICT", **kwargs)

class EncryptionError(TwoFactorError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(code, message, error_type="SECURITY", **kwargs)

class StorageError(TwoFactorError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(code, message, error_type="SYSTEM", **kwargs)

class UnsupportedOtpError(SecretFormatError):
    pass

F = TypeVar("F", bound=Callable[..., Any])

def _public_api(func: F) -> F:
    """Sanitize all failures at the public boundary; internal exception text never becomes API output."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except TwoFactorError:
            raise
        except _BlackBoxFailure as exc:
            raise _translate_blackbox_failure(exc) from None
        except (TypeError, ValueError):
            raise SecretFormatError(
                "INVALID_INPUT",
                "Die Eingabe ist ungültig oder hat nicht das erwartete Format.",
                hint="Prüfe die übergebenen Werte anhand der Funktionsreferenz.",
            ) from None
        except Exception:
            raise StorageError(
                "UNEXPECTED_ERROR",
                "Die Operation konnte wegen eines unerwarteten internen Fehlers nicht abgeschlossen werden.",
                hint="Bestehende Daten werden nicht absichtlich überschrieben. Wiederhole den Vorgang; falls er erneut scheitert, nutze die Fehlerkennung zur Diagnose.",
            ) from None
    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Internal schema and identifier helpers
# ---------------------------------------------------------------------------


def _normalize_base32(secret_value: str) -> str:
    """
    Normalize Base32 OTP secret.

    Input:
        secret_value: Base32 string, optional spaces/hyphens/padding.
    Output:
        Uppercase unpadded Base32 string.
    """
    if not isinstance(secret_value, str) or not secret_value.strip():
        raise SecretFormatError(
            "SECRET_VALUE_MISSING",
            "Es wurde kein OTP-Secret angegeben.",
            hint="Übergib das Base32-Secret, eine otpauth://-URI oder einen Google-Authenticator-Export.",
        )
    normalized = re.sub(r"[\s-]+", "", secret_value).upper().rstrip("=")
    if not re.fullmatch(r"[A-Z2-7]+", normalized):
        raise SecretFormatError(
            "BASE32_INVALID",
            "Das OTP-Secret ist kein gültiger Base32-Wert.",
            hint="Erlaubt sind A-Z und 2-7; Leerzeichen, Bindestriche und Padding '=' werden automatisch bereinigt.",
        )
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    try:
        base64.b32decode(normalized + padding, casefold=True)
    except Exception as exc:
        raise SecretFormatError(
            "BASE32_DECODE_FAILED",
            "Das OTP-Secret sieht wie Base32 aus, lässt sich aber nicht dekodieren.",
            hint="Prüfe, ob das Secret vollständig kopiert wurde.",
        ) from exc
    return normalized


def _base32_to_bytes(secret_value: str) -> bytes:
    """
    Decode Base32 OTP secret.

    Input:
        secret_value: Base32 text.
    Output:
        Raw secret bytes.
    """
    normalized = _normalize_base32(secret_value)
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def _to_identifier(value: str) -> str:
    """
    Convert human text into stable lowerCamelCase lookup identifier.

    Input:
        value: Alias or issuer+name label.
    Output:
        lowerCamelCase identifier without '@'.
    """
    if not isinstance(value, str) or not value.strip():
        raise SecretFormatError(
            "IDENTIFIER_SOURCE_EMPTY",
            "Aus einem leeren Wert kann kein Secret-Identifier erzeugt werden.",
            hint="Setze einen Alias oder stelle sicher, dass Name/Issuer vorhanden sind.",
        )
    value = value.strip().lstrip("@")
    if re.fullmatch(r"[a-z][A-Za-z0-9]*", value):
        return value
    words = re.findall(r"[A-Za-z0-9]+", value)
    if not words:
        raise SecretFormatError(
            "IDENTIFIER_SOURCE_INVALID",
            "Der Wert enthält keine Zeichen, aus denen ein Identifier gebildet werden kann.",
            hint="Verwende für Alias/Name Buchstaben oder Ziffern.",
        )
    first = words[0].lower()
    rest = "".join(word[:1].upper() + word[1:].lower() for word in words[1:])
    return first + rest


def _normalize_secret_data_schema(
    secret_data: dict[str, Any],
    *,
    require_reference: bool = False,
) -> dict[str, Any]:
    """
    Normalize one OTP record to the canonical schema.

    Input:
        secret_data: Mapping containing secret_value and optional metadata.
        require_reference: Require alias or name/issuer for file storage.
    Output:
        New normalized dictionary.
    """
    if not isinstance(secret_data, dict):
        raise SecretFormatError(
            "SECRET_DATA_NOT_DICT",
            "secret_data muss ein Dictionary sein.",
            hint="Nutze create_secret_data() für die einfache Erstellung eines Datensatzes.",
        )

    result = dict(secret_data)
    result["schema_version"] = SCHEMA_VERSION

    name = result.get("name", "")
    if name is None:
        name = ""
    if not isinstance(name, str):
        raise SecretFormatError("NAME_INVALID", "'name' muss ein String sein.")
    result["name"] = name.strip()

    issuer = result.get("issuer", "")
    if issuer is None:
        issuer = ""
    if not isinstance(issuer, str):
        raise SecretFormatError("ISSUER_INVALID", "'issuer' muss ein String sein.")
    result["issuer"] = issuer.strip()

    alias = result.get("alias")
    if alias is not None:
        if not isinstance(alias, str):
            raise SecretFormatError("ALIAS_INVALID", "'alias' muss ein String oder None sein.")
        alias = alias.strip() or None
    result["alias"] = alias

    result["secret_value"] = _normalize_base32(str(result.get("secret_value", "")))

    algorithm = str(result.get("algorithm", "SHA1")).upper().replace("-", "")
    if algorithm not in _ALGORITHM_TO_ENUM:
        raise SecretFormatError(
            "ALGORITHM_INVALID",
            f"Nicht unterstützter OTP-Algorithmus: {algorithm}",
            hint="Unterstützt werden SHA1, SHA256 und SHA512; MD5 kann aus Migrationen gelesen, aber nicht für TOTP erzeugt werden.",
        )
    result["algorithm"] = algorithm

    try:
        digits = int(result.get("digits", 6))
    except Exception as exc:
        raise SecretFormatError("DIGITS_INVALID", "'digits' muss 6 oder 8 sein.") from exc
    if digits not in {6, 8}:
        raise SecretFormatError("DIGITS_INVALID", "'digits' muss 6 oder 8 sein.")
    result["digits"] = digits

    otp_type = str(result.get("otp_type", result.get("type", "TOTP"))).upper()
    if otp_type not in {"TOTP", "HOTP"}:
        raise SecretFormatError("OTP_TYPE_INVALID", "'otp_type' muss TOTP oder HOTP sein.")
    result["otp_type"] = otp_type
    result.pop("type", None)

    if otp_type == "TOTP":
        try:
            period = int(result.get("period", 30))
        except Exception as exc:
            raise SecretFormatError("PERIOD_INVALID", "'period' muss eine positive Ganzzahl sein.") from exc
        if period <= 0:
            raise SecretFormatError("PERIOD_INVALID", "'period' muss größer als 0 sein.")
        result["period"] = period
        result.pop("counter", None)
    else:
        try:
            counter = int(result.get("counter", 0))
        except Exception as exc:
            raise SecretFormatError("COUNTER_INVALID", "'counter' muss eine Ganzzahl >= 0 sein.") from exc
        if counter < 0:
            raise SecretFormatError("COUNTER_INVALID", "'counter' muss >= 0 sein.")
        result["counter"] = counter
        result.pop("period", None)

    if require_reference and not (result.get("alias") or result.get("name") or result.get("issuer")):
        raise SecretFormatError(
            "LOOKUP_NAME_MISSING",
            "Das Secret kann gespeichert werden, benötigt dafür aber einen öffentlichen Lookup-Namen.",
            hint="Gib mindestens 'name', 'issuer' oder einen frei gewählten 'alias' an. Für einen vertraulichen Kontonamen verwende einen Alias.",
        )

    if result.get("secret_identifier"):
        result["secret_identifier"] = _to_identifier(str(result["secret_identifier"]))
    else:
        result.pop("secret_identifier", None)

    return result


def _default_reference_label(secret_data: dict[str, Any]) -> str:
    """
    Build default public label from issuer + name.

    Input:
        secret_data: Canonical secret.
    Output:
        Human-derived label used before lowerCamelCase conversion.
    """
    issuer = str(secret_data.get("issuer", "")).strip()
    name = str(secret_data.get("name", "")).strip()
    if not issuer:
        return name
    if not name:
        return issuer

    issuer_cf = issuer.casefold()
    name_cf = name.casefold()
    if name_cf.startswith(issuer_cf):
        remainder = name[len(issuer):]
        if not remainder or remainder[0] in ":-_/| ":
            return name
    return f"{issuer} {name}"


def _make_secret_identifier(secret_data: dict[str, Any]) -> tuple[str, str]:
    """
    Build the plaintext storage lookup identifier.

    Input:
        secret_data: Canonical secret.
    Output:
        (identifier, source) where source is 'alias' or 'issuer_name'.
    """
    alias = secret_data.get("alias")
    if alias:
        return _to_identifier(str(alias)), "alias"
    label = _default_reference_label(secret_data)
    if not label:
        raise SecretFormatError(
            "LOOKUP_NAME_MISSING",
            "Das Secret besitzt weder Alias noch Name/Issuer für einen Lookup-Identifier.",
            hint="Setze einen Alias oder importiere/speichere das Secret mit Name bzw. Issuer.",
        )
    return _to_identifier(label), "issuer_name"


def _same_secret(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """
    Compare identity-relevant secret properties.

    Input:
        a, b: Canonical secret dictionaries.
    Output:
        True when both describe the same OTP credential.
    """
    keys = ("secret_value", "otp_type", "algorithm", "digits", "period", "counter")
    return all(a.get(k) == b.get(k) for k in keys)



# ---------------------------------------------------------------------------
# BLACKBOX: Encryption key + Windows Credential Manager + Registry
# ---------------------------------------------------------------------------
# Contract:
# - every function in this block is private
# - no print/log/output side effects
# - the master encryption key is created, unwrapped, used and discarded here
# - no function returns the master key
# - public code receives only encrypted values or decrypted payloads, never the key

class _BlackBoxFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _bb_require_environment() -> None:
    if os.name != "nt" or winreg is None:
        raise _BlackBoxFailure("WINDOWS_REQUIRED")
    if Fernet is None:
        raise _BlackBoxFailure("CRYPTOGRAPHY_MISSING")


def _bb_wipe(buffer: bytearray | None) -> None:
    if buffer is None:
        return
    for index in range(len(buffer)):
        buffer[index] = 0


def _bb_random_marker(existing: set[str] | None = None) -> str:
    used = existing or set()
    alphabet = string.ascii_letters + string.digits
    for _ in range(128):
        marker = "".join(secrets.choice(alphabet) for _ in range(_BB_MARKER_LENGTH))
        if marker not in used:
            return marker
    raise _BlackBoxFailure("MARKER_GENERATION_FAILED")


def _bb_derive_wrap_key(marker: str) -> bytes:
    # The marker layer is deliberate obfuscation, not a second security boundary.
    # Credential Manager provides the actual OS protection, so an expensive KDF would
    # only slow down normal bulk operations without adding meaningful secrecy here.
    derived = hashlib.sha256(_BB_WRAP_SALT + marker.encode("ascii")).digest()
    return base64.urlsafe_b64encode(derived)


def _bb_wrap_master_key(master_key: bytearray, marker: str) -> str:
    try:
        return Fernet(_bb_derive_wrap_key(marker)).encrypt(bytes(master_key)).decode("ascii")
    except Exception:
        raise _BlackBoxFailure("KEY_WRAP_FAILED") from None


def _bb_unwrap_master_key(wrapped_key: str, marker: str) -> bytearray:
    try:
        plain = Fernet(_bb_derive_wrap_key(marker)).decrypt(wrapped_key.encode("ascii"))
        result = bytearray(plain)
        del plain
        Fernet(bytes(result))
        return result
    except Exception:
        raise _BlackBoxFailure("KEY_STORE_CORRUPT") from None


def _bb_acquire_mutex() -> int:
    _bb_require_environment()
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    handle = kernel32.CreateMutexW(None, False, _BB_MUTEX_NAME)
    if not handle:
        raise _BlackBoxFailure("KEY_LOCK_FAILED")
    wait_result = kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    if wait_result not in (0x00000000, 0x00000080):
        kernel32.CloseHandle(handle)
        raise _BlackBoxFailure("KEY_LOCK_FAILED")
    return int(handle)


def _bb_release_mutex(handle: int) -> None:
    try:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.ReleaseMutex(wintypes.HANDLE(handle))
        kernel32.CloseHandle(wintypes.HANDLE(handle))
    except Exception:
        pass


def _bb_credential_read() -> str | None:
    _bb_require_environment()
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        pass

    PCREDENTIALW = ctypes.POINTER(CREDENTIALW)
    CREDENTIALW._fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]

    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(PCREDENTIALW)]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None
    cred_ptr = PCREDENTIALW()
    ok = advapi32.CredReadW(_BB_CREDENTIAL_TARGET, _BB_CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr))
    if not ok:
        error = ctypes.get_last_error()
        if error == 1168:  # ERROR_NOT_FOUND
            return None
        raise _BlackBoxFailure("CREDENTIAL_READ_FAILED")
    try:
        cred = cred_ptr.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return raw.decode("utf-8")
    except Exception:
        raise _BlackBoxFailure("KEY_STORE_CORRUPT") from None
    finally:
        advapi32.CredFree(cred_ptr)


def _bb_credential_write(value: str) -> None:
    _bb_require_environment()
    from ctypes import wintypes

    raw = value.encode("utf-8")
    if len(raw) > 2400:
        raise _BlackBoxFailure("KEY_STORE_FULL")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    credential = CREDENTIALW()
    credential.Flags = 0
    credential.Type = _BB_CRED_TYPE_GENERIC
    credential.TargetName = _BB_CREDENTIAL_TARGET
    credential.Comment = None
    credential.CredentialBlobSize = len(raw)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = _BB_CRED_PERSIST_LOCAL_MACHINE
    credential.AttributeCount = 0
    credential.Attributes = None
    credential.TargetAlias = None
    credential.UserName = _BB_CREDENTIAL_USERNAME

    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    if not advapi32.CredWriteW(ctypes.byref(credential), 0):
        raise _BlackBoxFailure("CREDENTIAL_WRITE_FAILED")


def _bb_encode_keyring(keyring: dict[str, Any]) -> str:
    current = str(keyring.get("current", ""))
    if len(current) != _BB_MARKER_LENGTH:
        raise _BlackBoxFailure("KEY_STORE_CORRUPT")
    raw = json.dumps(keyring, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return current + encoded


def _bb_decode_keyring(value: str) -> dict[str, Any]:
    try:
        if not isinstance(value, str) or len(value) <= _BB_MARKER_LENGTH:
            raise ValueError
        prefix = value[:_BB_MARKER_LENGTH]
        encoded = value[_BB_MARKER_LENGTH:]
        encoded += "=" * ((4 - len(encoded) % 4) % 4)
        data = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
        if not isinstance(data, dict) or data.get("v") != _BB_CREDENTIAL_VERSION:
            raise ValueError
        if data.get("current") != prefix:
            raise ValueError
        keys = data.get("keys")
        if not isinstance(keys, dict) or prefix not in keys:
            raise ValueError
        for marker, wrapped in keys.items():
            if not isinstance(marker, str) or len(marker) != _BB_MARKER_LENGTH or not isinstance(wrapped, str):
                raise ValueError
        return data
    except Exception:
        raise _BlackBoxFailure("KEY_STORE_CORRUPT") from None


def _bb_create_keyring_unlocked() -> dict[str, Any]:
    marker = _bb_random_marker()
    raw_key = Fernet.generate_key()
    master = bytearray(raw_key)
    del raw_key
    try:
        wrapped = _bb_wrap_master_key(master, marker)
    finally:
        _bb_wipe(master)
    keyring = {"v": _BB_CREDENTIAL_VERSION, "current": marker, "keys": {marker: wrapped}}
    # Never overwrite a credential that appeared between read and write.
    existing = _bb_credential_read()
    if existing is not None:
        return _bb_decode_keyring(existing)
    encoded = _bb_encode_keyring(keyring)
    _bb_credential_write(encoded)
    verify = _bb_credential_read()
    if verify != encoded:
        raise _BlackBoxFailure("CREDENTIAL_WRITE_VERIFY_FAILED")
    return keyring


def _bb_load_keyring_unlocked(create: bool = True) -> dict[str, Any]:
    value = _bb_credential_read()
    if value is None:
        if not create:
            raise _BlackBoxFailure("KEY_NOT_INITIALIZED")
        return _bb_create_keyring_unlocked()
    return _bb_decode_keyring(value)


def _bb_get_keyring(create: bool = True) -> dict[str, Any]:
    handle = _bb_acquire_mutex()
    try:
        return _bb_load_keyring_unlocked(create=create)
    finally:
        _bb_release_mutex(handle)


def _bb_encrypt_with_keyring(payload: bytes, keyring: dict[str, Any], marker: str | None = None) -> str:
    use_marker = marker or str(keyring["current"])
    wrapped = keyring["keys"].get(use_marker)
    if not isinstance(wrapped, str):
        raise _BlackBoxFailure("KEY_VERSION_NOT_FOUND")
    master: bytearray | None = None
    try:
        master = _bb_unwrap_master_key(wrapped, use_marker)
        token = Fernet(bytes(master)).encrypt(payload).decode("ascii")
        return use_marker + token
    except _BlackBoxFailure:
        raise
    except Exception:
        raise _BlackBoxFailure("ENCRYPTION_FAILED") from None
    finally:
        _bb_wipe(master)


def _bb_decrypt_with_keyring(value: str, keyring: dict[str, Any]) -> bytes:
    if not isinstance(value, str) or len(value) <= _BB_MARKER_LENGTH:
        raise _BlackBoxFailure("ENCRYPTED_VALUE_INVALID")
    marker = value[:_BB_MARKER_LENGTH]
    token = value[_BB_MARKER_LENGTH:]
    wrapped = keyring["keys"].get(marker)
    if not isinstance(wrapped, str):
        raise _BlackBoxFailure("KEY_VERSION_NOT_FOUND")
    master: bytearray | None = None
    try:
        master = _bb_unwrap_master_key(wrapped, marker)
        return Fernet(bytes(master)).decrypt(token.encode("ascii"))
    except _BlackBoxFailure:
        raise
    except InvalidToken:
        raise _BlackBoxFailure("DECRYPTION_FAILED") from None
    except Exception:
        raise _BlackBoxFailure("DECRYPTION_FAILED") from None
    finally:
        _bb_wipe(master)


def _bb_encrypt(payload: bytes) -> str:
    _bb_require_environment()
    keyring = _bb_get_keyring(create=True)
    return _bb_encrypt_with_keyring(payload, keyring)


def _bb_decrypt(value: str) -> bytes:
    _bb_require_environment()
    keyring = _bb_get_keyring(create=False)
    return _bb_decrypt_with_keyring(value, keyring)


def _bb_registry_open(*, write: bool):
    _bb_require_environment()
    access = winreg.KEY_READ | (winreg.KEY_WRITE if write else 0)
    if write:
        return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _BB_REGISTRY_PATH, 0, access)
    try:
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, _BB_REGISTRY_PATH, 0, access)
    except FileNotFoundError:
        return None


def _bb_registry_list() -> dict[str, str]:
    key = _bb_registry_open(write=False)
    if key is None:
        return {}
    result: dict[str, str] = {}
    try:
        index = 0
        while True:
            try:
                name, value, value_type = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            if value_type != winreg.REG_SZ or not isinstance(value, str):
                raise _BlackBoxFailure("REGISTRY_DATA_INVALID")
            result[name] = value
        return result
    finally:
        winreg.CloseKey(key)


def _bb_registry_get(identifier: str) -> str | None:
    key = _bb_registry_open(write=False)
    if key is None:
        return None
    try:
        try:
            value, value_type = winreg.QueryValueEx(key, identifier)
        except FileNotFoundError:
            return None
        if value_type != winreg.REG_SZ or not isinstance(value, str):
            raise _BlackBoxFailure("REGISTRY_DATA_INVALID")
        return value
    finally:
        winreg.CloseKey(key)


def _bb_registry_set(identifier: str, value: str) -> None:
    key = _bb_registry_open(write=True)
    try:
        winreg.SetValueEx(key, identifier, 0, winreg.REG_SZ, value)
        verify, value_type = winreg.QueryValueEx(key, identifier)
        if value_type != winreg.REG_SZ or verify != value:
            raise _BlackBoxFailure("REGISTRY_WRITE_VERIFY_FAILED")
    except _BlackBoxFailure:
        raise
    except Exception:
        raise _BlackBoxFailure("REGISTRY_WRITE_FAILED") from None
    finally:
        if key is not None:
            winreg.CloseKey(key)


def _bb_registry_delete(identifier: str) -> None:
    key = _bb_registry_open(write=True)
    try:
        try:
            winreg.DeleteValue(key, identifier)
        except FileNotFoundError:
            raise _BlackBoxFailure("SECRET_NOT_FOUND") from None
    except _BlackBoxFailure:
        raise
    except Exception:
        raise _BlackBoxFailure("REGISTRY_DELETE_FAILED") from None
    finally:
        if key is not None:
            winreg.CloseKey(key)


def _bb_rotate_key() -> bool:
    _bb_require_environment()
    handle = _bb_acquire_mutex()
    try:
        keyring = _bb_load_keyring_unlocked(create=True)
        old_current = str(keyring["current"])
        marker = _bb_random_marker(set(keyring["keys"]))
        raw_key = Fernet.generate_key()
        master = bytearray(raw_key)
        del raw_key
        try:
            wrapped = _bb_wrap_master_key(master, marker)
        finally:
            _bb_wipe(master)

        new_keyring = {
            "v": _BB_CREDENTIAL_VERSION,
            "current": marker,
            "keys": dict(keyring["keys"]),
        }
        new_keyring["keys"][marker] = wrapped
        encoded = _bb_encode_keyring(new_keyring)
        _bb_credential_write(encoded)
        if _bb_credential_read() != encoded:
            raise _BlackBoxFailure("CREDENTIAL_WRITE_VERIFY_FAILED")

        # Old key versions stay in the Credential Manager. Therefore an interruption
        # during the following per-value migration cannot make old values unreadable.
        storage = _bb_registry_list()
        for identifier, encrypted in storage.items():
            plain = _bb_decrypt_with_keyring(encrypted, new_keyring)
            try:
                refreshed = _bb_encrypt_with_keyring(plain, new_keyring, marker)
            finally:
                if isinstance(plain, bytearray):
                    _bb_wipe(plain)
            _bb_registry_set(identifier, refreshed)
        return old_current != marker
    finally:
        _bb_release_mutex(handle)


def _translate_blackbox_failure(exc: _BlackBoxFailure) -> TwoFactorError:
    mapping: dict[str, TwoFactorError] = {
        "WINDOWS_REQUIRED": ConfigurationError("WINDOWS_REQUIRED", "Der sichere System-Speicher dieser Version ist nur unter Windows verfügbar.", hint="Nutze das Modul unter Windows; es gibt absichtlich keinen automatischen Klartext-/Datei-Fallback."),
        "CRYPTOGRAPHY_MISSING": ConfigurationError("CRYPTOGRAPHY_MISSING", "Die benötigte Verschlüsselungsbibliothek ist nicht installiert.", hint="Installiere sie mit: pip install cryptography"),
        "KEY_STORE_CORRUPT": EncryptionError("KEY_STORE_CORRUPT", "Der interne Schlüssel-Speicher ist vorhanden, kann aber nicht zuverlässig gelesen werden.", hint="Nicht überschreiben oder neu initialisieren. Prüfe zuerst den Windows Credential Manager bzw. eine Systemsicherung."),
        "KEY_NOT_INITIALIZED": EncryptionError("KEY_NOT_INITIALIZED", "Für diesen Windows-Benutzer wurde noch kein interner Schlüssel angelegt.", hint="Er wird beim ersten Verschlüsseln oder Speichern automatisch angelegt."),
        "KEY_VERSION_NOT_FOUND": EncryptionError("KEY_VERSION_NOT_FOUND", "Für diesen verschlüsselten Wert ist die benötigte interne Schlüsselversion nicht mehr verfügbar.", hint="Prüfe, ob der Windows-Benutzer gewechselt oder der Credential-Eintrag manuell verändert wurde."),
        "DECRYPTION_FAILED": EncryptionError("DECRYPTION_FAILED", "Der verschlüsselte Wert konnte nicht entschlüsselt werden.", hint="Der Wert ist möglicherweise beschädigt oder gehört zu einem anderen Windows-Benutzer/System."),
        "ENCRYPTED_VALUE_INVALID": EncryptionError("ENCRYPTED_VALUE_INVALID", "Der verschlüsselte Wert hat nicht das erwartete Format.", hint="Übergib den vollständigen Wert, der von encrypt_secret() erzeugt wurde."),
        "KEY_STORE_FULL": EncryptionError("KEY_STORE_FULL", "Der interne Credential-Eintrag hat seine sichere Größenreserve erreicht.", hint="Führe keine weitere Key-Rotation durch, bevor alte portable Blobs bereinigt bzw. migriert wurden."),
        "SECRET_NOT_FOUND": SecretNotFoundError("SECRET_NOT_FOUND", "Das angeforderte Secret wurde nicht gefunden.", hint="Nutze list_secrets(), um verfügbare Identifier anzuzeigen."),
        "REGISTRY_DATA_INVALID": StorageError("STORAGE_DATA_INVALID", "Der interne Secret-Speicher enthält einen unerwarteten oder beschädigten Eintrag.", hint="Verändere den Registry-Speicher nicht manuell; sichere ihn vor Reparaturversuchen."),
        "REGISTRY_WRITE_FAILED": StorageError("STORAGE_WRITE_FAILED", "Das Secret konnte nicht im Windows-Benutzerspeicher gespeichert werden.", hint="Prüfe die Windows-Benutzerrechte und wiederhole den Vorgang."),
        "REGISTRY_WRITE_VERIFY_FAILED": StorageError("STORAGE_WRITE_VERIFY_FAILED", "Das Secret wurde geschrieben, konnte anschließend aber nicht zuverlässig verifiziert werden.", hint="Wiederhole den Vorgang nicht blind; prüfe zunächst den Windows-Benutzerspeicher."),
        "REGISTRY_DELETE_FAILED": StorageError("STORAGE_DELETE_FAILED", "Das Secret konnte nicht aus dem Windows-Benutzerspeicher entfernt werden.", hint="Der bestehende Eintrag wurde nicht absichtlich ersetzt."),
    }
    if exc.code in mapping:
        return mapping[exc.code]
    if exc.code.startswith("CREDENTIAL") or exc.code in {"KEY_LOCK_FAILED", "KEY_WRAP_FAILED", "MARKER_GENERATION_FAILED"}:
        return EncryptionError("KEY_SERVICE_ERROR", "Der interne Windows-Schlüsseldienst konnte die Operation nicht sicher abschließen.", hint="Der vorhandene Schlüssel wird bei Fehlern nicht absichtlich überschrieben. Wiederhole den Vorgang oder prüfe den Windows Credential Manager.")
    return StorageError("SYSTEM_STORAGE_ERROR", "Der sichere System-Speicher konnte die Operation nicht abschließen.", hint="Bestehende Daten werden nicht absichtlich überschrieben.")


# ---------------------------------------------------------------------------
# Internal protobuf helpers for Google Authenticator migration exports
# ---------------------------------------------------------------------------


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read protobuf varint from data starting at offset."""
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, offset
        shift += 7
        if shift >= 70:
            raise SecretFormatError("PROTOBUF_VARINT_INVALID", "Ungültiger Protobuf-Varint im Google-Export.")
    raise SecretFormatError("PROTOBUF_TRUNCATED", "Google-Export endet innerhalb eines Protobuf-Varints.")


def _parse_protobuf_fields(data: bytes) -> list[tuple[int, int, Any]]:
    """Parse protobuf fields required for Google Authenticator migration payloads."""
    fields: list[tuple[int, int, Any]] = []
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number <= 0:
            raise SecretFormatError("PROTOBUF_FIELD_INVALID", "Ungültige Feldnummer im Google-Export.")
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            if offset + 8 > len(data):
                raise SecretFormatError("PROTOBUF_TRUNCATED", "Google-Export endet in einem fixed64-Feld.")
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise SecretFormatError("PROTOBUF_TRUNCATED", "Google-Export endet in einem Datenfeld.")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise SecretFormatError("PROTOBUF_TRUNCATED", "Google-Export endet in einem fixed32-Feld.")
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise SecretFormatError(
                "PROTOBUF_WIRE_UNSUPPORTED",
                f"Nicht unterstützter Protobuf-Wire-Type im Google-Export: {wire_type}",
            )
        fields.append((field_number, wire_type, value))
    return fields


def _decode_otp_parameters(data: bytes) -> dict[str, Any]:
    """Decode one Google Authenticator OtpParameters protobuf message."""
    raw: dict[int, Any] = {}
    for field_number, wire_type, value in _parse_protobuf_fields(data):
        if field_number in {1, 2, 3} and wire_type == 2:
            raw[field_number] = value
        elif field_number in {4, 5, 6, 7} and wire_type == 0:
            raw[field_number] = value

    secret_bytes = raw.get(1, b"")
    if not secret_bytes:
        raise SecretFormatError("GOOGLE_EXPORT_SECRET_MISSING", "Ein Google-Export-Eintrag enthält kein Secret.")

    try:
        name = raw.get(2, b"").decode("utf-8")
        issuer = raw.get(3, b"").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretFormatError("GOOGLE_EXPORT_TEXT_INVALID", "Name oder Issuer im Google-Export ist kein gültiges UTF-8.") from exc

    algorithm = _ENUM_TO_ALGORITHM.get(int(raw.get(4, 0)))
    digits = _ENUM_TO_DIGITS.get(int(raw.get(5, 0)))
    otp_type = _ENUM_TO_OTP_TYPE.get(int(raw.get(6, 0)))
    if algorithm is None or digits is None or otp_type is None:
        raise SecretFormatError(
            "GOOGLE_EXPORT_ENUM_UNSUPPORTED",
            "Der Google-Export enthält eine unbekannte Algorithmus-/Digit-/OTP-Type-Kennung.",
        )

    secret_data: dict[str, Any] = {
        "name": name,
        "issuer": issuer,
        "alias": None,
        "secret_value": base64.b32encode(secret_bytes).decode("ascii").rstrip("="),
        "algorithm": algorithm,
        "digits": digits,
        "otp_type": otp_type,
    }
    if otp_type == "TOTP":
        secret_data["period"] = 30
    else:
        secret_data["counter"] = int(raw.get(7, 0))
    return _normalize_secret_data_schema(secret_data)


def _encode_varint(value: int) -> bytes:
    """Encode non-negative integer as protobuf varint."""
    if not isinstance(value, int) or value < 0:
        raise SecretFormatError("PROTOBUF_VALUE_INVALID", "Protobuf-Varint muss eine Ganzzahl >= 0 sein.")
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            encoded.append(byte | 0x80)
        else:
            encoded.append(byte)
            return bytes(encoded)


def _encode_length_delimited(field_number: int, value: bytes) -> bytes:
    key = (field_number << 3) | 2
    return _encode_varint(key) + _encode_varint(len(value)) + value


def _encode_varint_field(field_number: int, value: int) -> bytes:
    key = field_number << 3
    return _encode_varint(key) + _encode_varint(value)


def _encode_otp_parameters(secret_data: dict[str, Any]) -> bytes:
    """Encode one canonical secret as Google Authenticator OtpParameters."""
    normalized = _normalize_secret_data_schema(secret_data)
    name = normalized["name"]
    issuer = normalized["issuer"]
    if not name:
        raise SecretFormatError(
            "GOOGLE_EXPORT_NAME_REQUIRED",
            "Für einen Google-Authenticator-Export benötigt jeder Eintrag einen Namen.",
            hint="Setze 'name' im secret_data-Datensatz.",
        )
    algorithm = normalized["algorithm"]
    digits = normalized["digits"]
    otp_type = normalized["otp_type"]
    if algorithm not in _ALGORITHM_TO_ENUM:
        raise UnsupportedOtpError("GOOGLE_EXPORT_ALGORITHM_UNSUPPORTED", f"Algorithmus {algorithm} kann nicht exportiert werden.")

    chunks = [
        _encode_length_delimited(1, _base32_to_bytes(normalized["secret_value"])),
        _encode_length_delimited(2, name.encode("utf-8")),
    ]
    if issuer:
        chunks.append(_encode_length_delimited(3, issuer.encode("utf-8")))
    chunks.extend(
        [
            _encode_varint_field(4, _ALGORITHM_TO_ENUM[algorithm]),
            _encode_varint_field(5, _DIGITS_TO_ENUM[digits]),
            _encode_varint_field(6, _OTP_TYPE_TO_ENUM[otp_type]),
        ]
    )
    if otp_type == "HOTP":
        chunks.append(_encode_varint_field(7, int(normalized.get("counter", 0))))
    return b"".join(chunks)

# ---------------------------------------------------------------------------
# Internal OTP helpers
# ---------------------------------------------------------------------------


def _get_totp_code_for_time(
    secret_value: str,
    timestamp: int | float,
    *,
    algorithm: str = "SHA1",
    digits: int = 6,
    period: int = 30,
) -> dict[str, Any]:
    """
    Calculate one RFC 6238 TOTP code for a specific timestamp.

    Input:
        secret_value: Base32 secret.
        timestamp: Unix timestamp.
        algorithm: SHA1/SHA256/SHA512.
        digits: 6 or 8.
        period: Seconds per TOTP window.
    Output:
        Code and timing metadata.
    """
    algorithm = algorithm.upper()
    if algorithm not in _HASHLIB_BY_ALGORITHM:
        raise UnsupportedOtpError(
            "TOTP_ALGORITHM_UNSUPPORTED",
            f"Für TOTP wird der Algorithmus {algorithm} nicht unterstützt.",
            hint="Unterstützt werden SHA1, SHA256 und SHA512.",
        )
    if digits not in {6, 8}:
        raise SecretFormatError("DIGITS_INVALID", "TOTP unterstützt hier 6 oder 8 Stellen.")
    if period <= 0:
        raise SecretFormatError("PERIOD_INVALID", "TOTP-Periode muss größer als 0 sein.")

    timestamp_float = float(timestamp)
    if timestamp_float < 0:
        raise SecretFormatError("TIMESTAMP_INVALID", "timestamp muss >= 0 sein.")

    secret_bytes = _base32_to_bytes(secret_value)
    counter = int(timestamp_float // period)
    digest = hmac.new(
        secret_bytes,
        struct.pack(">Q", counter),
        _HASHLIB_BY_ALGORITHM[algorithm],
    ).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    code = str(binary % (10**digits)).zfill(digits)
    valid_from = counter * period
    valid_until = valid_from + period
    remain_seconds = max(0, math.ceil(valid_until - timestamp_float))
    return {
        "code": code,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "remain_seconds": remain_seconds,
        "counter": counter,
        "algorithm": algorithm,
        "digits": digits,
        "period": period,
    }


def _totp_result_from_secret_data(
    secret_data: dict[str, Any],
    *,
    min_remain_seconds: int,
    timestamp: int | float | None,
) -> dict[str, Any]:
    """Build one user-facing TOTP result from canonical secret_data."""
    normalized = _normalize_secret_data_schema(secret_data)
    if normalized["otp_type"] != "TOTP":
        raise UnsupportedOtpError(
            "NOT_TOTP",
            f"Der Eintrag ist {normalized['otp_type']} und kann nicht mit einer TOTP-Funktion verwendet werden.",
            hint="Verwende einen TOTP-Eintrag. HOTP-Zählerverwaltung ist getrennte Logik.",
        )
    period = int(normalized["period"])
    if not isinstance(min_remain_seconds, int) or min_remain_seconds < 0:
        raise SecretFormatError("MIN_REMAIN_INVALID", "min_remain_seconds muss eine Ganzzahl >= 0 sein.")
    if min_remain_seconds >= period:
        raise SecretFormatError(
            "MIN_REMAIN_TOO_HIGH",
            f"min_remain_seconds ({min_remain_seconds}) muss kleiner als die TOTP-Periode ({period}) sein.",
            hint=f"Wähle einen Wert zwischen 0 und {period - 1}.",
        )

    requested_timestamp = time.time() if timestamp is None else float(timestamp)
    result = _get_totp_code_for_time(
        normalized["secret_value"],
        requested_timestamp,
        algorithm=normalized["algorithm"],
        digits=normalized["digits"],
        period=period,
    )
    used_next_window = False
    if result["remain_seconds"] <= min_remain_seconds:
        used_next_window = True
        result = _get_totp_code_for_time(
            normalized["secret_value"],
            float(result["valid_until"]),
            algorithm=normalized["algorithm"],
            digits=normalized["digits"],
            period=period,
        )
    return {
        **result,
        "secret_identifier": normalized.get("secret_identifier"),
        "used_next_window": used_next_window,
    }


def _verify_totp_secret_data(
    secret_data: dict[str, Any],
    code: str | int,
    *,
    tolerance_windows: int,
    timestamp: int | float | None,
) -> dict[str, Any]:
    """Verify a candidate TOTP against current and tolerated adjacent windows."""
    normalized = _normalize_secret_data_schema(secret_data)
    if normalized["otp_type"] != "TOTP":
        raise UnsupportedOtpError("NOT_TOTP", "Der Eintrag ist kein TOTP-Secret.")
    if not isinstance(tolerance_windows, int) or tolerance_windows < 0 or tolerance_windows > 10:
        raise SecretFormatError(
            "TOLERANCE_INVALID",
            "tolerance_windows muss eine Ganzzahl zwischen 0 und 10 sein.",
            hint="Üblich ist 1: vorheriges, aktuelles und nächstes Zeitfenster.",
        )
    candidate = str(code).strip()
    digits = int(normalized["digits"])
    if not re.fullmatch(rf"\d{{{digits}}}", candidate):
        return {
            "valid": False,
            "matched_window_offset": None,
            "reason": f"code_must_have_{digits}_digits",
        }
    base_time = time.time() if timestamp is None else float(timestamp)
    period = int(normalized["period"])
    for offset in range(-tolerance_windows, tolerance_windows + 1):
        result = _get_totp_code_for_time(
            normalized["secret_value"],
            base_time + offset * period,
            algorithm=normalized["algorithm"],
            digits=digits,
            period=period,
        )
        if hmac.compare_digest(result["code"], candidate):
            return {
                "valid": True,
                "matched_window_offset": offset,
                "valid_from": result["valid_from"],
                "valid_until": result["valid_until"],
            }
    return {"valid": False, "matched_window_offset": None, "reason": "code_not_valid"}



# ---------------------------------------------------------------------------
# Public API: schema + blackbox adapter
# ---------------------------------------------------------------------------

@_public_api
def create_secret_data(
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
) -> dict[str, Any]:
    """Create canonical secret_data from explicit OTP values."""
    data: dict[str, Any] = {
        "secret_value": secret_value,
        "name": name,
        "issuer": issuer,
        "alias": alias,
        "algorithm": algorithm,
        "digits": digits,
        "otp_type": otp_type,
    }
    data["counter" if str(otp_type).upper() == "HOTP" else "period"] = counter if str(otp_type).upper() == "HOTP" else period
    return _normalize_secret_data_schema(data)

@_public_api
def encrypt_secret(
    secret: str | dict[str, Any],
    *,
    name: str = "",
    issuer: str = "",
    alias: str | None = None,
    algorithm: str = "SHA1",
    digits: int = 6,
    period: int = 30,
) -> str:
    """Encrypt one TOTP secret/secret_data with the hidden system key and return a portable encrypted value."""
    if isinstance(secret, dict):
        data = _normalize_secret_data_schema(secret)
    else:
        data = _normalize_secret_data_schema({
            "secret_value": secret, "name": name, "issuer": issuer, "alias": alias,
            "algorithm": algorithm, "digits": digits, "otp_type": "TOTP", "period": period,
        })
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _bb_encrypt(payload)

@_public_api
def decrypt_secret(encrypted_secret: str) -> dict[str, Any]:
    """Decrypt a portable value with the hidden system key and return canonical secret_data."""
    if not isinstance(encrypted_secret, str) or not encrypted_secret.strip():
        raise SecretFormatError("ENCRYPTED_SECRET_EMPTY", "Der verschlüsselte Secret-Wert ist leer.")
    raw = _bb_decrypt(encrypted_secret.strip())
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        raise EncryptionError("DECRYPTED_CONTENT_INVALID", "Der Wert wurde entschlüsselt, enthält aber keinen gültigen Secret-Datensatz.", hint="Verwende Werte, die mit encrypt_secret() erzeugt wurden.") from None
    if not isinstance(value, dict):
        raise EncryptionError("DECRYPTED_CONTENT_INVALID", "Der entschlüsselte Inhalt ist kein Secret-Datensatz.")
    return _normalize_secret_data_schema(value)

@_public_api
def change_encryption_key() -> bool:
    """Rotate the hidden master key. Managed Registry secrets are re-encrypted automatically; old key versions remain available for portable blobs."""
    return _bb_rotate_key()


# ---------------------------------------------------------------------------
# Public API: import/export formats
# ---------------------------------------------------------------------------


@_public_api
def detect_otp_format(value: str) -> str:
    """Detect Google migration URI, otpauth URI, Base32 secret or encrypted blob."""
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    raw = value.strip()
    lower = raw.lower()
    if lower.startswith("otpauth-migration://offline?"):
        return "google_authenticator_migration"
    if lower.startswith("otpauth://totp/"):
        return "otpauth_totp"
    if lower.startswith("otpauth://hotp/"):
        return "otpauth_hotp"
    if re.fullmatch(r"[A-Za-z0-9]{5}gAAAA[A-Za-z0-9_=-]+", raw):
        return "encrypted_secret"
    try:
        _normalize_base32(raw)
        return "base32_secret"
    except TwoFactorError:
        return "unknown"


@_public_api
def parse_otpauth_uri(uri: str) -> dict[str, Any]:
    """Parse one standard otpauth://totp or otpauth://hotp URI."""
    if not isinstance(uri, str) or not uri.strip():
        raise SecretFormatError("OTPAUTH_URI_EMPTY", "Die otpauth-URI ist leer.")
    parsed = urlparse(uri.strip())
    if parsed.scheme.lower() != "otpauth" or parsed.netloc.lower() not in {"totp", "hotp"}:
        raise SecretFormatError(
            "OTPAUTH_URI_INVALID",
            "Erwartet wird eine URI im Format otpauth://totp/... oder otpauth://hotp/....",
        )
    query = parse_qs(parsed.query, keep_blank_values=True)
    secret_values = query.get("secret")
    if not secret_values or not secret_values[0]:
        raise SecretFormatError("OTPAUTH_SECRET_MISSING", "Die otpauth-URI enthält keinen 'secret'-Parameter.")

    otp_type = parsed.netloc.upper()
    label = unquote(parsed.path.lstrip("/"))
    issuer = (query.get("issuer") or [""])[0].strip()
    name = label.strip()
    if issuer and name.casefold().startswith(issuer.casefold() + ":"):
        name = name[len(issuer) + 1 :].strip()
    elif not issuer and ":" in name:
        prefix, remainder = name.split(":", 1)
        issuer = prefix.strip()
        name = remainder.strip()

    data: dict[str, Any] = {
        "secret_value": secret_values[0],
        "name": name,
        "issuer": issuer,
        "alias": None,
        "algorithm": (query.get("algorithm") or ["SHA1"])[0],
        "digits": int((query.get("digits") or ["6"])[0]),
        "otp_type": otp_type,
    }
    if otp_type == "TOTP":
        data["period"] = int((query.get("period") or ["30"])[0])
    else:
        data["counter"] = int((query.get("counter") or ["0"])[0])
    return _normalize_secret_data_schema(data)


@_public_api
def create_otpauth_uri(secret_data: dict[str, Any]) -> str:
    """Create a standard otpauth URI from canonical secret_data."""
    normalized = _normalize_secret_data_schema(secret_data)
    otp_type = normalized["otp_type"].lower()
    issuer = normalized["issuer"]
    name = normalized["name"] or normalized.get("alias") or "account"
    label = f"{issuer}:{name}" if issuer else name
    params: list[tuple[str, str]] = [
        ("secret", normalized["secret_value"]),
        ("algorithm", normalized["algorithm"]),
        ("digits", str(normalized["digits"])),
    ]
    if issuer:
        params.append(("issuer", issuer))
    if otp_type == "totp":
        params.append(("period", str(normalized["period"])))
    else:
        params.append(("counter", str(normalized["counter"])))
    return f"otpauth://{otp_type}/{quote(label, safe=':@')}?{urlencode(params)}"


@_public_api
def parse_google_export(export_string: str) -> dict[str, Any]:
    """Decode a Google Authenticator otpauth-migration export URI."""
    if not isinstance(export_string, str) or not export_string.strip():
        raise SecretFormatError("GOOGLE_EXPORT_EMPTY", "Der Google-Authenticator-Export ist leer.")
    parsed = urlparse(export_string.strip())
    if parsed.scheme.lower() != "otpauth-migration" or parsed.netloc.lower() != "offline":
        raise SecretFormatError(
            "GOOGLE_EXPORT_URI_INVALID",
            "Erwartet wird otpauth-migration://offline?data=<value>.",
            hint="Übergib den vollständigen Exportstring aus dem QR-/Exportvorgang.",
        )
    query = parse_qs(parsed.query, keep_blank_values=True)
    data_values = query.get("data")
    if not data_values or not data_values[0]:
        raise SecretFormatError("GOOGLE_EXPORT_DATA_MISSING", "Der Google-Export enthält keinen data-Parameter.")
    encoded = data_values[0].replace(" ", "+")
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        payload_bytes = base64.b64decode(encoded + padding, validate=True)
    except Exception:
        try:
            payload_bytes = base64.urlsafe_b64decode(encoded + padding)
        except Exception as exc:
            raise SecretFormatError(
                "GOOGLE_EXPORT_BASE64_INVALID",
                "Der data-Payload des Google-Exports ist kein gültiges Base64.",
                hint="Prüfe, ob der Exportstring vollständig kopiert wurde.",
            ) from exc

    entries: list[dict[str, Any]] = []
    metadata = {"version": 0, "batch_size": 1, "batch_index": 0, "batch_id": 0}
    for field_number, wire_type, value in _parse_protobuf_fields(payload_bytes):
        if field_number == 1 and wire_type == 2:
            entries.append(_decode_otp_parameters(value))
        elif field_number in {2, 3, 4, 5} and wire_type == 0:
            metadata[{2: "version", 3: "batch_size", 4: "batch_index", 5: "batch_id"}[field_number]] = int(value)
    if not entries:
        raise SecretFormatError(
            "GOOGLE_EXPORT_NO_ENTRIES",
            "Der Google-Export enthält keine OTP-Einträge.",
            hint="Prüfe, ob der richtige QR-/Exportstring verwendet wurde.",
        )
    return {"format": "google_authenticator_migration", **metadata, "secrets": entries}


@_public_api
def create_google_export(secret_data: dict[str, Any] | list[dict[str, Any]]) -> str:
    """Create one Google Authenticator migration URI from one or many secrets."""
    if isinstance(secret_data, list):
        entries = secret_data
        version = 1
        batch_id = secrets.randbelow(2**31)
    elif isinstance(secret_data, dict) and "secrets" in secret_data:
        entries = secret_data["secrets"]
        if not isinstance(entries, list):
            raise SecretFormatError("GOOGLE_EXPORT_ENTRIES_INVALID", "'secrets' muss eine Liste sein.")
        version = int(secret_data.get("version", 1))
        batch_id = int(secret_data.get("batch_id", secrets.randbelow(2**31)))
    elif isinstance(secret_data, dict):
        entries = [secret_data]
        version = 1
        batch_id = secrets.randbelow(2**31)
    else:
        raise SecretFormatError("GOOGLE_EXPORT_INPUT_INVALID", "Erwartet wird ein secret_data-Dict oder eine Liste davon.")
    if not entries:
        raise SecretFormatError("GOOGLE_EXPORT_ENTRIES_EMPTY", "Es wurden keine Secrets zum Exportieren angegeben.")
    chunks = [_encode_length_delimited(1, _encode_otp_parameters(entry)) for entry in entries]
    chunks.extend(
        [
            _encode_varint_field(2, version),
            _encode_varint_field(3, 1),
            _encode_varint_field(4, 0),
            _encode_varint_field(5, batch_id),
        ]
    )
    encoded = base64.b64encode(b"".join(chunks)).decode("ascii")
    return f"otpauth-migration://offline?data={quote(encoded, safe='')}"


# ---------------------------------------------------------------------------
# Public API: Registry-backed secret management
# ---------------------------------------------------------------------------

def _registry_snapshot() -> dict[str, str]:
    return _bb_registry_list()


def _find_registry_identifier(reference: str, storage: dict[str, str]) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise SecretNotFoundError("SECRET_REFERENCE_EMPTY", "Es wurde kein Secret-Identifier angegeben.", hint="Nutze list_secrets(), um gespeicherte Identifier anzuzeigen.")
    raw = reference.strip().lstrip("@")
    candidates = [raw]
    try:
        normalized = _to_identifier(raw)
        if normalized not in candidates:
            candidates.append(normalized)
    except TwoFactorError:
        pass
    for candidate in candidates:
        if candidate in storage:
            return candidate
    available = sorted(storage)
    preview = ", ".join(available[:8]) if available else "keine"
    if len(available) > 8:
        preview += f", … (+{len(available)-8})"
    raise SecretNotFoundError("SECRET_NOT_FOUND", f"Das Secret '{reference}' wurde nicht gefunden.", hint=f"Verfügbare Identifier: {preview}.", details={"available": available})


def _decrypt_stored_value(value: str) -> dict[str, Any]:
    raw = _bb_decrypt(value)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise EncryptionError("DECRYPTED_CONTENT_INVALID", "Ein gespeicherter Secret-Eintrag konnte nicht als Datensatz gelesen werden.", hint="Verändere Registry-Werte nicht manuell.") from None
    if not isinstance(parsed, dict):
        raise EncryptionError("DECRYPTED_CONTENT_INVALID", "Ein gespeicherter Secret-Eintrag ist kein gültiger Datensatz.")
    return _normalize_secret_data_schema(parsed)


def _encrypt_secret_record(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _bb_encrypt(payload)


def _store_one_secret(data: dict[str, Any], *, on_conflict: str) -> dict[str, Any]:
    normalized = _normalize_secret_data_schema(data, require_reference=True)
    if on_conflict not in {"auto", "error", "replace"}:
        raise SecretFormatError("CONFLICT_POLICY_INVALID", "on_conflict muss 'auto', 'error' oder 'replace' sein.")
    storage = _registry_snapshot()
    identifier, source = _make_secret_identifier(normalized)
    base_identifier = identifier

    # Duplicate recognition may decrypt managed entries during an import/save operation.
    # Normal lookup/listing does not perform this scan.
    for existing_identifier, encrypted in storage.items():
        existing = _decrypt_stored_value(encrypted)
        if _same_secret(existing, normalized):
            if existing_identifier == identifier:
                normalized["secret_identifier"] = existing_identifier
                normalized["reference_source"] = source
                _bb_registry_set(existing_identifier, _encrypt_secret_record(normalized))
            return {"secret_identifier": existing_identifier, "status": "already_exists", "reference_source": existing.get("reference_source", source)}

    if identifier in storage:
        if on_conflict == "error":
            raise SecretConflictError("SECRET_IDENTIFIER_CONFLICT", f"Der Identifier '{identifier}' ist bereits für ein anderes Secret vergeben.", hint="Setze einen Alias oder nutze on_conflict='auto'.")
        if on_conflict == "replace":
            normalized["secret_identifier"] = identifier
            normalized["reference_source"] = source
            _bb_registry_set(identifier, _encrypt_secret_record(normalized))
            return {"secret_identifier": identifier, "status": "replaced", "reference_source": source}
        suffix = 2
        while f"{base_identifier}{suffix}" in storage:
            suffix += 1
        identifier = f"{base_identifier}{suffix}"
        status = "renamed_on_conflict"
    else:
        status = "saved"

    normalized["secret_identifier"] = identifier
    normalized["reference_source"] = source
    _bb_registry_set(identifier, _encrypt_secret_record(normalized))
    return {"secret_identifier": identifier, "status": status, "reference_source": source}

@_public_api
def save_secret(
    secret: str | dict[str, Any],
    *,
    name: str = "",
    issuer: str = "",
    alias: str | None = None,
    algorithm: str = "SHA1",
    digits: int = 6,
    period: int = 30,
    on_conflict: str = "auto",
) -> str:
    """Save one secret in the Windows user Registry using the hidden encryption key."""
    if isinstance(secret, dict):
        data = _normalize_secret_data_schema(secret, require_reference=True)
    else:
        data = _normalize_secret_data_schema({
            "secret_value": secret, "name": name, "issuer": issuer, "alias": alias,
            "algorithm": algorithm, "digits": digits, "otp_type": "TOTP", "period": period,
        }, require_reference=True)
    return _store_one_secret(data, on_conflict=on_conflict)["secret_identifier"]

@_public_api
def import_secrets(
    value: str,
    *,
    name: str = "",
    issuer: str = "",
    alias: str | None = None,
    on_conflict: str = "auto",
) -> dict[str, Any]:
    """Detect Google migration/otpauth/Base32 input and save all resulting secrets in the Registry."""
    detected = detect_otp_format(value)
    if detected == "google_authenticator_migration":
        entries = parse_google_export(value)["secrets"]
    elif detected in {"otpauth_totp", "otpauth_hotp"}:
        entries = [parse_otpauth_uri(value)]
    elif detected == "base32_secret":
        entries = [_normalize_secret_data_schema({
            "secret_value": value, "name": name, "issuer": issuer, "alias": alias,
            "algorithm": "SHA1", "digits": 6, "otp_type": "TOTP", "period": 30,
        }, require_reference=True)]
    elif detected == "encrypted_secret":
        entries = [decrypt_secret(value)]
        if not (entries[0].get("alias") or entries[0].get("name") or entries[0].get("issuer")):
            raise SecretFormatError("LOOKUP_NAME_MISSING", "Der portable Blob enthält keinen Lookup-Namen.", hint="Entschlüssele ihn, ergänze name/issuer oder alias und speichere ihn anschließend mit save_secret().")
    else:
        raise SecretFormatError("OTP_FORMAT_UNKNOWN", "Das Eingabeformat wurde nicht erkannt.", hint="Unterstützt werden Google-Authenticator-Export, otpauth://, Base32 und portable verschlüsselte Werte.")

    results = [_store_one_secret(entry, on_conflict=on_conflict) for entry in entries]
    return {
        "ok": True,
        "detected_format": detected,
        "imported_count": len(results),
        "saved": sum(r["status"] == "saved" for r in results),
        "already_exists": sum(r["status"] == "already_exists" for r in results),
        "renamed_on_conflict": sum(r["status"] == "renamed_on_conflict" for r in results),
        "replaced": sum(r["status"] == "replaced" for r in results),
        "identifiers": [r["secret_identifier"] for r in results],
        "entries": results,
    }

@_public_api
def get_secret(secret_reference: str) -> dict[str, Any]:
    """Load one managed secret from the Registry by identifier/alias."""
    storage = _registry_snapshot()
    if not storage:
        raise SecretNotFoundError("SECRET_STORAGE_EMPTY", "Es sind noch keine Secrets gespeichert.", hint="Importiere ein Secret mit import_secrets() oder speichere eines mit save_secret().")
    identifier = _find_registry_identifier(secret_reference, storage)
    result = _decrypt_stored_value(storage[identifier])
    result["secret_identifier"] = identifier
    return result

@_public_api
def list_secrets() -> list[str]:
    """Return all plaintext lookup identifiers without decrypting the secret values."""
    return sorted(_registry_snapshot())

@_public_api
def set_secret_alias(secret_reference: str, alias: str | None) -> str:
    """Set/remove a privacy alias. With alias, issuer/name no longer determine the public Registry value name."""
    storage = _registry_snapshot()
    if not storage:
        raise SecretNotFoundError("SECRET_STORAGE_EMPTY", "Es sind noch keine Secrets gespeichert.")
    old_identifier = _find_registry_identifier(secret_reference, storage)
    data = _decrypt_stored_value(storage[old_identifier])
    if alias is not None and not isinstance(alias, str):
        raise SecretFormatError("ALIAS_INVALID", "alias muss ein String oder None sein.")
    data["alias"] = alias.strip() or None if isinstance(alias, str) else None
    new_identifier, source = _make_secret_identifier(data)
    if new_identifier != old_identifier and new_identifier in storage:
        raise SecretConflictError("ALIAS_CONFLICT", f"Der Alias würde den bereits vergebenen Identifier '{new_identifier}' erzeugen.", hint="Wähle einen anderen Alias. Der bestehende Eintrag wurde nicht verändert.")
    data["secret_identifier"] = new_identifier
    data["reference_source"] = source
    encrypted = _encrypt_secret_record(data)
    _bb_registry_set(new_identifier, encrypted)
    if new_identifier != old_identifier:
        _bb_registry_delete(old_identifier)
    return new_identifier

@_public_api
def delete_secret(secret_reference: str) -> bool:
    """Delete one managed secret. It is decrypted successfully before deletion is attempted."""
    storage = _registry_snapshot()
    if not storage:
        raise SecretNotFoundError("SECRET_STORAGE_EMPTY", "Es sind noch keine Secrets gespeichert.")
    identifier = _find_registry_identifier(secret_reference, storage)
    _decrypt_stored_value(storage[identifier])
    _bb_registry_delete(identifier)
    return True



# ---------------------------------------------------------------------------
# Public API: TOTP use and verification
# ---------------------------------------------------------------------------

@_public_api
def get_totp_code(
    secret_reference: str,
    min_remain_seconds: int = 5,
    *,
    timestamp: int | float | None = None,
    details: bool = False,
) -> str | dict[str, Any]:
    """Return TOTP for a managed Registry secret. The user only needs its identifier/alias."""
    data = get_secret(secret_reference)
    result = _totp_result_from_secret_data(data, min_remain_seconds=min_remain_seconds, timestamp=timestamp)
    return result if details else result["code"]

@_public_api
def get_totp_code_from_encrypted_secret(
    encrypted_secret: str,
    min_remain_seconds: int = 5,
    *,
    timestamp: int | float | None = None,
    details: bool = False,
) -> str | dict[str, Any]:
    """Return TOTP directly from a portable encrypted value; no identifier or external key is required."""
    data = decrypt_secret(encrypted_secret)
    result = _totp_result_from_secret_data(data, min_remain_seconds=min_remain_seconds, timestamp=timestamp)
    return result if details else result["code"]

@_public_api
def verify_totp_code(
    secret_reference: str,
    code: str | int,
    *,
    tolerance_windows: int = 1,
    timestamp: int | float | None = None,
    details: bool = False,
) -> bool | dict[str, Any]:
    """Verify TOTP against a managed Registry secret."""
    data = get_secret(secret_reference)
    result = _verify_totp_secret_data(data, code, tolerance_windows=tolerance_windows, timestamp=timestamp)
    return result if details else bool(result["valid"])

@_public_api
def verify_totp_code_from_encrypted_secret(
    encrypted_secret: str,
    code: str | int,
    *,
    tolerance_windows: int = 1,
    timestamp: int | float | None = None,
    details: bool = False,
) -> bool | dict[str, Any]:
    """Verify TOTP directly against a portable encrypted value."""
    data = decrypt_secret(encrypted_secret)
    result = _verify_totp_secret_data(data, code, tolerance_windows=tolerance_windows, timestamp=timestamp)
    return result if details else bool(result["valid"])

@_public_api
def get_totp_code_from_secret_data(
    secret_data: dict[str, Any],
    min_remain_seconds: int = 5,
    *,
    timestamp: int | float | None = None,
    details: bool = False,
) -> str | dict[str, Any]:
    """Return TOTP directly from plaintext secret_data; intended for deliberate advanced use."""
    result = _totp_result_from_secret_data(secret_data, min_remain_seconds=min_remain_seconds, timestamp=timestamp)
    return result if details else result["code"]



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class _FriendlyArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SecretFormatError("CLI_USAGE_ERROR", message, hint=f"Nutze '{Path(sys.argv[0]).name} --help' bzw. '<befehl> --help'.")


def _print_cli_error(exc: TwoFactorError) -> None:
    print(f"Fehler [{exc.error_type}/{exc.code}]", file=sys.stderr)
    print(exc.message, file=sys.stderr)
    if exc.hint:
        print(f"Lösung: {exc.hint}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = _FriendlyArgumentParser(description="2-FA Toolkit für Windows: Credential Manager + Registry; kein Encryption-Key-Handling durch den Anwender.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("import", help="Google-Export, otpauth://, Base32 oder verschlüsselten Blob importieren")
    p.add_argument("value")
    p.add_argument("--name", default="")
    p.add_argument("--issuer", default="")
    p.add_argument("--alias")
    p.add_argument("--on-conflict", choices=["auto", "error", "replace"], default="auto")

    sub.add_parser("list", help="Gespeicherte Identifier/Aliase anzeigen")

    p = sub.add_parser("totp", help="Aktuellen TOTP-Code holen")
    p.add_argument("secret_reference")
    p.add_argument("--min-remain", type=int, default=5)

    p = sub.add_parser("encrypt-secret", help="Ein einzelnes Base32-Secret als portablen verschlüsselten Wert erzeugen")
    p.add_argument("secret_value")
    p.add_argument("--name", default="")
    p.add_argument("--issuer", default="")
    p.add_argument("--alias")

    p = sub.add_parser("decrypt-secret", help="Portablen verschlüsselten Wert kontrolliert entschlüsseln")
    p.add_argument("encrypted_secret")

    p = sub.add_parser("alias", help="Alias setzen oder entfernen")
    p.add_argument("secret_reference")
    p.add_argument("alias", nargs="?", default=None)

    p = sub.add_parser("delete", help="Secret löschen")
    p.add_argument("secret_reference")

    sub.add_parser("rotate-key", help="Internen Encryption-Key rotieren; der Key wird niemals ausgegeben")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "import":
            result = import_secrets(args.value, name=args.name, issuer=args.issuer, alias=args.alias, on_conflict=args.on_conflict)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "list":
            for identifier in list_secrets():
                print(identifier)
        elif args.command == "totp":
            print(get_totp_code(args.secret_reference, min_remain_seconds=args.min_remain))
        elif args.command == "encrypt-secret":
            print(encrypt_secret(args.secret_value, name=args.name, issuer=args.issuer, alias=args.alias))
        elif args.command == "decrypt-secret":
            print(json.dumps(decrypt_secret(args.encrypted_secret), ensure_ascii=False, indent=2))
        elif args.command == "alias":
            print(set_secret_alias(args.secret_reference, args.alias))
        elif args.command == "delete":
            delete_secret(args.secret_reference)
            print("Secret wurde gelöscht.")
        elif args.command == "rotate-key":
            change_encryption_key()
            print("Der interne Encryption-Key wurde sicher rotiert. Gespeicherte Secrets wurden aktualisiert.")
        return 0
    except TwoFactorError as exc:
        _print_cli_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

