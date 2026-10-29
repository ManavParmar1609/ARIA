"""JSON Schema helpers for structured output.

OpenAI-style strict mode requires every object to list all of its properties as required and to
set ``additionalProperties: false``. Guided-decoding backends (NIM, vLLM) are happiest with a
self-contained schema, so references are inlined.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from pydantic import BaseModel

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            return _inline_refs(copy.deepcopy(defs[name]), defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: _strictify(v) for k, v in node.items() if k not in ("default", "title")}
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        return node
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    return node


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    inlined = _inline_refs(raw, raw.get("$defs", {}))
    return _strictify(inlined)  # type: ignore[no-any-return]


def restrict_enum(schema: dict[str, Any], path: list[str], allowed: list[str]) -> dict[str, Any]:
    """Narrow an enum field (for example the adjudicator's severity to the prediction set)."""
    out = copy.deepcopy(schema)
    node = out
    for key in path:
        node = node["properties"][key]
    node.pop("anyOf", None)
    node["type"] = "string"
    node["enum"] = list(allowed)
    return out


def extract_json(text: str) -> Any:
    """Parse a JSON object from model output, tolerating think blocks and code fences."""
    cleaned = _THINK.sub("", text).strip()
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise
