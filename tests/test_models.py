from src.models.review import Issue, ReviewResult, Decision
from src.models.config import ReviewConfig, RulesConfig, ApprovalCriteria, IgnoreConfig


class TestIssue:
    def test_create_issue(self):
        issue = Issue(
            severity="critical",
            category="security",
            file="src/api/users.py",
            line=42,
            description="SQL injection possible",
            suggestion="Use parameterized query",
        )
        assert issue.severity == "critical"
        assert issue.file == "src/api/users.py"

    def test_issue_file_can_be_null(self):
        issue = Issue(
            severity="warning",
            category="test_coverage",
            file=None,
            line=None,
            description="No tests",
            suggestion="Add tests",
        )
        assert issue.file is None
        assert issue.line is None


class TestReviewResult:
    def test_create_review_result(self):
        result = ReviewResult(
            score=8,
            summary="Overall good",
            decision=Decision.COMMENT,
            issues=[],
            good_points=["Clean architecture"],
        )
        assert result.score == 8
        assert result.decision == Decision.COMMENT

    def test_score_must_be_1_to_10(self):
        from pydantic import ValidationError
        import pytest
        with pytest.raises(ValidationError):
            ReviewResult(score=0, summary="x", decision=Decision.COMMENT)
        with pytest.raises(ValidationError):
            ReviewResult(score=11, summary="x", decision=Decision.COMMENT)


class TestReviewConfig:
    def test_default_config(self):
        config = ReviewConfig()
        assert config.review_language == "korean"
        assert config.rules.code_quality is True
        assert config.approve_criteria.max_high_issues == 0
        assert config.model is None

    def test_custom_rules(self):
        config = ReviewConfig(custom_rules=["No magic numbers"])
        assert "No magic numbers" in config.custom_rules

    def test_model_override(self):
        config = ReviewConfig(model="gpt-5.4-mini")
        assert config.model == "gpt-5.4-mini"
