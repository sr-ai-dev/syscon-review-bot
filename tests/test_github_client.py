import pytest
from unittest.mock import AsyncMock, patch

from src.github.client import GitHubClient
from src.github.pr import get_pr_diff, get_pr_files, get_pr_info, get_pr_reviews, get_repo_file


class TestGitHubClient:
    @pytest.fixture
    def client(self):
        return GitHubClient(token="ghs_test")

    @pytest.mark.asyncio
    async def test_get_pr_diff(self, client):
        with patch.object(
            client, "get", new_callable=AsyncMock,
            return_value="diff --git a/x.py b/x.py\n+hello",
        ) as mock_get:
            diff = await get_pr_diff(client, "owner/repo", 1)

        assert "hello" in diff
        call = mock_get.call_args
        assert "/repos/owner/repo/pulls/1" in call.args[0]
        assert call.kwargs.get("accept") == "application/vnd.github.v3.diff"

    @pytest.mark.asyncio
    async def test_get_pr_info(self, client):
        with patch.object(
            client, "get_json", new_callable=AsyncMock,
            return_value={"title": "X", "body": "B", "head": {"ref": "f"}, "base": {"ref": "main"}},
        ):
            info = await get_pr_info(client, "owner/repo", 1)

        assert info["title"] == "X"

    @pytest.mark.asyncio
    async def test_get_repo_file_returns_content(self, client):
        import base64
        encoded = base64.b64encode(b"hello").decode()

        with patch.object(
            client, "get_json", new_callable=AsyncMock,
            return_value={"content": encoded, "encoding": "base64"},
        ):
            content = await get_repo_file(client, "owner/repo", "config.yml", "main")

        assert content == "hello"

    @pytest.mark.asyncio
    async def test_get_pr_reviews_returns_list(self, client):
        with patch.object(
            client, "get_json", new_callable=AsyncMock,
            return_value=[
                {
                    "body": "## 🤖 코드 리뷰 — 점수: 7/10\n...",
                    "state": "COMMENTED",
                    "submitted_at": "2026-05-11T11:20:26Z",
                    "user": {"login": "github-actions[bot]"},
                },
            ],
        ) as mock_get_json:
            reviews = await get_pr_reviews(client, "owner/repo", 42)

        assert len(reviews) == 1
        assert reviews[0]["body"].startswith("## 🤖")
        assert "/repos/owner/repo/pulls/42/reviews" in mock_get_json.call_args.args[0]

    @pytest.mark.asyncio
    async def test_get_repo_file_404_returns_none(self, client):
        import httpx

        async def raise_404(*args, **kwargs):
            request = httpx.Request("GET", "https://api.github.com/x")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("Not found", request=request, response=response)

        with patch.object(client, "get_json", side_effect=raise_404):
            content = await get_repo_file(client, "owner/repo", "config.yml", "main")

        assert content is None


class TestGetPrFiles:
    @pytest.fixture
    def client(self):
        return GitHubClient(token="ghs_test")

    @pytest.mark.asyncio
    async def test_single_page(self, client):
        page1 = [
            {"filename": "a.py", "patch": "@@ -1 +1 @@\n+x", "additions": 1, "deletions": 0, "status": "modified"},
        ]
        with patch.object(client, "get_json_list", new_callable=AsyncMock, return_value=page1):
            files = await get_pr_files(client, "owner/repo", 1)

        assert len(files) == 1
        assert files[0]["filename"] == "a.py"

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self, client):
        with patch.object(client, "get_json_list", new_callable=AsyncMock, return_value=[]) as mock:
            await get_pr_files(client, "owner/repo", 42)

        mock.assert_called_once_with("/repos/owner/repo/pulls/42/files")


class TestGetJsonList:
    @pytest.fixture
    def client(self):
        return GitHubClient(token="ghs_test")

    @pytest.mark.asyncio
    async def test_paginates_until_empty(self, client):
        import httpx

        page1_items = [{"id": i} for i in range(100)]
        page2_items = [{"id": 100 + i} for i in range(30)]

        responses = [
            httpx.Response(200, json=page1_items, request=httpx.Request("GET", "https://x")),
            httpx.Response(200, json=page2_items, request=httpx.Request("GET", "https://x")),
        ]
        call_idx = {"n": 0}

        async def mock_get(path, **kwargs):
            resp = responses[call_idx["n"]]
            call_idx["n"] += 1
            return resp

        with patch.object(client._http, "get", side_effect=mock_get):
            result = await client.get_json_list("/test")

        assert len(result) == 130
        assert call_idx["n"] == 2

    @pytest.mark.asyncio
    async def test_single_page_under_100(self, client):
        import httpx

        items = [{"id": i} for i in range(50)]
        resp = httpx.Response(200, json=items, request=httpx.Request("GET", "https://x"))

        async def mock_get(path, **kwargs):
            return resp

        with patch.object(client._http, "get", side_effect=mock_get):
            result = await client.get_json_list("/test")

        assert len(result) == 50
