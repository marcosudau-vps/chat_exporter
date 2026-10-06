"""Zaehlung der an ChatGPT gesendeten Anfragen je Lauf."""

import pytest

from chatexporter.providers.chatgpt.api.client import (
    ApiClient, ApiError, RequestCounter, request_category,
)
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.api.files import FileApi
from chatexporter.providers.chatgpt.auth.broker import AuthBroker
from chatexporter.providers.chatgpt.contract import contract_result


@pytest.mark.parametrize("path,bearer,expected", [
    ("/backend-api/conversations", True, "listing"),
    ("/backend-api/conversation/abc", True, "conversation"),
    ("/backend-api/conversation/abc/textdocs", True, "textdocs"),
    ("/backend-api/files/file_1", True, "file_metadata"),
    ("/backend-api/files/file_1/download", True, "file_ticket"),
    ("https://files.example/signed?sig=x", False, "file_content"),
    ("https://chatgpt.com/api/auth/session", True, "auth"),
    ("https://chatgpt.com/backend-api/me", True, "auth"),
    ("/backend-api/sonstwas", True, "other"),
])
def test_request_category(path, bearer, expected):
    assert request_category(path, bearer=bearer) == expected


class _Resp:
    def __init__(self, status, body=b'{"items": []}'):
        self.status = status; self.headers = {}; self._body = body
    def body(self):
        return self._body


class _Req:
    def __init__(self, statuses):
        self.statuses = list(statuses); self.urls = []
    def get(self, url, **kwargs):
        self.urls.append(url)
        status = self.statuses.pop(0)
        if status == "boom":
            raise RuntimeError("Netzwerk weg")
        if status == 429:
            return _Resp(429, b'{"detail": "Too many requests"}')
        return _Resp(status, b'{"items": [], "download_url": "https://files.example/x?sig=1", "id": "u1"}')


class _Ctx:
    def __init__(self, statuses):
        self.request = _Req(statuses)


def test_api_client_counts_every_sent_request_including_failures():
    counter = RequestCounter()
    client = ApiClient(_Ctx([200, 429, 200, 200, "boom"]), "t", base_url="https://chatgpt.com",
                       counter=counter)
    api = ConversationApi(client)
    api.list_page(offset=0, limit=10)
    with pytest.raises(ApiError):
        api.list_page(offset=10, limit=10)
    files = FileApi(client)
    ticket = files.download_ticket("file_1")
    files.download_bytes(ticket["download_url"])
    with pytest.raises(RuntimeError):
        api.get_conversation("c1")
    data = counter.as_dict()
    assert data["total"] == 5
    assert data["by_category"] == {"listing": 2, "file_ticket": 1, "file_content": 1,
                                   "conversation": 1}
    assert data["rate_limited_total"] == 1
    assert data["rate_limited_by_category"] == {"listing": 1}


def test_auth_broker_counts_auth_requests():
    counter = RequestCounter()

    class _Cdp:
        context = _Ctx([401])

    broker = AuthBroker(_Cdp(), "https://chatgpt.com", 1000, counter=counter)
    assert broker._probe() is None
    assert counter.as_dict()["by_category"] == {"auth": 1}


def test_request_total_reaches_contract_stats_and_detail():
    report = {"aborted": False, "stats": {"fetched": 1},
              "requests": {"total": 7, "by_category": {"listing": 1, "conversation": 6}},
              "verification": {"requests": 3, "confirmed": True}}
    result = contract_result(report)
    assert result["stats"]["requests_total"] == 7
    assert result["detail"]["requests"]["by_category"]["conversation"] == 6
    assert result["detail"]["verification"]["confirmed"] is True
