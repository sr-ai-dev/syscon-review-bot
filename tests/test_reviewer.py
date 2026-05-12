import pytest
from unittest.mock import AsyncMock

from src.github.reviewer import (
    BOT_REVIEW_MARKER,
    filter_bot_reviews,
    format_review_body,
    submit_review,
)
from src.models.review import ReviewResult, Issue, Decision


class TestFormatReviewBody:
    def test_format_with_issues(self):
        result = ReviewResult(
            score=6, summary="Needs work", decision=Decision.REQUEST_CHANGES,
            issues=[
                Issue(severity="critical", category="security", file="src/api.py",
                      line=10, description="SQL injection", suggestion="Parameterized query"),
                Issue(severity="warning", category="quality", file="src/utils.py",
                      line=5, description="Dup code", suggestion="Extract function"),
            ],
            good_points=["Good naming"],
        )
        body = format_review_body(result)
        assert "점수: 6/10" in body
        assert "필수 수정" in body
        assert "SQL injection" in body
        assert "권고" in body
        assert "Good naming" in body

    def test_format_includes_score_rationale_when_present(self):
        result = ReviewResult(
            score=8, summary="Good", decision=Decision.APPROVE,
            score_rationale="critical 0개, warning 0개, minor 2건이라 8점",
            issues=[], good_points=[],
        )
        body = format_review_body(result)
        assert "critical 0개, warning 0개, minor 2건이라 8점" in body
        assert body.index("critical 0개") < body.index("Good")

    def test_format_omits_score_rationale_when_empty(self):
        result = ReviewResult(
            score=8, summary="Good", decision=Decision.APPROVE,
            score_rationale="",
            issues=[], good_points=[],
        )
        body = format_review_body(result)
        assert "점수 근거" not in body

    def test_format_approve_only(self):
        result = ReviewResult(
            score=9, summary="Great", decision=Decision.APPROVE,
            issues=[], good_points=["Clean"],
        )
        body = format_review_body(result)
        assert "Approve" in body

    def test_format_omits_empty_sections(self):
        result = ReviewResult(
            score=9, summary="Good", decision=Decision.APPROVE,
            issues=[], good_points=["Nice"],
        )
        body = format_review_body(result)
        assert "필수 수정" not in body
        assert "권고" not in body

    def test_format_handles_null_file(self):
        result = ReviewResult(
            score=7, summary="Missing tests", decision=Decision.COMMENT,
            issues=[
                Issue(severity="warning", category="test_coverage",
                      file=None, line=None,
                      description="No tests added", suggestion="Add tests"),
            ],
            good_points=[],
        )
        body = format_review_body(result)
        assert "No tests added" in body
        assert "None" not in body
        assert "null" not in body.lower()

    def test_format_escapes_pipe_in_description(self):
        result = ReviewResult(
            score=8, summary="S", decision=Decision.COMMENT,
            issues=[
                Issue(severity="warning", category="quality", file="x.py", line=1,
                      description="Use `a | b` operator", suggestion="Replace `|`"),
            ],
            good_points=[],
        )
        body = format_review_body(result)
        assert r"a \| b" in body

    def test_format_collapses_newlines_in_cell(self):
        result = ReviewResult(
            score=8, summary="S", decision=Decision.COMMENT,
            issues=[
                Issue(severity="warning", category="quality", file="x.py", line=1,
                      description="Line1\nLine2\nLine3", suggestion="Single line"),
            ],
            good_points=[],
        )
        body = format_review_body(result)
        row = next(line for line in body.split("\n") if "Line1" in line)
        assert "Line2" in row and "Line3" in row


class TestFilterBotReviews:
    def test_keeps_only_bot_marker_reviews(self):
        raw = [
            {"body": f"{BOT_REVIEW_MARKER} — 점수: 7/10\nfoo"},
            {"body": "looks good to me"},
            {"body": f"{BOT_REVIEW_MARKER} — 점수: 8/10\nbar"},
        ]
        result = filter_bot_reviews(raw)
        assert len(result) == 2
        assert all(BOT_REVIEW_MARKER in r["body"] for r in result)

    def test_returns_empty_when_no_bot_reviews(self):
        raw = [
            {"body": "looks good"},
            {"body": "approve"},
        ]
        assert filter_bot_reviews(raw) == []

    def test_handles_missing_body_field(self):
        raw = [
            {"state": "PENDING"},  # no body
            {"body": f"{BOT_REVIEW_MARKER} — 점수: 7/10"},
        ]
        result = filter_bot_reviews(raw)
        assert len(result) == 1

    def test_marker_matches_real_review_output(self):
        """filter must accept the body produced by format_review_body."""
        result = ReviewResult(
            score=7, summary="ok", decision=Decision.COMMENT,
            issues=[], good_points=[],
        )
        body = format_review_body(result)
        assert filter_bot_reviews([{"body": body}]) == [{"body": body}]


class TestSubmitReview:
    @pytest.mark.asyncio
    async def test_always_submits_as_comment_event(self):
        """기본 GITHUB_TOKEN이 APPROVE를 못 보내는 GitHub 정책 때문에,
        실제 결정과 무관하게 API event는 항상 COMMENT로 보낸다.
        봇의 판정은 본문 라벨로만 표시."""
        for decision, label in [
            (Decision.APPROVE, "Approve"),
            (Decision.COMMENT, "Comment"),
            (Decision.REQUEST_CHANGES, "Request Changes"),
        ]:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value={"id": 1})

            result = ReviewResult(
                score=9, summary="ok", decision=decision,
                issues=[], good_points=[],
            )
            await submit_review(mock_client, "owner/repo", 42, result)

            payload = mock_client.post.call_args.kwargs["json_data"]
            assert payload["event"] == "COMMENT", f"{decision}에서 event가 COMMENT 아님"
            assert label in payload["body"], f"본문에 판정 라벨 '{label}' 누락"
