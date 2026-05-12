from src.models.review import Decision, ReviewResult, SpecStatus


def compute_decision(result: ReviewResult) -> Decision:
    if result.spec_status == SpecStatus.MISSING:
        return Decision.REQUEST_CHANGES
    if not result.aligned:
        return Decision.REQUEST_CHANGES
    return Decision.APPROVE
