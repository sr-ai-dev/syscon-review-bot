from src.review.structured_output import build_review_response_format


def _walk_schema(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_schema(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_schema(value)


def test_review_response_format_is_strict_json_schema():
    response_format = build_review_response_format()

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "review_result"
    assert response_format["json_schema"]["strict"] is True


def test_review_schema_makes_every_object_closed_and_required():
    schema = build_review_response_format()["json_schema"]["schema"]

    object_nodes = [node for node in _walk_schema(schema) if "properties" in node]
    assert object_nodes
    for node in object_nodes:
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])


def test_review_schema_removes_defaults_recursively():
    schema = build_review_response_format()["json_schema"]["schema"]

    assert all("default" not in node for node in _walk_schema(schema))
