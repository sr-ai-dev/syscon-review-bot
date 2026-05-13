import pytest
from pydantic import ValidationError

from src.models.review import (
    Mismatch,
    ReviewResult,
    SpecStatus,
    Decision,
    QualityFinding,
    FindingCategory,
)
from src.models.config import ReviewConfig, IgnoreConfig


class TestMismatch:
    def test_create_with_location(self):
        m = Mismatch(
            file="src/api/auth.py",
            line=42,
            description="로그인 엔드포인트가 스펙에는 POST /auth/login인데 구현은 /login.",
            suggestion="라우트를 /auth/login으로 변경",
        )
        assert m.file == "src/api/auth.py"
        assert m.line == 42

    def test_create_without_location(self):
        m = Mismatch(
            file=None, line=None,
            description="스펙의 비밀번호 정책 검증 누락",
            suggestion="최소 길이/특수문자 검증 추가",
        )
        assert m.file is None and m.line is None


class TestReviewResult:
    def test_present_aligned(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT,
            aligned=True,
            summary="스펙대로 구현됨",
        )
        assert result.spec_status == SpecStatus.PRESENT
        assert result.aligned is True
        assert result.mismatches == []

    def test_present_with_mismatches(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT,
            aligned=False,
            summary="스펙 일부 누락",
            mismatches=[
                Mismatch(file="a.py", line=1, description="d", suggestion="s"),
            ],
        )
        assert len(result.mismatches) == 1

    def test_missing_spec(self):
        result = ReviewResult(
            spec_status=SpecStatus.MISSING,
            aligned=False,
            summary="PR 본문에 스펙·요구사항이 없어 검증 불가",
        )
        assert result.spec_status == SpecStatus.MISSING

    def test_aligned_default_false(self):
        """aligned가 명시 안 됐을 때 안전한 기본값(False)으로."""
        result = ReviewResult(spec_status=SpecStatus.MISSING, summary="x")
        assert result.aligned is False

    def test_architecture_concern_field_accepted(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            architecture_concern="레이어 역참조 의심: A가 B를 직접 import",
        )
        assert "레이어 역참조" in result.architecture_concern

    def test_architecture_concern_defaults_empty(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert result.architecture_concern == ""

    def test_old_fields_removed(self):
        """score, decision, issues, good_points, score_rationale은 더 이상 존재하지 않음."""
        with pytest.raises(ValidationError):
            ReviewResult(
                spec_status=SpecStatus.PRESENT, aligned=True, summary="x",
                score=8,  # 폐기된 필드
            )


class TestQualityFinding:
    def test_create_with_category_and_location(self):
        f = QualityFinding(
            category=FindingCategory.BUG,
            file="src/api/auth.py",
            line=42,
            description="None일 수 있는 user를 검사 없이 역참조",
            suggestion="None 체크 추가",
        )
        assert f.category == FindingCategory.BUG
        assert f.file == "src/api/auth.py"
        assert f.line == 42

    def test_create_without_location(self):
        f = QualityFinding(
            category=FindingCategory.SMELL,
            file=None, line=None,
            description="중복 코드 블록",
            suggestion="공통 함수로 추출",
        )
        assert f.file is None and f.line is None

    def test_category_values(self):
        assert {c.value for c in FindingCategory} == {
            "bug", "vulnerability", "security", "smell", "complexity",
        }

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            QualityFinding(
                category=FindingCategory.BUG,
                description="d", suggestion="s",
                severity="critical",
            )


class TestReviewResultQualityFindings:
    def test_quality_findings_default_empty(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert result.quality_findings == []

    def test_quality_findings_accepted(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[
                QualityFinding(
                    category=FindingCategory.VULNERABILITY,
                    file="src/db.py", line=10,
                    description="문자열 포매팅으로 SQL 구성",
                    suggestion="파라미터 바인딩 사용",
                ),
            ],
        )
        assert len(result.quality_findings) == 1
        assert result.quality_findings[0].category == FindingCategory.VULNERABILITY


class TestDecisionEnum:
    def test_three_values(self):
        # GitHub event 이름과 매칭. APPROVE는 정책상 못 보내지만 결정 라벨로는 유지.
        assert {d.value for d in Decision} == {"approve", "comment", "request_changes"}


class TestReviewConfig:
    def test_default_config(self):
        config = ReviewConfig()
        assert config.model is None
        assert config.ignore.files == []
        assert config.ignore.extensions == []

    def test_model_override(self):
        config = ReviewConfig(model="gpt-5.4-mini")
        assert config.model == "gpt-5.4-mini"

    def test_ignore_config(self):
        config = ReviewConfig(ignore=IgnoreConfig(files=["*.lock"], extensions=[".md"]))
        assert "*.lock" in config.ignore.files

    def test_removed_fields(self):
        """rules, custom_rules, review_language, approve_criteria 모두 제거됨."""
        with pytest.raises(ValidationError):
            ReviewConfig(rules={"security": True})
        with pytest.raises(ValidationError):
            ReviewConfig(custom_rules=["x"])
        with pytest.raises(ValidationError):
            ReviewConfig(review_language="korean")
        with pytest.raises(ValidationError):
            ReviewConfig(approve_criteria={"max_high_issues": 0})
