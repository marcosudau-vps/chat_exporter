from __future__ import annotations
from typing import Any, Iterator
from .client import ApiClient, ApiError, RateLimitError


class ConversationApi:
    def __init__(self, client: ApiClient):
        self.client = client
        #: Nur im Entwicklungsmodus gesetzt: hoechstens so viele Listing-Seiten je Bereich ...
        self.max_pages: int | None = None
        #: ... und nach so vielen Konversationsabrufen ein simuliertes Rate-Limit (HTTP 429).
        self.fetch_budget: int | None = None
        self.fetches = 0

    def list_page(self, *, offset: int, limit: int, archived: bool = False,
                  order: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("listing limit must be between 1 and 100")
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if order is not None:
            # Nur `updated` ist belegt (Browser-Request, API_CONTRACT);
            # `order=created` liefert HTTP 500.
            if order != "updated":
                raise ValueError("listing order must be 'updated' or None")
            params["order"] = order
        if archived:
            params["is_archived"] = "true"
        payload = self.client.get_json("/backend-api/conversations", params=params)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ApiError("Conversation listing returned an unexpected payload", endpoint="/backend-api/conversations", payload=payload)
        return payload

    def iter_scope(self, *, archived: bool, limit: int = 100) -> Iterator[dict[str, Any]]:
        offset = 0
        pages = 0
        seen_pages: set[tuple[str, ...]] = set()
        while True:
            page = self.list_page(offset=offset, limit=limit, archived=archived)
            items = page["items"]
            fingerprint = tuple(str(x.get("id")) for x in items if isinstance(x, dict))
            if fingerprint and fingerprint in seen_pages:
                raise ApiError("Conversation listing repeated an identical page; refusing a pagination loop", endpoint="/backend-api/conversations")
            seen_pages.add(fingerprint)
            for item in items:
                if isinstance(item, dict):
                    yield item
            if len(items) < limit:
                break
            pages += 1
            if self.max_pages is not None and pages >= self.max_pages:
                break
            offset += len(items)

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        if self.fetch_budget is not None:
            if self.fetches >= self.fetch_budget:
                raise RateLimitError("Entwicklungsmodus: simuliertes Rate-Limit", status=429,
                                     endpoint="/backend-api/conversation/<id>",
                                     payload={"detail": "Too many requests"})
            self.fetches += 1
        payload = self.client.get_json(f"/backend-api/conversation/{conversation_id}")
        if not isinstance(payload, dict):
            raise ApiError("Conversation endpoint returned non-object JSON", endpoint=f"/backend-api/conversation/{conversation_id}")
        return payload

    def get_textdocs(self, conversation_id: str) -> list[dict[str, Any]]:
        payload = self.client.get_json(f"/backend-api/conversation/{conversation_id}/textdocs")
        if not isinstance(payload, list):
            raise ApiError("Textdocs endpoint returned non-list JSON", endpoint=f"/backend-api/conversation/{conversation_id}/textdocs")
        return [x for x in payload if isinstance(x, dict)]
