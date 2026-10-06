"""Neuanmeldung mitten im Lauf: HTTP 401 -> Anmeldung erneuern, Anfrage einmal wiederholen."""

from __future__ import annotations

import json

from chatexporter.providers.chatgpt.api.client import ApiClient, RequestCounter


class _Resp:
    def __init__(self, status):
        self.status, self.headers = status, {}

    def body(self):
        return b'{"items": []}'


class _Req:
    """Antwortet 401, solange nicht der erwartete Token mitgeschickt wird."""

    def __init__(self, valid="neu"):
        self.valid, self.seen = valid, []

    def get(self, url, **kwargs):
        token = (kwargs.get("headers") or {}).get("Authorization", "")
        self.seen.append(token)
        return _Resp(200 if token in (f"Bearer {self.valid}", "") else 401)


class _Ctx:
    def __init__(self, valid="neu"):
        self.request = _Req(valid)


def test_expired_token_is_renewed_and_the_request_repeated_once():
    ctx, counter, calls = _Ctx(), RequestCounter(), []
    client = ApiClient(ctx, "alt", base_url="https://chatgpt.com", counter=counter,
                       reauthenticate=lambda: calls.append(1) or "neu")
    response = client.request("GET", "/backend-api/conversations")
    assert response.status == 200 and calls == [1]
    assert ctx.request.seen == ["Bearer alt", "Bearer neu"]
    assert client.access_token == "neu"
    assert counter.total == 2, "beide gesendeten Anfragen zaehlen"
    assert client.reauth_events == [{"endpoint": "/backend-api/conversations", "ok": True, "reason": "",
                                     "token_changed": True}]
    assert "alt" not in json.dumps(client.reauth_events) and "neu" not in json.dumps(client.reauth_events)


def test_without_renewal_a_401_stays_a_401():
    client = ApiClient(_Ctx(), "alt", base_url="https://chatgpt.com")
    assert client.request("GET", "/backend-api/conversations").status == 401


def test_failed_renewal_keeps_the_original_401_and_records_why():
    def fails():
        raise RuntimeError("Automatische Anmeldung: Sicherheitspruefung im Browser")
    ctx = _Ctx()
    client = ApiClient(ctx, "alt", base_url="https://chatgpt.com", reauthenticate=fails)
    assert client.request("GET", "/backend-api/conversations").status == 401
    assert ctx.request.seen == ["Bearer alt"], "ohne neue Sitzung keine Wiederholung"
    assert client.reauth_events[0]["ok"] is False and "Sicherheitspruefung" in client.reauth_events[0]["reason"]
    empty = ApiClient(_Ctx(), "alt", base_url="https://chatgpt.com", reauthenticate=lambda: None)
    assert empty.request("GET", "/x").status == 401 and empty.reauth_events[0]["ok"] is False


def test_renewals_per_run_are_limited():
    calls = []
    client = ApiClient(_Ctx(valid="nie"), "alt", base_url="https://chatgpt.com",
                       reauthenticate=lambda: calls.append(1) or f"t{len(calls)}", max_reauth=2)
    for _ in range(4):
        assert client.request("GET", "/backend-api/conversations").status == 401
    assert len(calls) == 2 and len(client.reauth_events) == 2


def test_requests_without_bearer_never_trigger_a_renewal():
    calls = []

    class Req:
        def get(self, url, **kwargs):
            return _Resp(401)

    class Ctx:
        request = Req()
    client = ApiClient(Ctx(), "alt", base_url="https://chatgpt.com", reauthenticate=lambda: calls.append(1) or "x")
    assert client.request("GET", "https://files.example/signed", bearer=False).status == 401
    assert calls == []


def test_other_errors_never_trigger_a_renewal():
    calls = []

    class Req:
        def get(self, url, **kwargs):
            return _Resp(403)

    class Ctx:
        request = Req()
    client = ApiClient(Ctx(), "alt", base_url="https://chatgpt.com", reauthenticate=lambda: calls.append(1) or "x")
    assert client.request("GET", "/backend-api/conversations").status == 403 and calls == []


# -- Einbindung in den Lauf --------------------------------------------------------------------------

class _Broker:
    def __init__(self, token="frisch", fail=None):
        self.token, self.fail, self.calls = token, fail, []

    def acquire(self, interactive=True):
        self.calls.append(interactive)
        if self.fail:
            raise self.fail
        token = self.token

        class Session:
            access_token = token
        return Session()


def test_reauthenticator_renews_through_the_broker_only_when_needed():
    from chatexporter.providers.chatgpt.contract import reauthenticator
    made, said = [], []
    broker = _Broker()
    renew = reauthenticator(None, object(), interactive=False, say=said.append,
                            broker_factory=lambda: made.append(1) or broker)
    assert made == [], "Broker erst beim ersten 401"
    assert renew() == "frisch" and renew() == "frisch"
    assert made == [1] and broker.calls == [False, False], "ohne Interaktion: nie Anmeldung von Hand"
    assert any("HTTP 401" in line for line in said)


def test_failed_reauthentication_ends_like_before_with_the_reason():
    from chatexporter.providers.chatgpt.auth.session import ReauthenticationRequired
    from chatexporter.providers.chatgpt.contract import reauthenticator
    broker = _Broker(fail=ReauthenticationRequired("Automatische Anmeldung: Sicherheitspruefung"))
    client = ApiClient(_Ctx(), "alt", base_url="https://chatgpt.com",
                       reauthenticate=reauthenticator(None, object(), interactive=False,
                                                      broker_factory=lambda: broker))
    assert client.request("GET", "/backend-api/conversations").status == 401
    assert "Sicherheitspruefung" in client.reauth_events[0]["reason"]
