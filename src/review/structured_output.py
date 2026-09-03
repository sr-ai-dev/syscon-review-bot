from copy import deepcopy
from typing import Any

from src.models.review import ReviewResult


def _make_strict(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("default", None)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
            node["additionalProperties"] = False
        for value in node.values():
            _make_strict(value)
    elif isinstance(node, list):
        for value in node:
            _make_strict(value)


def build_review_response_format() -> dict[str, Any]:
    schema = deepcopy(ReviewResult.model_json_schema())
    _make_strict(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "review_result",
            "strict": True,
            "schema": schema,
        },
    }


REVIEW_RESPONSE_FORMAT = build_review_response_format()
