from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph


def test_complete_graph(simple_raw):
    v=validate_conversation_graph(simple_raw)
    assert v.complete
    assert v.root_count == 1
    assert v.dangling_parent_count == 0


def test_dangling_parent_rejected(simple_raw):
    simple_raw["mapping"]["u1"]["parent"] = "missing"
    v=validate_conversation_graph(simple_raw)
    assert not v.complete
    assert v.dangling_parent_count == 1


def test_missing_current_node_rejected(simple_raw):
    simple_raw["current_node"]="missing"
    assert not validate_conversation_graph(simple_raw).complete


def test_branches_preserved(simple_raw):
    simple_raw["mapping"]["u1"]["children"] = ["a1", "alt"]
    simple_raw["mapping"]["alt"] = {"id":"alt", "parent":"u1", "children":[], "message": {"id":"alt","author":{"role":"assistant"},"content":{"content_type":"text","parts":["alternate"]},"metadata":{}}}
    assert validate_conversation_graph(simple_raw).complete
    assert "alt" in simple_raw["mapping"]
