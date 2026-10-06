from chatexporter.providers.chatgpt.storage.envelope import build_envelope
from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation
from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph


def test_exact_envelope_core(simple_raw, summary):
 f=FetchedConversation(simple_raw,[],[],[],validate_conversation_graph(simple_raw),[])
 env=build_envelope(summary,f)
 assert env["storage_schema_version"] == 1
 assert env["conversation_id"] == "c1"
 assert env["acquisition"]["complete"] is True
 assert len(env["integrity"]["raw_payload_sha256"]) == 64
 assert "raw" in env and "file_references" in env and "textdocs" in env
