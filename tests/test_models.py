import pytest
from pydantic import ValidationError

from src.models.review import (
    AdvisoryFinding,
    ArchitectureFinding,
    Mismatch,
    ReviewResult,
    SpecDocFinding,
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

    def test_architecture_findings_field_accepted(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            architecture_findings=[
                ArchitectureFinding(
                    file="a.py", line=1,
                    description="레이어 역참조 의심: A가 B를 직접 import",
                    suggestion="의존 방향을 정리",
                    confidence=85,
                ),
            ],
        )
        assert "레이어 역참조" in result.architecture_findings[0].description

    def test_architecture_findings_default_empty(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert result.architecture_findings == []
        assert result.spec_doc_findings == []

    def test_spec_doc_findings_field_accepted(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            spec_doc_findings=[
                SpecDocFinding(
                    file="spec/login/requirements.md", line=12,
                    description="수용 기준이 성공 조건만 적고 실패 조건을 정의하지 않음",
                    suggestion="실패 조건과 경계 케이스를 수용 기준에 추가",
                    confidence=82,
                ),
            ],
        )
        assert len(result.spec_doc_findings) == 1
        assert "수용 기준" in result.spec_doc_findings[0].description

    def test_advisory_findings_default_empty(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert result.advisory_findings == []

    def test_advisory_finding_is_accepted(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT,
            aligned=True,
            summary="정상 workflow는 통과하고 추가 hardening만 제안함",
            advisory_findings=[
                AdvisoryFinding(
                    file="src/state.py",
                    line=42,
                    description="인위적으로 손상된 history에 대한 방어 제안",
                    suggestion="별도 hardening PR에서 검토",
                    confidence=88,
                ),
            ],
        )
        assert len(result.advisory_findings) == 1
        assert result.advisory_findings[0].confidence == 88


class TestAdvisoryFinding:
    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            AdvisoryFinding(
                description="d",
                suggestion="s",
                blocking=False,
            )


class TestArchitectureFinding:
    def test_create_with_location_and_confidence(self):
        f = ArchitectureFinding(
            file="src/api.py", line=12,
            description="Controller가 repository를 직접 참조",
            suggestion="service 계층을 통해 접근",
            confidence=88,
        )
        assert f.file == "src/api.py"
        assert f.confidence == 88

    def test_confidence_defaults_to_80(self):
        f = ArchitectureFinding(description="d", suggestion="s")
        assert f.confidence == 80

    def test_confidence_must_be_in_range(self):
        with pytest.raises(ValidationError):
            ArchitectureFinding(description="d", suggestion="s", confidence=101)

    def test_old_fields_removed(self):
        """score, decision, issues, good_points, score_rationale은 더 이상 존재하지 않음."""
        with pytest.raises(ValidationError):
            ReviewResult(
                spec_status=SpecStatus.PRESENT, aligned=True, summary="x",
                score=8,  # 폐기된 필드
            )


class TestSpecDocFinding:
    def test_create_with_location_and_confidence(self):
        f = SpecDocFinding(
            file="spec/login/design.md", line=8,
            description="requirements의 API 경로와 design의 API 경로가 다름",
            suggestion="두 문서의 API 경로를 하나로 통일",
            confidence=90,
        )
        assert f.file == "spec/login/design.md"
        assert f.confidence == 90

    def test_confidence_defaults_to_70(self):
        f = SpecDocFinding(description="d", suggestion="s")
        assert f.confidence == 70

    def test_confidence_must_be_in_range(self):
        with pytest.raises(ValidationError):
            SpecDocFinding(description="d", suggestion="s", confidence=-1)


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


class TestPriorResolved:
    def test_prior_resolved_default_empty(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert result.prior_resolved == []

    def test_prior_resolved_accepted(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            prior_resolved=[
                "필드 초기값 direction 기반 기본값과 불일치 → 생성자에서 direction 분기 추가하여 해결",
                "getWaypointNode 방향 의존 → 방향 파라미터 제거하여 해결",
            ],
        )
        assert len(result.prior_resolved) == 2
        assert "해결" in result.prior_resolved[0]


def test_mismatch_requires_confidence_field():
    m = Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=85)
    assert m.confidence == 85

def test_mismatch_confidence_must_be_in_range():
    with pytest.raises(ValidationError):
        Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=150)
    with pytest.raises(ValidationError):
        Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=-5)

def test_quality_finding_confidence_field():
    q = QualityFinding(
        category=FindingCategory.BUG, file="a.py", line=1,
        description="d", suggestion="s", confidence=75,
    )
    assert q.confidence == 75

def test_mismatch_confidence_defaults_to_70():
    m = Mismatch(file="a.py", line=1, description="d", suggestion="s")
    assert m.confidence == 70


class TestDecisionEnum:
    def test_two_values(self):
        # GitHub event 이름과 매칭. APPROVE는 정책상 못 보내지만 결정 라벨로는 유지.
        assert {d.value for d in Decision} == {"approve", "request_changes"}


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
