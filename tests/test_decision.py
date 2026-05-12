from src.review.decision import compute_decision
from src.models.review import Issue, Decision
from src.models.config import ApprovalCriteria


def issue(severity: str) -> Issue:
    return Issue(
        severity=severity, category="x", file="x.py", line=1,
        description="d", suggestion="s",
    )


CRIT = ApprovalCriteria(max_high_issues=0, max_medium_issues=3)


class TestComputeDecision:
    def test_perfect_score_approves(self):
        assert compute_decision(10, [], CRIT) == Decision.APPROVE

    def test_high_score_no_issues_approves(self):
        assert compute_decision(9, [], CRIT) == Decision.APPROVE

    def test_high_score_with_critical_request_changes(self):
        assert compute_decision(9, [issue("critical")], CRIT) == Decision.REQUEST_CHANGES

    def test_low_score_request_changes(self):
        assert compute_decision(6, [], CRIT) == Decision.REQUEST_CHANGES

    def test_score_8_no_warnings_approves(self):
        """Real case (PR 634): score 8 + only minor issues should approve."""
        assert compute_decision(8, [issue("minor")], CRIT) == Decision.APPROVE

    def test_score_8_with_warnings_within_threshold_approves(self):
        assert compute_decision(8, [issue("warning")], CRIT) == Decision.APPROVE

    def test_score_7_comments(self):
        """Score 7 is still below APPROVE bar (8)."""
        assert compute_decision(7, [], CRIT) == Decision.COMMENT

    def test_mid_score_with_critical_request_changes(self):
        assert compute_decision(8, [issue("critical")], CRIT) == Decision.REQUEST_CHANGES

    def test_score_8_too_many_warnings_comments(self):
        issues = [issue("warning") for _ in range(5)]
        assert compute_decision(8, issues, CRIT) == Decision.COMMENT

    def test_too_many_warnings_drops_to_comment(self):
        issues = [issue("warning") for _ in range(5)]
        assert compute_decision(9, issues, CRIT) == Decision.COMMENT

    def test_minor_issues_dont_block_approve(self):
        issues = [issue("minor") for _ in range(20)]
        assert compute_decision(9, issues, CRIT) == Decision.APPROVE

    def test_warning_at_threshold_approves(self):
        issues = [issue("warning") for _ in range(3)]
        assert compute_decision(9, issues, CRIT) == Decision.APPROVE

    def test_max_high_one_allows_one_critical(self):
        criteria = ApprovalCriteria(max_high_issues=1, max_medium_issues=3)
        assert compute_decision(9, [issue("critical")], criteria) == Decision.APPROVE
