import pytest
from unittest.mock import AsyncMock

from src.github.reviewer import (
    BOT_REVIEW_MARKER,
    filter_bot_reviews,
    format_review_body,
    submit_review,
)
from src.models.review import (
    ArchitectureFinding,
    Decision,
    FindingCategory,
    Mismatch,
    QualityFinding,
    ReviewResult,
    SpecDocFinding,
    SpecStatus,
)


def _result_missing():
    return ReviewResult(
        spec_status=SpecStatus.MISSING, aligned=False,
        summary="스펙·요구사항을 식별하지 못해 코드 자체를 검토함",
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


def _result_with_spec_doc_findings():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True,
        summary="스펙 문서 보완 필요",
        spec_doc_findings=[
            SpecDocFinding(
                file="spec/login/requirements.md", line=7,
                description="수용 기준이 성공 케이스만 있고 실패 조건을 정의하지 않음",
                suggestion="실패 조건과 경계 케이스를 수용 기준에 추가",
                confidence=84,
            ),
        ],
    )


class TestFormatReviewBody:
    def test_marker_at_top(self):
        body = format_review_body(_result_aligned())
        assert body.startswith(BOT_REVIEW_MARKER)

    def test_aligned_shows_approve_verdict(self):
        body = format_review_body(_result_aligned())
        assert "Approved" in body
        assert "❌" not in body

    def test_mismatched_lists_each_with_location(self):
        body = format_review_body(_result_mismatched())
        assert "스펙 문서 검토" in body
        assert "로그아웃 엔드포인트 누락" in body
        assert "위치: `src/auth.py:10`" in body
        assert "| # | 항목 | 제안 |" in body
        assert "| # | 항목 | conf | 제안 |" not in body
        assert "비밀번호 정책 검증 누락" in body
        assert "수정 필요" in body

    def test_missing_spec_explains_limited_alignment_review(self):
        body = format_review_body(_result_missing())
        assert "스펙" in body or "요구사항" in body
        assert "정합성 검토와 스펙 문서 검토는 생략" in body
        assert "Approved" in body
        assert "수정 필요" not in body
        assert "### 스펙 문서 검토" not in body
        # 스펙 없을 때 mismatch 섹션은 표시 안 함
        assert "src/" not in body

    def test_spec_doc_findings_render_first_section(self):
        body = format_review_body(_result_with_spec_doc_findings())
        assert "수용 기준이 성공 케이스만" in body
        assert "위치: `spec/login/requirements.md:7`" in body
        assert "신뢰도: 84" in body
        assert "수정 필요" in body
        spec_doc_pos = body.index("### 스펙 문서 검토")
        arch_pos = body.index("### 아키텍처 검토")
        quality_pos = body.index("### 코드 품질 검사")
        assert spec_doc_pos < arch_pos < quality_pos

    def test_spec_doc_section_precedes_prior_resolved(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="s",
            prior_resolved=["이전 문서 지적 → 해결"],
            spec_doc_findings=[
                SpecDocFinding(description="requirements와 tasks 범위가 다름", suggestion="범위 통일"),
            ],
        )
        body = format_review_body(result)
        assert body.index("### 스펙 문서 검토") < body.index("### 이전 리뷰 상태")

    def test_renders_architecture_findings_when_present(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True,
            summary="스펙 부합",
            architecture_findings=[
                ArchitectureFinding(
                    file="src/a.py", line=20,
                    description="A 모듈이 B를 역참조하는 의심 코드 있음",
                    suggestion="의존 방향을 단방향으로 정리",
                    confidence=85,
                ),
            ],
        )
        body = format_review_body(result)
        assert "아키텍처" in body
        assert "A 모듈이 B를 역참조" in body
        assert "| # | 항목 | 제안 |" in body
        assert "위치: `src/a.py:20`" in body
        assert "신뢰도: 85" in body
        assert "수정 필요" in body

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


def _result_with_prior_resolved():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False,
        summary="이전 3건 중 2건 해결, 1건 미해결 + 신규 1건",
        prior_resolved=[
            "필드 초기값 direction 기반 기본값과 불일치 → 생성자에서 direction 분기 추가하여 해결",
            "getWaypointNode 방향 의존 → 작성자 설명 수용 (의도된 설계)",
        ],
        mismatches=[
            Mismatch(file="src/a.py", line=10, description="미해결 이슈", suggestion="수정 필요"),
        ],
    )


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
        assert "위치: `src/svc.py:12`" in body
        assert "| # | 분류 | 항목 | 제안 |" in body
        assert "| # | 분류 | 항목 | conf | 제안 |" not in body
        assert "중복 코드 블록" in body
        assert "버그" in body
        assert "코드 스멜" in body
        assert "수정 필요" in body

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


class TestFormatReviewBodyPriorResolved:
    def test_prior_resolved_section_rendered(self):
        body = format_review_body(_result_with_prior_resolved())
        assert "이전 리뷰 상태" in body
        assert "필드 초기값" in body
        assert "getWaypointNode" in body

    def test_prior_resolved_not_shown_when_empty(self):
        body = format_review_body(_result_aligned())
        assert "이전 리뷰 상태" not in body

    def test_full_resolved_item_uses_check_prefix(self):
        body = format_review_body(_result_with_prior_resolved())
        line = next(l for l in body.split("\n") if "필드 초기값" in l)
        assert "✅ 완전 해결:" in line
        assert "~~" not in line

    def test_partial_resolved_item_no_strikethrough(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=False, summary="s",
            prior_resolved=["(부분) 그룹 패널 책임 집중 → 일부 helper 분리됨"],
            mismatches=[
                Mismatch(file="x.py", line=1, description="남은 문제", suggestion="s"),
            ],
        )
        body = format_review_body(result)
        line = next(l for l in body.split("\n") if "그룹 패널" in l)
        assert "~~" not in line
        # 부분 표식이 사용자에게 보여야 함
        assert "부분" in line

    def test_count_distinguishes_full_and_partial(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=False, summary="s",
            prior_resolved=[
                "완전 해결 A → 해결됨",
                "(부분) 부분 해결 B → 일부만",
                "완전 해결 C → 해결됨",
            ],
            mismatches=[Mismatch(file="x.py", line=1, description="남은 문제", suggestion="s")],
        )
        body = format_review_body(result)
        # 완전 2건 + 부분 1건이 헤더에 노출되어야 함
        assert "완전 해결 2건" in body or "2건 해결" in body
        assert "부분 해결 1건" in body or "1건 부분" in body


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


def test_mismatch_renders_confidence_inside_item():
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="s",
        mismatches=[
            Mismatch(file="a.py", line=10, description="d", suggestion="s", confidence=85),
        ],
    )
    body = format_review_body(result)
    row = next(line for line in body.split("\n") if "d<br>" in line)
    assert "신뢰도: 85" in row


def test_quality_finding_renders_confidence_inside_item():
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True, summary="s",
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="x.py", line=1,
                description="d", suggestion="s", confidence=72,
            ),
        ],
    )
    body = format_review_body(result)
    row = next(line for line in body.split("\n") if "d<br>" in line)
    assert "신뢰도: 72" in row


class TestSubmitReview:
    @pytest.mark.asyncio
    async def test_always_comment_event(self):
        """GITHUB_TOKEN의 APPROVE 정책 회피: 결정 무관 항상 COMMENT 이벤트."""
        for result, label in [
            (_result_aligned(), "Approved"),
            (_result_mismatched(), "수정 필요"),
            (_result_missing(), "Approved"),
        ]:
            client = AsyncMock()
            client.post = AsyncMock(return_value={"id": 1})
            await submit_review(client, "owner/repo", 1, result)
            payload = client.post.call_args.kwargs["json_data"]
            assert payload["event"] == "COMMENT"
            assert label in payload["body"]
