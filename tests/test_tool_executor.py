import pytest
from unittest.mock import AsyncMock

from src.review.tool_executor import GitHubToolExecutor


@pytest.mark.asyncio
async def test_read_file_returns_source():
    mock_gh = AsyncMock()
    mock_gh.get_json.return_value = {
        "content": "ZGVmIGZvbygpOgogICAgcmV0dXJuIDE=\n",  # base64 of "def foo():\n    return 1"
        "encoding": "base64",
    }
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")

    src = await ex.read_file("a.py")
    assert "def foo()" in src


@pytest.mark.asyncio
async def test_read_file_returns_empty_on_404():
    import httpx

    mock_gh = AsyncMock()

    class _Resp:
        status_code = 404

    mock_gh.get_json.side_effect = httpx.HTTPStatusError(
        "not found", request=None, response=_Resp()
    )
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    assert await ex.read_file("missing.py") == ""


@pytest.mark.asyncio
async def test_grep_returns_path_matches_capped():
    mock_gh = AsyncMock()
    mock_gh.get_json.return_value = {
        "items": [
            {"path": f"src/file_{i}.py"} for i in range(30)
        ]
    }
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    matches = await ex.grep("foo")
    assert len(matches) <= 10
    assert all("path" in m for m in matches)


@pytest.mark.asyncio
async def test_grep_swallows_search_errors_returns_empty():
    mock_gh = AsyncMock()
    mock_gh.get_json.side_effect = Exception("rate limited")
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    assert await ex.grep("foo") == []
