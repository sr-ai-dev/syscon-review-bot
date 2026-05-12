import pytest
from unittest.mock import AsyncMock, patch

from src.github.client import GitHubClient
from src.github.pr import get_pr_diff, get_pr_info, get_pr_reviews, get_repo_file


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
