import pytest
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.sync.listing import fetch_complete_listing, DuplicateConversationError


class FakeClient:
    def __init__(self, pages): self.pages=pages; self.calls=[]
    def get_json(self,path,params=None):
        self.calls.append((path,dict(params or {})))
        key=(params.get("is_archived") == "true", params["offset"])
        return self.pages[key]


def test_listing_terminal_page_by_len_not_total():
    pages={
      (False,0): {"items":[{"id":"a"},{"id":"b"}],"total":999},
      (False,2): {"items":[{"id":"c"}],"total":3},
    }
    api=ConversationApi(FakeClient(pages))
    ids=[x["id"] for x in api.iter_scope(archived=False,limit=2)]
    assert ids == ["a","b","c"]


def test_limit_above_100_rejected():
    api=ConversationApi(FakeClient({}))
    with pytest.raises(ValueError): api.list_page(offset=0,limit=101)


def test_active_archived_merge():
    pages={
      (False,0): {"items":[{"id":"a","is_archived":False}],"total":1},
      (True,0): {"items":[{"id":"b","is_archived":True}],"total":1},
    }
    out=fetch_complete_listing(ConversationApi(FakeClient(pages)),limit=100)
    assert set(out)=={"a","b"}


def test_duplicate_between_scopes_rejected():
    pages={
      (False,0): {"items":[{"id":"a"}],"total":1},
      (True,0): {"items":[{"id":"a"}],"total":1},
    }
    with pytest.raises(DuplicateConversationError): fetch_complete_listing(ConversationApi(FakeClient(pages)),limit=100)


def test_repeated_page_loop_rejected():
    pages={
      (False,0): {"items":[{"id":"a"},{"id":"b"}],"total":999},
      (False,2): {"items":[{"id":"a"},{"id":"b"}],"total":999},
    }
    api=ConversationApi(FakeClient(pages))
    with pytest.raises(Exception):
        list(api.iter_scope(archived=False,limit=2))
