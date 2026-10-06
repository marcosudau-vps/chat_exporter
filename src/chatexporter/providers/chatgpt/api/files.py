from __future__ import annotations
from typing import Any
from .client import ApiClient, ApiError


class FileApi:
    def __init__(self, client: ApiClient):
        self.client = client

    def metadata(self, file_id: str) -> dict[str, Any]:
        payload = self.client.get_json(f"/backend-api/files/{file_id}")
        if not isinstance(payload, dict):
            raise ApiError("File metadata endpoint returned non-object JSON")
        return payload

    def download_ticket(self, file_id: str, *, gizmo_id: str | None = None) -> dict[str, Any]:
        # Gizmo-Dateien (use_case == "gizmo", direct_get_only == true) verweigern
        # den generischen Download mit HTTP 403. Mit dem Kontext-Parameter
        # `gizmo_id` antwortet der Endpunkt mit HTTP 200 und der signierten URL.
        params = {"gizmo_id": gizmo_id} if gizmo_id else None
        payload = self.client.get_json(f"/backend-api/files/{file_id}/download", params=params)
        if not isinstance(payload, dict) or not isinstance(payload.get("download_url"), str):
            raise ApiError("File download endpoint did not return download_url")
        return payload

    def download_bytes(self, signed_url: str) -> bytes:
        response = self.client.request("GET", signed_url, bearer=False)
        if not response.ok:
            # Body mitgeben: sonst waere ein HTTP 429 beim Dateidownload nicht
            # als Rate-Limit erkennbar und wuerde faelschlich Fehlerbudget kosten.
            payload = self.client.body_payload(response)
            raise self.client.error_for(response.status, "signed_download", payload)
        return response.body
