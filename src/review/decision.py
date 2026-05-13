from src.models.review import Decision, FindingCategory, ReviewResult, SpecStatus


_BLOCKING_CATEGORIES = {FindingCategory.BUG, FindingCategory.VULNERABILITY}


def compute_decision(result: ReviewResult) -> Decision:
    if result.spec_status == SpecStatus.MISSING:
        return Decision.REQUEST_CHANGES
    if not result.aligned:
        return Decision.REQUEST_CHANGES
    if result.architecture_concern:
        return Decision.REQUEST_CHANGES
    if any(f.category in _BLOCKING_CATEGORIES for f in result.quality_findings):
        return Decision.REQUEST_CHANGES
    if result.quality_findings:
        return Decision.COMMENT
    return Decision.APPROVE
