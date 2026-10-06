from types import SimpleNamespace

from chatexporter.providers.chatgpt.auth.broker import AuthBroker, _me_is_real, _identity_consistent
from chatexporter.providers.chatgpt.auth.session import AuthIdentity


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def json(self):
        return self._payload

    def text(self):
        return ""


class FakeRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FakeCdp:
    def __init__(self, responses):
        self.context = SimpleNamespace(request=FakeRequest(responses))
        self.page = object()

    def ensure_chatgpt_page(self):
        return self.page


def test_anonymous_200_not_authenticated():
    assert not _me_is_real({"id": "ua-123", "email": "", "name": ""})


def test_real_me_payload_authenticated_shape():
    assert _me_is_real({"id": "user-123", "email": "synthetic-email", "name": "A"})


def test_identity_mismatch_rejected():
    assert not _identity_consistent(AuthIdentity(user_id="u1", email="synthetic-email"), {"id": "u2", "email": "synthetic-email"})


def test_identity_match():
    assert _identity_consistent(AuthIdentity(user_id="u1", email="SYNTHETIC-EMAIL"), {"id": "u1", "email": "synthetic-email"})


def test_probe_uses_browser_context_request_and_validates_bearer():
    cdp = FakeCdp([
        FakeResponse(200, {
            "accessToken": "synthetic-token",
            "user": {"id": "user-123", "email": "synthetic-email", "name": "A"},
        }),
        FakeResponse(200, {"id": "user-123", "email": "synthetic-email", "name": "A"}),
    ])
    session = AuthBroker(cdp, "https://chatgpt.com", 1000)._probe()
    assert session is not None
    assert session.access_token == "synthetic-token"
    assert len(cdp.context.request.calls) == 2
    assert cdp.context.request.calls[0][0].endswith("/api/auth/session")
    assert cdp.context.request.calls[1][0].endswith("/backend-api/me")
    assert cdp.context.request.calls[1][1]["headers"]["Authorization"] == "Bearer synthetic-token"


def test_probe_returns_none_without_token():
    cdp = FakeCdp([FakeResponse(200, {"user": {"id": "user-123"}})])
    assert AuthBroker(cdp, "https://chatgpt.com", 1000)._probe() is None
