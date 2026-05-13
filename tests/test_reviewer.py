import pytest
from unittest.mock import AsyncMock

from src.github.reviewer import (
    BOT_REVIEW_MARKER,
    filter_bot_reviews,
    format_review_body,
    submit_review,
)
from src.models.review import (
    Decision,
    FindingCategory,
    Mismatch,
    QualityFinding,
    ReviewResult,
    SpecStatus,
)


def _result_missing():
    return ReviewResult(
        spec_status=SpecStatus.MISSING, aligned=False,
        summary="PR 본문에 스펙·요구사항이 없어 검증 불가",
    )


def _result_aligned():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True,
        summary="모든 요구사항이 코드에 반영됨",
    )


def _result_mismatched():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False,
        summary="스펙 일부 누락",
        mismatches=[
            Mismatch(file="src/auth.py", line=10, description="로그아웃 엔드포인트 누락", suggestion="POST /auth/logout 추가"),
            Mismatch(file=None, line=None, description="비밀번호 정책 검증 누락", suggestion="최소 길이 검증 추가"),
        ],
    )


class TestFormatReviewBody:
    def test_marker_at_top(self):
        body = format_review_body(_result_aligned())
        assert body.startswith(BOT_REVIEW_MARKER)

    def test_aligned_shows_approve_verdict(self):
        body = format_review_body(_result_aligned())
        assert "스펙 부합" in body or "Approve" in body
        assert "❌" not in body

    def test_mismatched_lists_each_with_location(self):
        body = format_review_body(_result_mismatched())
        assert "로그아웃 엔드포인트 누락" in body
        assert "src/auth.py:10" in body
        assert "비밀번호 정책 검증 누락" in body
        assert "Request Changes" in body

    def test_missing_spec_explains_requirement(self):
        body = format_review_body(_result_missing())
        assert "스펙" in body or "요구사항" in body
        assert "Request Changes" in body
        # 스펙 없을 때 mismatch 섹션은 표시 안 함
        assert "src/" not in body

    def test_renders_architecture_concern_when_present(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True,
            summary="스펙 부합",
            architecture_concern="A 모듈이 B를 역참조하는 의심 코드 있음",
        )
        body = format_review_body(result)
        assert "아키텍처" in body
        assert "A 모듈이 B를 역참조" in body
        assert "Request Changes" in body

    def test_architecture_section_always_shown(self):
        """검수 사실 노출용. 우려 없어도 '이상 없음' 표시."""
        body = format_review_body(_result_aligned())
        assert "아키텍처" in body
        assert "이상 없음" in body

    def test_no_score_no_severity_tiers(self):
        for r in (_result_aligned(), _result_mismatched(), _result_missing()):
            body = format_review_body(r)
            for dead in ("점수", "score", "🔴", "🟡", "🔵", "critical", "warning", "minor"):
                assert dead not in body, f"폐기된 표기 '{dead}'가 본문에 남아있음"

    def test_pipe_escaped_in_mismatch_description(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=False, summary="s",
            mismatches=[
                Mismatch(file="x.py", line=1, description="Use `a | b`", suggestion="Replace `|`"),
            ],
        )
        body = format_review_body(result)
        assert r"a \| b" in body

    def test_newlines_in_description_collapsed(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=False, summary="s",
            mismatches=[
                Mismatch(file="x.py", line=1, description="Line1\nLine2", suggestion="Single"),
            ],
        )
        body = format_review_body(result)
        row = next(line for line in body.split("\n") if "Line1" in line)
        assert "Line2" in row


def _result_with_quality_findings():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True,
        summary="스펙 부합하나 코드 품질 이슈 있음",
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="src/svc.py", line=12,
                description="None 가능 값을 검사 없이 사용", suggestion="None 체크 추가",
            ),
            QualityFinding(
                category=FindingCategory.SMELL, file=None, line=None,
                description="중복 코드 블록", suggestion="공통 함수 추출",
            ),
        ],
    )


class TestFormatReviewBodyQuality:
    def test_quality_section_lists_findings(self):
        body = format_review_body(_result_with_quality_findings())
        assert "코드 품질" in body
        assert "None 가능 값을 검사 없이 사용" in body
        assert "src/svc.py:12" in body
        assert "중복 코드 블록" in body
        assert "버그" in body
        assert "코드 스멜" in body
        assert "Request Changes" in body

    def test_quality_section_shows_ok_when_empty(self):
        body = format_review_body(_result_aligned())
        assert "코드 품질" in body
        assert body.count("이상 없음") >= 2

    def test_quality_pipe_escaped(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="s",
            quality_findings=[
                QualityFinding(
                    category=FindingCategory.SMELL, file="x.py", line=1,
                    description="Use `a | b`", suggestion="Replace `|`",
                ),
            ],
        )
        body = format_review_body(result)
        assert r"a \| b" in body


class TestFilterBotReviews:
    def test_keeps_only_marker(self):
        raw = [
            {"body": f"{BOT_REVIEW_MARKER}\nfoo"},
            {"body": "looks good"},
            {"body": f"{BOT_REVIEW_MARKER}\nbar"},
        ]
        assert len(filter_bot_reviews(raw)) == 2

    def test_filter_matches_real_body(self):
        body = format_review_body(_result_aligned())
        assert filter_bot_reviews([{"body": body}]) == [{"body": body}]


class TestSubmitReview:
    @pytest.mark.asyncio
    async def test_always_comment_event(self):
        """GITHUB_TOKEN의 APPROVE 정책 회피: 결정 무관 항상 COMMENT 이벤트."""
        for result, label in [
            (_result_aligned(), "Approve"),
            (_result_mismatched(), "Request Changes"),
            (_result_missing(), "Request Changes"),
        ]:
            client = AsyncMock()
            client.post = AsyncMock(return_value={"id": 1})
            await submit_review(client, "owner/repo", 1, result)
            payload = client.post.call_args.kwargs["json_data"]
            assert payload["event"] == "COMMENT"
            assert label in payload["body"]
