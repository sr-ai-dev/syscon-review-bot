import pytest
from unittest.mock import AsyncMock, patch

import httpx

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
    issue_comments: list[dict] | None = None,
    review_comments: list[dict] | None = None,
):
    pr_info = pr_info or {
        "title": "T", "body": "B",
        "head": {"ref": "feat", "sha": "deadbeef"}, "base": {"ref": "main"},
    }
    reviews = reviews or []
    issue_comments = issue_comments or []
    review_comments = review_comments or []

    async def dispatch(path):
        if "/issues/" in path and path.endswith("/comments"):
            return issue_comments
        if "/pulls/" in path and path.endswith("/comments"):
            return review_comments
        if path.endswith("/reviews"):
            return reviews
        return pr_info

    return dispatch


def _mock_github(diff="diff --git a/a.py b/a.py\n@@ -1 +1 @@\n+x", **dispatch_kwargs):
    m = AsyncMock()
    m.get.return_value = diff
    m.get_json.side_effect = make_get_json_dispatch(**dispatch_kwargs)
    m.get_json_list = AsyncMock(return_value=[])
    m.post = AsyncMock(return_value={"id": 1})
    return m


_NO_EXPAND = patch("src.review.engine.get_repo_file", new_callable=AsyncMock, return_value=None)


@pytest.mark.asyncio
async def test_review_pr_submits_when_present(context, aligned_result):
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = aligned_result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(enable_judge=False),
    ), _NO_EXPAND:
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
    ), _NO_EXPAND:
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
    ), _NO_EXPAND:
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
    ), _NO_EXPAND:
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    mock_gpt.review.assert_not_called()


@pytest.mark.asyncio
async def test_review_pr_passes_unified_conversation_history(context, aligned_result):
    bot_login = "github-actions[bot]"
    reviews = [
        {
            "body": "## 🤖 스펙 정합성 리뷰\nFIRST_BOT_BODY",
            "user": {"login": bot_login},
            "submitted_at": "2026-05-13T06:50:00Z",
            "commit_id": "abcdef0123456789",
        },
        {
            "body": "## 🤖 스펙 정합성 리뷰\nSECOND_BOT_BODY",
            "user": {"login": bot_login},
            "submitted_at": "2026-05-13T07:10:00Z",
            "commit_id": "fedcba9876543210",
        },
    ]
    issue_comments = [
        {
            "body": "HUMAN_ISSUE_REPLY",
            "user": {"login": "alice"},
            "created_at": "2026-05-13T06:55:00Z",
        },
    ]
    review_comments = [
        {
            "body": "HUMAN_LINE_REPLY",
            "user": {"login": "bob"},
            "path": "src/y.py",
            "line": 20,
            "created_at": "2026-05-13T07:00:00Z",
        },
    ]
    captured = {}

    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(
        reviews=reviews,
        issue_comments=issue_comments,
        review_comments=review_comments,
    )
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=False)), _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    user_prompt = captured["user"]
    # 통합 섹션 헤더
    assert "이전 리뷰 & 대화 히스토리" in user_prompt
    # 봇 본문 전체 포함
    assert "FIRST_BOT_BODY" in user_prompt
    assert "SECOND_BOT_BODY" in user_prompt
    # 사람 코멘트 본문 포함
    assert "HUMAN_ISSUE_REPLY" in user_prompt
    assert "HUMAN_LINE_REPLY" in user_prompt
    # 라인 위치
    assert "src/y.py:20" in user_prompt
    # 시간순: FIRST_BOT(06:50) < HUMAN_ISSUE(06:55) < HUMAN_LINE(07:00) < SECOND_BOT(07:10)
    pos_first = user_prompt.index("FIRST_BOT_BODY")
    pos_issue = user_prompt.index("HUMAN_ISSUE_REPLY")
    pos_line = user_prompt.index("HUMAN_LINE_REPLY")
    pos_second = user_prompt.index("SECOND_BOT_BODY")
    assert pos_first < pos_issue < pos_line < pos_second


@pytest.mark.asyncio
async def test_review_pr_excludes_bot_self_in_issue_comments(context, aligned_result):
    bot_login = "github-actions[bot]"
    reviews = [
        {
            "body": "## 🤖 스펙 정합성 리뷰\nbot review",
            "user": {"login": bot_login},
            "submitted_at": "2026-05-13T06:50:00Z",
            "commit_id": "abcdef01",
        }
    ]
    issue_comments = [
        {
            "body": "BOT_SELF_ISSUE_COMMENT",
            "user": {"login": bot_login},
            "created_at": "2026-05-13T06:55:00Z",
        }
    ]
    captured = {}

    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(
        reviews=reviews,
        issue_comments=issue_comments,
        review_comments=[],
    )
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig()), _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    assert "BOT_SELF_ISSUE_COMMENT" not in captured["user"]


@pytest.mark.asyncio
async def test_review_pr_uses_config_model(context, aligned_result):
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = aligned_result

    cfg = ReviewConfig(model="gpt-5-mini")
    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=cfg,
    ), _NO_EXPAND:
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    assert mock_gpt.review.call_args.kwargs["model"] == "gpt-5-mini"


@pytest.mark.asyncio
async def test_review_pr_dry_run_skips_gpt_and_submit(context, capsys):
    mock_github = _mock_github()
    mock_gpt = AsyncMock()

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ), _NO_EXPAND:
        await review_pr(
            context=context, github_client=mock_github, gpt_client=mock_gpt,
            dry_run=True,
        )

    mock_gpt.review.assert_not_called()
    mock_github.post.assert_not_called()
    out = capsys.readouterr().out
    assert "SYSTEM PROMPT" in out and "USER PROMPT" in out
    assert "정합성" in out


@pytest.mark.asyncio
async def test_review_pr_includes_all_comments_regardless_of_timing(context, aligned_result):
    """Whole-thread mode: comments before bot reviews are kept too."""
    bot_login = "github-actions[bot]"
    reviews = [
        {
            "body": "## 🤖 스펙 정합성 리뷰\nlate bot review",
            "user": {"login": bot_login},
            "submitted_at": "2026-05-13T10:00:00Z",
            "commit_id": "feedface12345678",
        }
    ]
    issue_comments = [
        {
            "body": "오래된 토론",
            "user": {"login": "alice"},
            "created_at": "2026-05-13T09:00:00Z",
        },
    ]
    captured = {}

    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(
        reviews=reviews,
        issue_comments=issue_comments,
        review_comments=[],
    )
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=False)), _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    user_prompt = captured["user"]
    # No "after last bot review" filter — all comments included
    assert "오래된 토론" in user_prompt
    assert "late bot review" in user_prompt


@pytest.mark.asyncio
async def test_review_pr_renders_prior_resolved_in_body(context):
    result_with_resolved = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True, summary="해결 완료",
        prior_resolved=["이전 지적 A → 해결됨"],
    )
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = result_with_resolved

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock, return_value=ReviewConfig(),
    ), _NO_EXPAND:
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    payload = mock_github.post.call_args.kwargs["json_data"]
    assert "이전 리뷰 상태" in payload["body"]
    assert "이전 지적 A" in payload["body"]


@pytest.mark.asyncio
async def test_review_pr_expands_hunks_using_head_file_content(context, aligned_result):
    """엔진이 변경 파일을 head SHA로 fetch해서 hunk 확장 후 LLM에 전달."""
    full_source = "\n".join([
        "x = 1",
        "def helper():",
        "    return 1",
        "def main():",
        "    y = helper()",
        "    return y + 1",
    ])
    diff = (
        "diff --git a/a.py b/a.py\n"
        "@@ -6,1 +6,1 @@\n"
        "-    return y\n"
        "+    return y + 1\n"
    )

    captured = {}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(diff=diff)
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=False)), \
         patch("src.review.engine.get_repo_file", new_callable=AsyncMock, return_value=full_source):
        await review_pr(context, mock_github, mock_gpt)

    assert "def main()" in captured["user"]
    assert "y = helper()" in captured["user"]


@pytest.mark.asyncio
async def test_review_pr_drops_oversized_files_and_notes_skipped(context, aligned_result):
    huge = "a" * 250000
    diff = (
        "diff --git a/huge.py b/huge.py\n"
        f"@@ -1,1 +1,1 @@\n+{huge}\n"
        "diff --git a/small.py b/small.py\n"
        "@@ -1,1 +1,1 @@\n+ok\n"
    )
    captured = {}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        captured["user"] = user
        return aligned_result
    mock_github = _mock_github(diff=diff)
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review
    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(token_budget=5000, enable_judge=False)), _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)
    assert "small.py" in captured["user"]
    assert ("a" * 1000) not in captured["user"]
    assert "토큰 예산" in captured["user"] or "huge.py" in captured["user"]


@pytest.mark.asyncio
async def test_review_pr_runs_judge_when_enabled(context):
    first = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="원본",
        prior_resolved=["X → 일부"], architecture_concern="X 잔존",
    )
    judged = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="judged",
        prior_resolved=["(부분) X → 일부, 잔존은 아키텍처 참조"],
        architecture_concern="X 잔존",
    )
    call_count = {"n": 0}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        call_count["n"] += 1
        return first if call_count["n"] == 1 else judged

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=True)), \
         _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    assert call_count["n"] == 2
    body = mock_github.post.call_args.kwargs["json_data"]["body"]
    assert "(부분)" in body or "🔶" in body


@pytest.mark.asyncio
async def test_review_pr_skips_judge_when_disabled(context, aligned_result):
    call_count = {"n": 0}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        call_count["n"] += 1
        return aligned_result

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=False)), \
         _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_review_pr_creates_tool_executor_when_enabled(context, aligned_result):
    captured = {}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        captured["tool_executor"] = tool_executor
        captured["max_tool_iterations"] = max_tool_iterations
        return aligned_result

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_tool_use=True, max_tool_iterations=5)), \
         _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    assert captured["tool_executor"] is not None
    assert hasattr(captured["tool_executor"], "read_file")
    assert hasattr(captured["tool_executor"], "grep")
    assert captured["max_tool_iterations"] == 5


@pytest.mark.asyncio
async def test_review_pr_omits_tool_executor_when_disabled(context, aligned_result):
    captured = {}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8, reasoning_effort="high"):
        captured["tool_executor"] = tool_executor
        return aligned_result

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_tool_use=False)), \
         _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    assert captured["tool_executor"] is None


@pytest.mark.asyncio
async def test_load_repo_config_falls_back_to_default_on_non_404_error():
    from src.review.engine import load_repo_config
    from src.review.config_loader import DEFAULT_CONFIG
    mock_gh = AsyncMock()
    # 5xx 시뮬레이션
    mock_gh.get_json = AsyncMock(side_effect=RuntimeError("simulated 500"))
    cfg = await load_repo_config(mock_gh, "owner/repo", "deadbeef")
    assert cfg is DEFAULT_CONFIG


@pytest.mark.asyncio
async def test_review_pr_applies_postprocess_filter(context):
    """엔진이 LLM 응답에 postprocess를 적용해 저신뢰 finding을 제거."""
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="혼합",
        mismatches=[
            Mismatch(file="a.py", line=1, description="확실 finding", suggestion="s", confidence=85),
            Mismatch(file="b.py", line=2, description="약함 finding", suggestion="s", confidence=40),
        ],
    )
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock,
        return_value=ReviewConfig(enable_judge=False, enable_tool_use=False, confidence_threshold=70),
    ), _NO_EXPAND:
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    body = mock_github.post.call_args.kwargs["json_data"]["body"]
    assert "확실 finding" in body
    assert "약함 finding" not in body


@pytest.mark.asyncio
async def test_expand_files_swallows_non_404_errors(context, aligned_result):
    """If get_repo_file raises (e.g., 500), engine still proceeds with original FileDiff."""
    diff = (
        "diff --git a/a.py b/a.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n+new\n"
    )
    mock_github = _mock_github(diff=diff)
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = aligned_result

    async def raise_500(*args, **kwargs):
        raise RuntimeError("simulated 500")

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=False)), \
         patch("src.review.engine.get_repo_file", side_effect=raise_500):
        await review_pr(context, mock_github, mock_gpt)

    # GPT 호출이 발생했음을 확인 (= 엔진이 크래시하지 않음)
    mock_gpt.review.assert_called_once()


@pytest.mark.asyncio
async def test_review_pr_falls_back_to_files_api_on_406(context, aligned_result):
    """get_pr_diff 406 → get_pr_files fallback으로 리뷰 계속 진행."""

    async def raise_406(*args, **kwargs):
        request = httpx.Request("GET", "https://api.github.com/repos/owner/repo/pulls/42")
        response = httpx.Response(406, request=request)
        raise httpx.HTTPStatusError("406 Not Acceptable", request=request, response=response)

    pr_files = [
        {"filename": "a.py", "patch": "@@ -1 +1 @@\n+new_code", "additions": 1, "deletions": 0, "status": "modified"},
    ]

    mock_github = _mock_github()
    mock_github.get.side_effect = raise_406
    mock_github.get_json_list.return_value = pr_files

    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = aligned_result

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=False)), _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    mock_github.get_json_list.assert_called_once()
    mock_gpt.review.assert_called_once()


@pytest.mark.asyncio
async def test_review_pr_reraises_non_406_http_error(context):
    """get_pr_diff 500 등 비-406 에러는 fallback 없이 그대로 raise."""

    async def raise_500(*args, **kwargs):
        request = httpx.Request("GET", "https://api.github.com/repos/owner/repo/pulls/42")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("500 Server Error", request=request, response=response)

    mock_github = _mock_github()
    mock_github.get.side_effect = raise_500
    mock_gpt = AsyncMock()

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig()), _NO_EXPAND:
        with pytest.raises(httpx.HTTPStatusError, match="500"):
            await review_pr(context, mock_github, mock_gpt)
