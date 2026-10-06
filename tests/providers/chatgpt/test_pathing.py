import pytest
from chatexporter.providers.chatgpt.common.pathing import safe_component


def test_safe_component_rejects_path_traversal():
    with pytest.raises(ValueError): safe_component('file_../evil')
    with pytest.raises(ValueError): safe_component('a/b')
    assert safe_component('file_ABC-123_x') == 'file_ABC-123_x'
