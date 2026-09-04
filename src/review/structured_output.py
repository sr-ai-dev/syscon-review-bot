from copy import deepcopy
from typing import Any

from src.models.review import ReviewResult
from src.models.review_pipeline import ReviewPartial


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


def build_model_response_format(model: type, name: str) -> dict[str, Any]:
    schema = deepcopy(model.model_json_schema())
    _make_strict(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


def build_review_response_format() -> dict[str, Any]:
    return build_model_response_format(ReviewResult, "review_result")


REVIEW_RESPONSE_FORMAT = build_review_response_format()
REVIEW_PARTIAL_RESPONSE_FORMAT = build_model_response_format(
    ReviewPartial, "review_partial"
)
