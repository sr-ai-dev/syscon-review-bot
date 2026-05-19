import json
import pytest
from unittest.mock import AsyncMock

from src.review.llm_tools import TOOL_SCHEMAS, dispatch_tool_call


def test_tool_schemas_include_read_file_and_grep():
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert "read_file" in names
    assert "grep" in names


def test_tool_schemas_follow_openai_format():
    for t in TOOL_SCHEMAS:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "description" in t["function"]
        assert "parameters" in t["function"]
        assert t["function"]["parameters"]["type"] == "object"


@pytest.mark.asyncio
async def test_dispatch_read_file_calls_executor():
    ex = AsyncMock()
    ex.read_file.return_value = "file body"
    out = await dispatch_tool_call(
        {"function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}},
        ex,
    )
    ex.read_file.assert_awaited_once_with("a.py")
    assert "file body" in out


@pytest.mark.asyncio
async def test_dispatch_grep_calls_executor():
    ex = AsyncMock()
    ex.grep.return_value = [{"path": "a.py"}, {"path": "b.py"}]
    out = await dispatch_tool_call(
        {"function": {"name": "grep", "arguments": json.dumps({"pattern": "foo", "path_glob": "src/**"})}},
        ex,
    )
    ex.grep.assert_awaited_once_with("foo", "src/**")
    assert "a.py" in out and "b.py" in out


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error_string():
    ex = AsyncMock()
    out = await dispatch_tool_call(
        {"function": {"name": "delete_repo", "arguments": "{}"}},
        ex,
    )
    assert "error" in out.lower() or "unknown" in out.lower()


@pytest.mark.asyncio
async def test_dispatch_truncates_oversized_result():
    ex = AsyncMock()
    ex.read_file.return_value = "x" * 100000
    out = await dispatch_tool_call(
        {"function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}},
        ex,
        max_chars=1000,
    )
    assert len(out) <= 1200
    assert "truncated" in out.lower() or "잘림" in out
