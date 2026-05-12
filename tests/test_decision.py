from src.review.decision import compute_decision
from src.models.review import ReviewResult, SpecStatus, Mismatch, Decision


def _mismatch():
    return Mismatch(file="x", line=1, description="d", suggestion="s")


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
