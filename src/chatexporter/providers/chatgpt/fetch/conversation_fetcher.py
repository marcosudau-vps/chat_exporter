from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.common.redaction import sanitize_reasoning_payload
from .reference_extractor import extract_file_references, extract_tool_references, has_canvas_hint
from .validator import GraphValidation, validate_conversation_graph


class IncompleteConversationError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchedConversation:
    raw: dict[str, Any]
    textdocs: list[dict[str, Any]]
    file_references: list[dict[str, Any]]
    tool_references: list[dict[str, Any]]
    validation: GraphValidation
    supplemental_errors: list[str]


class ConversationFetcher:
    def __init__(self, api: ConversationApi, *, fetch_textdocs: bool = True):
        self.api = api
        self.fetch_textdocs = fetch_textdocs

    def fetch(self, conversation_id: str) -> FetchedConversation:
        return self.build(conversation_id, self.api.get_conversation(conversation_id))

    def build(self, conversation_id: str, original: dict[str, Any]) -> FetchedConversation:
        """Wie :meth:`fetch`, aber aus einer bereits geladenen Detailantwort
        (spart den erneuten Abruf, z. B. nach der Grenzpruefung)."""
        raw = sanitize_reasoning_payload(original)
        validation = validate_conversation_graph(raw)
        if not validation.complete:
            raise IncompleteConversationError(
                f"Conversation {conversation_id} failed completeness gate: "
                f"current_node_resolved={validation.current_node_resolved}, "
                f"dangling_parent_count={validation.dangling_parent_count}"
            )
        files = extract_file_references(raw)
        tools = extract_tool_references(raw)
        textdocs: list[dict[str, Any]] = []
        supplemental_errors: list[str] = []
        if self.fetch_textdocs and has_canvas_hint(raw):
            try:
                textdocs = sanitize_reasoning_payload(self.api.get_textdocs(conversation_id))
            except Exception as exc:
                # Textdocs are a convenience current-state snapshot; Canvas history
                # remains in the authoritative graph, so this must not discard an
                # otherwise complete conversation.
                supplemental_errors.append(f"textdocs:{type(exc).__name__}:{exc}")
        return FetchedConversation(raw=raw, textdocs=textdocs, file_references=files, tool_references=tools, validation=validation, supplemental_errors=supplemental_errors)
