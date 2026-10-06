from __future__ import annotations
import json
from typing import Any
from playwright.sync_api import Error as PlaywrightError
from .session import AuthIdentity, AuthSession, AuthenticationError, ReauthenticationRequired


def _identity_from_session(payload: dict[str, Any]) -> AuthIdentity:
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    return AuthIdentity(
        user_id=(user.get("id") or account.get("id")),
        email=(user.get("email") or account.get("email")),
        name=(user.get("name") or account.get("name")),
    )


def _me_is_real(me: dict[str, Any]) -> bool:
    uid = str(me.get("id") or "")
    if not uid or uid.startswith("ua-"):
        return False
    return bool(str(me.get("email") or "").strip() or str(me.get("name") or "").strip())


def _identity_consistent(session_identity: AuthIdentity, me: dict[str, Any]) -> bool:
    if session_identity.user_id and me.get("id") and session_identity.user_id != me.get("id"):
        return False
    if session_identity.email and me.get("email") and session_identity.email.lower() != str(me.get("email")).lower():
        return False
    return True


class AuthBroker:
    def __init__(self, cdp_session, base_url: str, timeout_ms: int, *, counter: Any = None,
                 auto_login: Any = None):
        self.cdp = cdp_session
        self.base_url = base_url.rstrip("/")
        self.timeout_ms = timeout_ms
        #: Optionaler RequestCounter (Kategorie "auth").
        self.counter = counter
        #: Optional: ``(is_logged_in) -> LoginResult`` (``auto_login.make_auto_login``).
        self.auto_login = auto_login
        #: Ergebnis der letzten automatischen Anmeldung (Laufbericht), ohne Zugangsdaten.
        self.auto_login_result: Any = None

    def _get(self, context: Any, url: str, **kwargs: Any) -> Any:
        try:
            response = context.request.get(url, **kwargs)
        except Exception:
            if self.counter is not None:
                self.counter.record("auth")
            raise
        if self.counter is not None:
            self.counter.record("auth", response.status)
        return response

    def acquire(self, interactive: bool = True) -> AuthSession:
        result = self._probe()
        if result is not None:
            return result
        failure = ""
        if self.auto_login is not None:
            found: list[AuthSession] = []

            def logged_in() -> bool:
                session = self._probe()
                if session is not None:
                    found.append(session)
                return session is not None

            outcome = self.auto_login(logged_in)
            self.auto_login_result = outcome
            if outcome.ok and found:
                return found[-1]
            failure = outcome.reason
            print(f"Automatische Anmeldung nicht abgeschlossen: {failure}", flush=True)
        if not interactive:
            raise ReauthenticationRequired(
                "No valid ChatGPT session in the browser profile."
                + (f" Automatische Anmeldung: {failure}" if failure else ""))

        show = getattr(self.cdp, "show_window", None)
        if callable(show) and show():
            print("\nDas Browserfenster wird jetzt angezeigt.", flush=True)
        print("\nKeine gültige ChatGPT-Sitzung gefunden.", flush=True)
        print("Bitte im geöffneten Dedicated-Edge-Fenster normal bei ChatGPT anmelden.", flush=True)
        print("Du kannst den Login vollständig abschließen; der Browser darf dabei navigieren.", flush=True)

        while True:
            input("Danach hier ENTER drücken, um die Sitzung erneut zu prüfen (Strg+C zum Abbrechen): ")
            result = self._probe()
            if result is not None:
                hide = getattr(self.cdp, "hide_window", None)
                if callable(hide):
                    hide()
                return result
            print(
                "Noch keine validierbare ChatGPT-Sitzung erkannt. "
                "Falls der Browser noch lädt oder umleitet, dort fertig werden lassen und hier erneut ENTER drücken.",
                flush=True,
            )

    def _probe(self) -> AuthSession | None:
        """Probe the browser-bound authenticated session without depending on page JS state.

        The primary probe uses BrowserContext.request, which shares the browser context's
        cookies but is not tied to a page execution context. This avoids the login race where
        a page navigation destroys a page.evaluate() execution context immediately after MFA.
        """
        context = self.cdp.context
        if context is None:
            raise AuthenticationError("CDP browser context is not available")

        try:
            response = self._get(
                context, self.base_url + "/api/auth/session",
                headers={"Cache-Control": "no-cache"},
                timeout=self.timeout_ms,
            )
        except PlaywrightError as exc:
            raise AuthenticationError("/api/auth/session request failed in the browser context") from exc

        if not (200 <= response.status < 300):
            return None
        try:
            payload = response.json()
        except Exception:
            try:
                payload = json.loads(response.text())
            except Exception:
                return None
        if not isinstance(payload, dict):
            return None

        token = payload.get("accessToken")
        if not isinstance(token, str) or not token:
            return None

        try:
            me_response = self._get(
                context, self.base_url + "/backend-api/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout_ms,
            )
        except PlaywrightError as exc:
            raise AuthenticationError("/backend-api/me validation request failed") from exc

        if not (200 <= me_response.status < 300):
            return None
        try:
            me = me_response.json()
        except Exception as exc:
            raise AuthenticationError("/backend-api/me did not return JSON") from exc
        if not isinstance(me, dict) or not _me_is_real(me):
            return None

        identity = _identity_from_session(payload)
        if not _identity_consistent(identity, me):
            raise AuthenticationError("Session identity does not match /backend-api/me payload")
        if identity.user_id is None:
            identity.user_id = str(me.get("id") or "") or None
        if identity.email is None:
            identity.email = str(me.get("email") or "") or None
        if identity.name is None:
            identity.name = str(me.get("name") or "") or None

        page = self.cdp.ensure_chatgpt_page()
        return AuthSession(
            access_token=token,
            identity=identity,
            page=page,
            context=context,
            session_payload_keys=sorted(payload.keys()),
        )
