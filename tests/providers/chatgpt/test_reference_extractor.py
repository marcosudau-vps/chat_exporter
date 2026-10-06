from chatexporter.providers.chatgpt.fetch.reference_extractor import extract_file_references, extract_tool_references, has_canvas_hint


def test_attachment_extraction(simple_raw):
    simple_raw["mapping"]["u1"]["message"]["metadata"]={"attachments":[{"id":"file_abc","name":"x.txt","mime_type":"text/plain","size":3,"library_file_id":"lib_1"}]}
    refs=extract_file_references(simple_raw)
    assert refs[0]["id"] == "file_abc"
    assert refs[0]["kind"] == "attachment"


def test_image_pointer_extraction(simple_raw):
    simple_raw["mapping"]["a1"]["message"]["content"]={"content_type":"multimodal_text","parts":[{"content_type":"image_asset_pointer","asset_pointer":"sediment://file_img","width":512,"height":512}]}
    refs=extract_file_references(simple_raw)
    assert len(refs) == 1
    ref = refs[0]
    assert ref["id"] == "file_img"
    assert ref["kind"] == "image_asset_pointer"
    assert ref["node_id"] == "a1"
    # Die Message-Id wird mitgefuehrt, damit Dateien eindeutig zuordenbar sind.
    assert "message_id" in ref
    assert ref["width"] == 512 and ref["height"] == 512


def test_tool_and_canvas_detection(simple_raw):
    simple_raw["mapping"]["a1"]["message"]["recipient"]="canmore.create_textdoc"
    refs=extract_tool_references(simple_raw)
    assert refs[0]["recipient"] == "canmore.create_textdoc"
    assert has_canvas_hint(simple_raw)
