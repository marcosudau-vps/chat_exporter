"""Einmalcode (TOTP) fuer die automatische Anmeldung – ueber die Two-Factor Tools.

Quellen (``providers.chatgpt.auth``, nur aus ``.env``/Umgebung):

- ``totp_reference`` (``CHATGPT_2FA_REFERENCE``): Kennung/Alias im verschluesselten
  Windows-Speicher der Two-Factor Tools – empfohlen, das Secret steht dann nirgends im Klartext.
- ``totp_secret`` (``CHATGPT_2FA_SECRET``): Base32-Secret, ``otpauth://totp/...``-URI
  oder ein mit ``encrypt_secret()`` erzeugter verschluesselter Wert.

Der Code wird so gewaehlt, dass er noch mindestens ``min_remain_seconds`` gilt.
Weder Secret noch Code werden protokolliert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class OneTimeCodeError(RuntimeError):
    """Kein Code erzeugbar (fehlt, unbekanntes Format, Speicher nicht lesbar). Ohne Secret im Text."""


@dataclass(frozen=True)
class OneTimeCode:
    code: str = ""
    remain_seconds: int = 0

    def __repr__(self) -> str:          # nie den Code ausgeben
        return f"OneTimeCode(remain_seconds={self.remain_seconds})"


def configured(auth: Any) -> bool:
    return bool(getattr(auth, "totp_reference", None) or getattr(auth, "totp_secret", None))


def current_code(auth: Any, *, min_remain_seconds: int = 10, timestamp: float | None = None) -> OneTimeCode:
    import two_factor_tools as tft

    try:
        if auth.totp_reference:
            info = tft.get_totp_code(auth.totp_reference, min_remain_seconds, timestamp=timestamp, details=True)
        elif auth.totp_secret:
            value = auth.totp_secret.strip()
            kind = tft.detect_otp_format(value)
            if kind == "encrypted_secret":
                info = tft.get_totp_code_from_encrypted_secret(value, min_remain_seconds, timestamp=timestamp,
                                                               details=True)
            elif kind == "otpauth_totp":
                info = tft.get_totp_code_from_secret_data(tft.parse_otpauth_uri(value), min_remain_seconds,
                                                          timestamp=timestamp, details=True)
            elif kind == "base32_secret":
                info = tft.get_totp_code_from_secret_data(tft.create_secret_data(value), min_remain_seconds,
                                                          timestamp=timestamp, details=True)
            else:
                raise OneTimeCodeError(f"2FA-Secret hat kein unterstuetztes Format ({kind}); erwartet: Base32, "
                                       "otpauth://totp/... oder verschluesselter Wert der Two-Factor Tools")
        else:
            raise OneTimeCodeError("Kein 2FA-Secret angegeben (CHATGPT_2FA_SECRET oder CHATGPT_2FA_REFERENCE)")
    except tft.TwoFactorError as exc:   # Meldungen der Two-Factor Tools enthalten keine Secrets
        hint = f" ({exc.hint})" if getattr(exc, "hint", None) else ""
        raise OneTimeCodeError(f"Einmalcode nicht erzeugbar: {exc.message}{hint}") from None
    return OneTimeCode(str(info["code"]), int(info.get("remain_seconds") or 0))
