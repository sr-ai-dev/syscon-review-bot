import pytest
from unittest.mock import AsyncMock, patch

from src.review.engine import review_pr, ReviewContext
from src.models.review import ReviewResult, Decision, Issue
from src.models.config import ReviewConfig


@pytest.fixture
def context():
    return ReviewContext(repo="owner/repo", pr_number=42)


@pytest.fixture
def good_review():
    return ReviewResult(
        score=8, summary="Good", decision=Decision.COMMENT,
        issues=[Issue(severity="warning", category="x", file="a.py",
                      line=1, description="d", suggestion="s")],
        good_points=["Nice"],
    )


@pytest.mark.asyncio
async def test_review_pr_full_flow(context, good_review):
    mock_github = AsyncMock()
    mock_github.get.return_value = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n+hello"
    )
    mock_github.get_json.return_value = {
        "title": "T", "body": "B",
        "head": {"ref": "feat"}, "base": {"ref": "main"},
    }
    mock_github.post = AsyncMock(return_value={"id": 1})

    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = good_review

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    mock_github.get.assert_called_once()
    mock_gpt.review.assert_called_once()
    mock_github.post.assert_called_once()


@pytest.mark.asyncio
async def test_review_pr_skips_empty_diff(context):
    mock_github = AsyncMock()
    mock_github.get.return_value = ""
    mock_github.get_json.return_value = {
        "title": "T", "body": "B",
        "head": {"ref": "f"}, "base": {"ref": "m"},
    }
    mock_gpt = AsyncMock()

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    mock_gpt.review.assert_not_called()


@pytest.mark.asyncio
async def test_review_pr_overrides_gpt_decision(context):
    """Even if GPT says approve, server should override based on issues."""
    gpt_result = ReviewResult(
        score=5, summary="Has critical", decision=Decision.APPROVE,
        issues=[Issue(severity="critical", category="security", file="x.py",
                      line=1, description="SQL", suggestion="fix")],
        good_points=[],
    )
    mock_github = AsyncMock()
    mock_github.get.return_value = "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n+hi"
    mock_github.get_json.return_value = {
        "title": "T", "body": "B",
        "head": {"ref": "f"}, "base": {"ref": "m"},
    }
    mock_github.post = AsyncMock(return_value={"id": 1})
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = gpt_result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    call = mock_github.post.call_args
    assert "REQUEST_CHANGES" in str(call)


@pytest.mark.asyncio
async def test_review_pr_uses_config_model(context, good_review):
    mock_github = AsyncMock()
    mock_github.get.return_value = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n+x"
    mock_github.get_json.return_value = {
        "title": "T", "body": "B",
        "head": {"ref": "f"}, "base": {"ref": "m"},
    }
    mock_github.post = AsyncMock(return_value={"id": 1})

    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = good_review

    cfg = ReviewConfig(model="gpt-5-mini")
    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=cfg,
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    assert mock_gpt.review.call_args.kwargs["model"] == "gpt-5-mini"
