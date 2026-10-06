from __future__ import annotations
import copy
import re
from typing import Any
from urllib.parse import urlsplit

SECRET_KEY_RE = re.compile(
    r"(authorization|access_?token|refresh_?token|session_?token|cookie|set-cookie|password|totp|client_secret|api_?key)",
    re.IGNORECASE,
)
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE)
SIGNED_QUERY_KEYS = {"sig", "signature", "token", "key", "ts", "expires", "se", "sp", "sv"}
URL_RE = re.compile(r"https?://[^\s\"\'<>]+")
SENSITIVE_HEADER_LINE_RE = re.compile(
    r"(?im)^(?P<prefix>\s*(?:-\s*)?)(?P<name>authorization|cookie|set-cookie)\s*:\s*.*$"
)
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SESSION_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:__Secure-next-auth\.session-token(?:\.\d+)?|oai-client-auth-info|__oailb|__Secure-oai-is)=[^;\s]+"
)
REDACTED_REASONING = "<REDACTED_INTERNAL_REASONING>"


def redact_text(text: str) -> str:
    text = JWT_RE.sub("<REDACTED_JWT>", text)
    text = BEARER_RE.sub("Bearer <REDACTED>", text)
    text = SESSION_ASSIGNMENT_RE.sub("<REDACTED_SESSION_VALUE>", text)
    return EMAIL_RE.sub("<REDACTED_EMAIL>", text)


def redact_log_text(text: str) -> str:
    # Playwright error messages may embed complete request call logs. Redact full
    # sensitive header lines before doing URL/JWT cleanup so cookie jars can never
    # leak into persisted run manifests.
    text = SENSITIVE_HEADER_LINE_RE.sub(
        lambda m: f"{m.group('prefix')}{m.group('name')}: <REDACTED>",
        text,
    )
    text = redact_text(text)

    def repl(match):
        url = match.group(0)
        parsed = urlsplit(url)
        if not parsed.query:
            return url
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?<REDACTED_QUERY>"

    return URL_RE.sub(repl, text)


def compact_error_text(exc: Exception, *, max_chars: int = 1200) -> str:
    """Return a bounded, secret-safe diagnostic string for persistent logs."""
    text = redact_log_text(f"{type(exc).__name__}: {exc}")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " … <TRUNCATED>"


def safe_url(url: str) -> dict[str, Any]:
    p = urlsplit(url)
    return {
        "scheme": p.scheme,
        "host": p.hostname or "",
        "path": p.path,
        "query_keys": sorted({part.split("=", 1)[0] for part in p.query.split("&") if part}),
    }


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and SECRET_KEY_RE.search(k):
                out[k] = "<REDACTED>"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, str):
        text = redact_text(value)
        if text.startswith(("http://", "https://")):
            parsed = urlsplit(text)
            query_keys = {part.split("=", 1)[0].lower() for part in parsed.query.split("&") if part}
            if query_keys & SIGNED_QUERY_KEYS:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?<REDACTED_QUERY>"
        return text
    return value


def _redact_textual_leaves(value: Any) -> Any:
    if isinstance(value, str):
        return REDACTED_REASONING
    if isinstance(value, list):
        return [_redact_textual_leaves(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_textual_leaves(v) for k, v in value.items()}
    return value


def sanitize_reasoning_payload(payload: Any) -> Any:
    """Preserve graph/field shape while removing hidden/internal reasoning text.

    `reasoning_recap` is deliberately NOT redacted because research observed it as
    a user-visible recap content type. `thoughts`, `reasoning`, `raw_cot`, and
    metadata.summary_type=raw_cot are treated as non-exportable internal reasoning.
    """
    value = copy.deepcopy(payload)

    def walk(obj: Any, force_internal: bool = False) -> Any:
        if isinstance(obj, list):
            return [walk(v, force_internal) for v in obj]
        if not isinstance(obj, dict):
            return obj

        content_type = str(obj.get("content_type") or "").lower()
        md = obj.get("metadata")
        summary_type = str(md.get("summary_type") or "").lower() if isinstance(md, dict) else ""
        internal = force_internal or content_type in {"thoughts", "reasoning", "raw_cot"} or summary_type == "raw_cot"

        out = {}
        for k, v in obj.items():
            if internal and k in {"parts", "text", "reasoning", "thoughts"}:
                out[k] = _redact_textual_leaves(v)
            elif internal and k == "content":
                out[k] = walk(v, True)
            else:
                out[k] = walk(v, False)
        return out

    return redact_secrets(walk(value))


def mask_email(value: str | None) -> str | None:
    """Konto-E-Mail fuer Ausgaben: ``m***@example.org`` (Benutzername/E-Mail zaehlt zu den
    geschuetzten Angaben, ``_governance/CONFIG_AND_SECRETS.md``)."""
    if not value or "@" not in value:
        return value
    name, domain = value.split("@", 1)
    return f"{name[:1]}***@{domain}"
