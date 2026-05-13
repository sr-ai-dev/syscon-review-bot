from src.review.decision import compute_decision
from src.models.review import ReviewResult, SpecStatus, Mismatch, Decision, QualityFinding, FindingCategory


def _mismatch():
    return Mismatch(file="x", line=1, description="d", suggestion="s")


def _finding(category):
    return QualityFinding(
        category=category, file="x.py", line=1, description="d", suggestion="s",
    )


class TestComputeDecision:
    def test_missing_spec_requests_changes(self):
        result = ReviewResult(
            spec_status=SpecStatus.MISSING, aligned=False, summary="no spec",
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES

    def test_present_with_mismatches_requests_changes(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=False, summary="some mismatch",
            mismatches=[_mismatch()],
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES

    def test_present_and_aligned_approves(self):
        """결정 라벨로는 APPROVE. 실제 GitHub 제출은 reviewer가 COMMENT로 보냄."""
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="all good",
        )
        assert compute_decision(result) == Decision.APPROVE

    def test_architecture_concern_triggers_request_changes(self):
        """스펙 부합해도 아키텍처 우려가 있으면 REQUEST_CHANGES."""
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            architecture_concern="레이어 역참조 의심",
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES

    def test_empty_architecture_concern_does_not_block(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            architecture_concern="",
        )
        assert compute_decision(result) == Decision.APPROVE


class TestComputeDecisionQualityFindings:
    def test_bug_finding_requests_changes(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[_finding(FindingCategory.BUG)],
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES

    def test_vulnerability_finding_requests_changes(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[_finding(FindingCategory.VULNERABILITY)],
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES

    def test_smell_only_downgrades_to_comment(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[_finding(FindingCategory.SMELL)],
        )
        assert compute_decision(result) == Decision.COMMENT

    def test_security_and_complexity_only_is_comment(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[
                _finding(FindingCategory.SECURITY),
                _finding(FindingCategory.COMPLEXITY),
            ],
        )
        assert compute_decision(result) == Decision.COMMENT

    def test_no_findings_keeps_approve(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert compute_decision(result) == Decision.APPROVE

    def test_spec_missing_still_request_changes_despite_smell(self):
        result = ReviewResult(
            spec_status=SpecStatus.MISSING, aligned=False, summary="no spec",
            quality_findings=[_finding(FindingCategory.SMELL)],
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES
