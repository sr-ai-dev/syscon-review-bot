import pytest
from pydantic import ValidationError

from src.models.review_pipeline import (
    CoverageReport,
    ReviewPlan,
    ReviewRoute,
    ReviewSizeMetrics,
    ReviewUnit,
    RoutingReasonCode,
    SizeRoutingPolicy,
)


def test_size_routing_policy_defaults_match_design():
    policy = SizeRoutingPolicy()

    assert policy.single_max_effective_lines == 1200
    assert policy.single_max_effective_files == 40
    assert policy.single_max_tokens == 40_000
    assert policy.multi_max_effective_lines == 2500
    assert policy.multi_max_effective_files == 80
    assert policy.multi_max_tokens == 100_000
    assert policy.max_shards == 4
    assert policy.max_tokens_per_shard == 30_000


def test_review_plan_rejects_duplicate_owned_paths():
    metrics = ReviewSizeMetrics(
        effective_lines=1, effective_files=1, effective_tokens=1,
        raw_files=1, raw_tokens=1,
    )
    with pytest.raises(ValidationError, match="exactly one review unit"):
        ReviewPlan(
            route=ReviewRoute.MULTI,
            head_sha="abc",
            metrics=metrics,
            reason_code=RoutingReasonCode.REQUIRES_MULTI_REVIEW,
            units=[
                ReviewUnit(unit_id="shard-1", paths=["a.py"], effective_tokens=1),
                ReviewUnit(unit_id="shard-2", paths=["a.py"], effective_tokens=1),
            ],
            coverage=CoverageReport(required_paths=["a.py"], covered_paths=["a.py"]),
        )


def test_review_plan_rejects_missing_coverage():
    metrics = ReviewSizeMetrics(
        effective_lines=1, effective_files=1, effective_tokens=1,
        raw_files=1, raw_tokens=1,
    )
    with pytest.raises(ValidationError, match="coverage mismatch"):
        ReviewPlan(
            route=ReviewRoute.SINGLE,
            head_sha="abc",
            metrics=metrics,
            reason_code=RoutingReasonCode.WITHIN_SINGLE_LIMIT,
            units=[ReviewUnit(unit_id="single", paths=["a.py"], effective_tokens=1)],
            coverage=CoverageReport(required_paths=["a.py", "b.py"], covered_paths=["a.py"]),
        )
