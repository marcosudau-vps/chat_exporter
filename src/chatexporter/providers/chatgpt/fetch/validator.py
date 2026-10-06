from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GraphValidation:
    complete: bool
    current_node_resolved: bool
    dangling_parent_count: int
    root_count: int
    node_count: int
    warnings: list[str]


def validate_conversation_graph(payload: dict[str, Any]) -> GraphValidation:
    mapping = payload.get("mapping")
    current_node = payload.get("current_node")
    if not isinstance(mapping, dict):
        return GraphValidation(False, False, 0, 0, 0, ["mapping_missing_or_not_object"])
    current_resolved = isinstance(current_node, str) and current_node in mapping
    dangling = 0
    roots = 0
    warnings: list[str] = []
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            warnings.append(f"node_not_object:{node_id}")
            continue
        parent = node.get("parent")
        if parent is None:
            roots += 1
        elif parent not in mapping:
            dangling += 1
    if roots != 1:
        warnings.append(f"root_count:{roots}")
    complete = current_resolved and dangling == 0
    return GraphValidation(complete, current_resolved, dangling, roots, len(mapping), warnings)
