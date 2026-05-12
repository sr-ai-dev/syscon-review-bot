import pytest
from unittest.mock import AsyncMock, patch

from src.review.engine import review_pr, ReviewContext
from src.models.review import Mismatch, ReviewResult, SpecStatus
from src.models.config import ReviewConfig


@pytest.fixture
def context():
    return ReviewContext(repo="owner/repo", pr_number=42)


@pytest.fixture
def aligned_result():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
    )


@pytest.fixture
def missing_spec_result():
    return ReviewResult(
        spec_status=SpecStatus.MISSING, aligned=False,
        summary="PR 본문에 스펙이 없음",
    )


def make_get_json_dispatch(
    pr_info: dict | None = None,
    reviews: list[dict] | None = None,
):
    pr_info = pr_info or {
        "title": "T", "body": "B",
        "head": {"ref": "feat"}, "base": {"ref": "main"},
    }
    reviews = reviews or []

    async def dispatch(path):
        if path.endswith("/reviews"):
            return reviews
        return pr_info

    return dispatch


def _mock_github(diff="diff --git a/a.py b/a.py\n@@ -1 +1 @@\n+x", **dispatch_kwargs):
    m = AsyncMock()
    m.get.return_value = diff
    m.get_json.side_effect = make_get_json_dispatch(**dispatch_kwargs)
    m.post = AsyncMock(return_value={"id": 1})
    return m


@pytest.mark.asyncio
async def test_review_pr_submits_when_present(context, aligned_result):
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = aligned_result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    mock_gpt.review.assert_called_once()
    mock_github.post.assert_called_once()
    payload = mock_github.post.call_args.kwargs["json_data"]
    assert "Approve" in payload["body"]


@pytest.mark.asyncio
async def test_review_pr_request_changes_on_mismatches(context):
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="누락",
        mismatches=[Mismatch(file="x.py", line=1, description="d", suggestion="s")],
    )
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    payload = mock_github.post.call_args.kwargs["json_data"]
    assert "Request Changes" in payload["body"]


@pytest.mark.asyncio
async def test_review_pr_request_changes_on_missing_spec(context, missing_spec_result):
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = missing_spec_result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    payload = mock_github.post.call_args.kwargs["json_data"]
    assert "Request Changes" in payload["body"]
    assert "스펙" in payload["body"]


@pytest.mark.asyncio
async def test_review_pr_skips_empty_diff(context):
    mock_github = _mock_github(diff="")
    mock_gpt = AsyncMock()

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    mock_gpt.review.assert_not_called()


@pytest.mark.asyncio
async def test_review_pr_includes_previous_bot_reviews_in_prompt(context, aligned_result):
    bot_body = "## 🤖 스펙 정합성 리뷰\n이전지적사항"
    human_body = "human reviewer comment"

    mock_github = _mock_github(reviews=[
        {"body": bot_body, "user": {"login": "github-actions[bot]"}},
        {"body": human_body, "user": {"login": "alice"}},
    ])
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = aligned_result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    user_prompt = mock_gpt.review.call_args.args[1]
    assert "이전지적사항" in user_prompt
    assert human_body not in user_prompt


@pytest.mark.asyncio
async def test_review_pr_uses_config_model(context, aligned_result):
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = aligned_result

    cfg = ReviewConfig(model="gpt-5-mini")
    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=cfg,
    ):
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    assert mock_gpt.review.call_args.kwargs["model"] == "gpt-5-mini"


@pytest.mark.asyncio
async def test_review_pr_dry_run_skips_gpt_and_submit(context, capsys):
    mock_github = _mock_github()
    mock_gpt = AsyncMock()

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ):
        await review_pr(
            context=context, github_client=mock_github, gpt_client=mock_gpt,
            dry_run=True,
        )

    mock_gpt.review.assert_not_called()
    mock_github.post.assert_not_called()
    out = capsys.readouterr().out
    assert "SYSTEM PROMPT" in out and "USER PROMPT" in out
    assert "정합성" in out
