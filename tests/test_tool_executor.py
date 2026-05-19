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
async def test_grep_uses_git_trees_and_finds_matching_paths():
    mock_gh = AsyncMock()
    # tree 응답
    tree_resp = {
        "tree": [
            {"path": "src/foo/getWaypointNode.ts", "type": "blob"},
            {"path": "src/bar/other.ts", "type": "blob"},
            {"path": "src/dir/", "type": "tree"},
        ]
    }
    # content 응답 — 첫 번째 파일에 패턴 있음
    contents = {
        "src/foo/getWaypointNode.ts": "def x():\n  getWaypointNode()\n  return 1\n",
        "src/bar/other.ts": "no match here\n",
    }
    async def get_json(path):
        if "git/trees" in path:
            return tree_resp
        # contents/<file>
        for fname, body in contents.items():
            if fname in path:
                import base64
                return {"content": base64.b64encode(body.encode()).decode(), "encoding": "base64"}
        return {}
    mock_gh.get_json = AsyncMock(side_effect=get_json)

    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")

    matches = await ex.grep("getWaypointNode")
    paths = [m["path"] for m in matches]
    assert "src/foo/getWaypointNode.ts" in paths
    assert "src/bar/other.ts" not in paths
    # matches 내부에 line 번호와 text가 있어야 함
    foo_match = next(m for m in matches if m["path"] == "src/foo/getWaypointNode.ts")
    assert any("getWaypointNode" in mm["text"] for mm in foo_match["matches"])


@pytest.mark.asyncio
async def test_grep_applies_path_glob_filter():
    mock_gh = AsyncMock()
    tree_resp = {
        "tree": [
            {"path": "src/a.py", "type": "blob"},
            {"path": "src/b.ts", "type": "blob"},
            {"path": "docs/c.md", "type": "blob"},
        ]
    }
    import base64
    async def get_json(path):
        if "git/trees" in path:
            return tree_resp
        return {"content": base64.b64encode(b"foo bar").decode(), "encoding": "base64"}
    mock_gh.get_json = AsyncMock(side_effect=get_json)

    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    matches = await ex.grep("foo", path_glob="src/*.ts")
    paths = [m["path"] for m in matches]
    assert paths == ["src/b.ts"]


@pytest.mark.asyncio
async def test_grep_caps_candidate_files_to_50():
    mock_gh = AsyncMock()
    tree_resp = {
        "tree": [
            {"path": f"src/f{i}.ts", "type": "blob"} for i in range(200)
        ]
    }
    import base64
    async def get_json(path):
        if "git/trees" in path:
            return tree_resp
        return {"content": base64.b64encode(b"match!").decode(), "encoding": "base64"}
    mock_gh.get_json = AsyncMock(side_effect=get_json)

    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    matches = await ex.grep("match!")
    # 실제 매칭 결과는 최대 10개로 cap (메타 sentinel 제외)
    real_hits = [m for m in matches if "path" in m]
    assert len(real_hits) <= 10
    # contents fetch는 후보 50개에 대해서만 실행됐어야 함 (tree 1회 + contents 50회 = 51회)
    assert mock_gh.get_json.await_count <= 51


@pytest.mark.asyncio
async def test_grep_returns_empty_when_tree_fetch_fails():
    mock_gh = AsyncMock()
    mock_gh.get_json = AsyncMock(side_effect=Exception("tree boom"))

    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    assert await ex.grep("foo") == []


@pytest.mark.asyncio
async def test_read_file_caches_within_executor_lifetime():
    import base64
    mock_gh = AsyncMock()
    mock_gh.get_json = AsyncMock(return_value={
        "content": base64.b64encode(b"hello").decode(),
        "encoding": "base64",
    })
    from src.review.tool_executor import GitHubToolExecutor
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    a = await ex.read_file("a.py")
    b = await ex.read_file("a.py")
    assert a == b == "hello"
    # 두 번째 호출은 캐시 — get_json 1회만
    assert mock_gh.get_json.await_count == 1


@pytest.mark.asyncio
async def test_grep_appends_truncated_meta_when_candidates_capped():
    import base64
    mock_gh = AsyncMock()
    tree_resp = {"tree": [{"path": f"src/f{i}.ts", "type": "blob"} for i in range(200)]}
    async def get_json(path):
        if "git/trees" in path:
            return tree_resp
        return {"content": base64.b64encode(b"no_match_pattern").decode(), "encoding": "base64"}
    mock_gh.get_json = AsyncMock(side_effect=get_json)
    from src.review.tool_executor import GitHubToolExecutor
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    matches = await ex.grep("foo")  # 매칭 0개
    # truncated meta는 그래도 등장 (200-50=150)
    assert any(m.get("_truncated_candidates") == 150 for m in matches if isinstance(m, dict))
