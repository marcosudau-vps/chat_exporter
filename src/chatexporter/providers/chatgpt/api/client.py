from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from chatexporter.providers.chatgpt.common.redaction import safe_url


class ApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, endpoint: str | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.endpoint = endpoint
        self.payload = payload


class RateLimitError(ApiError):
    """Serverseitiges Rate-Limit (HTTP 429).

    Bewusst eine eigene Klasse: ein Rate-Limit ist kein Defekt, sondern ein
    regulaerer, erwartbarer Serverzustand bei groesseren Syncs. Der
    Orchestrator zaehlt ihn deshalb NICHT gegen das Fehlerbudget.

    Die Erkennung prueft zusaetzlich zum Status den Antwortbody. Gemessen
    wurde ueber 37 reale 429-Antworten ausnahmslos ``{"detail": "Too many
    requests"}``. Ein 429 mit abweichendem ``detail`` kann eine andere
    Ursache haben und wird deshalb wie ein normaler Fehler behandelt.
    """

    #: Kleinbuchstaben-Vergleichswert des bestaetigten Rate-Limit-Bodys.
    DETAIL = "too many requests"

    @staticmethod
    def detail_of(payload: Any) -> str:
        if isinstance(payload, dict):
            value = payload.get("detail")
            if isinstance(value, str):
                return value.strip().lower()
        return ""

    @classmethod
    def matches(cls, status: int | None, payload: Any) -> bool:
        return status == 429 and cls.detail_of(payload) == cls.DETAIL


class ApiTransportClosedError(ApiError):
    """Fatal browser-bound transport failure.

    The Gen4 API transport intentionally depends on the live Playwright browser
    context. If that context/browser disappears, continuing the sync would only
    create a storm of identical failed requests. This exception lets the
    orchestrator fail closed immediately.
    """


@dataclass(slots=True)
class ApiResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def _transport_was_closed(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "targetclosed" in name:
        return True
    markers = (
        "request context disposed",
        "target page, context or browser has been closed",
        "browser has been closed",
        "context has been closed",
        "target closed",
        # Playwright-Treiber weg (ERR-SYNC-CONN-CLOSED, Lauf 20260924T214820Z): jede weitere
        # Anfrage scheitert ebenso -> fatal statt Fehlerbudget.
        "connection closed while reading from the driver",
    )
    return any(marker in text for marker in markers)


#: Kategorien der Anfragezaehlung (je Endpunkt; ob Endpunkte ein gemeinsames
#: Kontingent teilen, ist nur fuer Listing und Konversation gemessen).
REQUEST_CATEGORIES = ("auth", "listing", "conversation", "textdocs",
                      "file_metadata", "file_ticket", "file_content", "other")


def request_category(path_or_url: str, *, bearer: bool = True) -> str:
    """Ordnet eine Anfrage einer Zaehlkategorie zu."""
    if path_or_url.startswith(("http://", "https://")):
        if not bearer:
            return "file_content"  # signierte Download-URL
        path = safe_url(path_or_url).get("path") or ""
    else:
        path = path_or_url.split("?", 1)[0]
    if path in ("/api/auth/session", "/backend-api/me"):
        return "auth"
    if path == "/backend-api/conversations":
        return "listing"
    if path.startswith("/backend-api/conversation/"):
        return "textdocs" if path.endswith("/textdocs") else "conversation"
    if path.startswith("/backend-api/files/"):
        return "file_ticket" if path.endswith("/download") else "file_metadata"
    return "other"


class RequestCounter:
    """Zaehlt die an ChatGPT gesendeten Anfragen eines Laufs (je Kategorie).

    Gezaehlt wird jede gesendete Anfrage, auch fehlgeschlagene; HTTP-429-
    Antworten (Rate-Limit) zusaetzlich getrennt. Enthaelt keine Inhalte.
    """

    def __init__(self) -> None:
        self.sent: dict[str, int] = {c: 0 for c in REQUEST_CATEGORIES}
        self.rate_limited: dict[str, int] = {c: 0 for c in REQUEST_CATEGORIES}

    def record(self, category: str, status: int | None = None) -> None:
        category = category if category in self.sent else "other"
        self.sent[category] += 1
        if status == 429:
            self.rate_limited[category] += 1

    @property
    def total(self) -> int:
        return sum(self.sent.values())

    def as_dict(self) -> dict[str, Any]:
        return {"total": self.total,
                "by_category": {k: v for k, v in self.sent.items() if v},
                "rate_limited_total": sum(self.rate_limited.values()),
                "rate_limited_by_category": {k: v for k, v in self.rate_limited.items() if v}}


class ApiClient:
    """Thin browser-bound HTTP transport. No persistence, merge, or pagination logic.

    Optional zaehlt ein :class:`RequestCounter` jede gesendete Anfrage. Optional erneuert
    ``reauthenticate`` bei HTTP 401 die Anmeldung (neuer Token) und die Anfrage wird
    genau einmal wiederholt – hoechstens ``max_reauth``-mal je Lauf.
    """
    def __init__(self, context: Any, access_token: str, *, base_url: str, timeout_ms: int = 120000,
                 counter: RequestCounter | None = None,
                 reauthenticate: Callable[[], str | None] | None = None, max_reauth: int = 2):
        self.context = context
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.timeout_ms = timeout_ms
        self.counter = counter
        #: Optional: holt bei HTTP 401 eine neue Sitzung (Token) – Neuanmeldung mitten im Lauf.
        self.reauthenticate = reauthenticate
        #: Hoechstens so viele Erneuerungen je Lauf (verhindert Schleifen bei dauerhaftem 401).
        self.max_reauth = max_reauth
        #: Erneuerungen dieses Laufs, ohne Tokens: {"endpoint", "ok", "reason", ["token_changed"]}.
        self.reauth_events: list[dict[str, Any]] = []

    def request(self, method: str, path_or_url: str, *, params: dict[str, Any] | None = None,
                json_body: Any = None, bearer: bool = True, headers: dict[str, str] | None = None) -> ApiResponse:
        url = path_or_url if path_or_url.startswith("http://") or path_or_url.startswith("https://") else self.base_url + path_or_url
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        req_headers = dict(headers or {})
        if bearer:
            req_headers["Authorization"] = f"Bearer {self.access_token}"
        kwargs: dict[str, Any] = {"headers": req_headers, "timeout": self.timeout_ms}
        if json_body is not None:
            kwargs["data"] = json.dumps(json_body, ensure_ascii=False)
            req_headers.setdefault("Content-Type", "application/json")
        category = request_category(path_or_url, bearer=bearer)
        response = self._send(method, url, kwargs, category)
        if (response.status == 401 and bearer and self.reauthenticate is not None
                and len(self.reauth_events) < self.max_reauth and self._renew(safe_url(url).get("path"))):
            req_headers["Authorization"] = f"Bearer {self.access_token}"
            response = self._send(method, url, kwargs, category)
        return ApiResponse(status=response.status, headers=dict(response.headers), body=response.body(), url=url)

    def _renew(self, endpoint: str | None) -> bool:
        """Neue Sitzung holen (``reauthenticate``); scheitert nie laut – dann bleibt es beim 401."""
        event: dict[str, Any] = {"endpoint": endpoint, "ok": False, "reason": ""}
        self.reauth_events.append(event)
        try:
            token = self.reauthenticate()
        except Exception as exc:  # noqa: BLE001  z. B. ReauthenticationRequired ohne Interaktion
            event["reason"] = f"{type(exc).__name__}: {exc}"[:300]
            return False
        if not token:
            event["reason"] = "keine neue Sitzung erhalten"
            return False
        event.update(ok=True, token_changed=token != self.access_token)
        self.access_token = token
        return True

    def _send(self, method: str, url: str, kwargs: dict[str, Any], category: str) -> Any:
        """Eine Anfrage senden und zaehlen; ein geschlossener Browser ist ein fataler Transportfehler."""
        try:
            response = getattr(self.context.request, method.lower())(url, **kwargs)
        except Exception as exc:
            if self.counter is not None:
                self.counter.record(category)
            if _transport_was_closed(exc):
                raise ApiTransportClosedError(
                    "Browser-bound API request context was closed; sync cannot continue safely",
                    endpoint=safe_url(url).get("path"),
                ) from exc
            raise
        if self.counter is not None:
            self.counter.record(category, response.status)
        return response

    @staticmethod
    def error_for(status: int, endpoint: str, payload: Any) -> ApiError:
        """Waehlt die passende Fehlerklasse anhand von Status UND Body."""
        message = f"HTTP {status} for {endpoint}"
        if RateLimitError.matches(status, payload):
            return RateLimitError(message, status=status, endpoint=endpoint, payload=payload)
        return ApiError(message, status=status, endpoint=endpoint, payload=payload)

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self.request("GET", path, params=params)
        try:
            payload = response.json()
        except Exception as exc:
            raise ApiError(f"Expected JSON from {safe_url(response.url)}", status=response.status, endpoint=path) from exc
        if not response.ok:
            raise self.error_for(response.status, path, payload)
        return payload

    def body_payload(self, response: "ApiResponse") -> Any:
        """Best-effort JSON-Body, ohne bei Nicht-JSON zu scheitern."""
        try:
            return response.json()
        except Exception:
            return None
