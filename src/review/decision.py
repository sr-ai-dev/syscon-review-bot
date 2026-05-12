from src.models.review import Issue, Decision
from src.models.config import ApprovalCriteria


def compute_decision(
    score: int,
    issues: list[Issue],
    criteria: ApprovalCriteria,
) -> Decision:
    critical_count = sum(1 for i in issues if i.severity == "critical")
    warning_count = sum(1 for i in issues if i.severity == "warning")

    if score < 7 or critical_count > criteria.max_high_issues:
        return Decision.REQUEST_CHANGES

    if score >= 8 and warning_count <= criteria.max_medium_issues:
        return Decision.APPROVE

    return Decision.COMMENT
