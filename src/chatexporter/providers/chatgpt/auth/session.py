from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AuthIdentity:
    user_id: str | None = None
    email: str | None = None
    name: str | None = None


@dataclass(slots=True)
class AuthSession:
    access_token: str
    identity: AuthIdentity
    page: Any
    context: Any
    session_payload_keys: list[str] = field(default_factory=list)


class AuthenticationError(RuntimeError):
    pass


class ReauthenticationRequired(AuthenticationError):
    pass
