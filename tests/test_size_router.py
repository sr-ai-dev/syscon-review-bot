import math

from src.models.review_pipeline import ReviewRoute, RoutingReasonCode, SizeRoutingPolicy
from src.review.diff_parser import FileDiff
from src.review.size_router import build_review_plan, measure_review_size
from src.review.token_counter import count_tokens


def fd(path: str, additions: int = 0, deletions: int = 0, patch: str = "") -> FileDiff:
    return FileDiff(path=path, additions=additions, deletions=deletions, patch=patch)


def test_weighted_metrics_use_file_kind_and_half_weight_deletions():
    files = [
        fd("src/main.py", additions=10, deletions=4, patch="production"),
        fd("tests/test_main.py", additions=10, deletions=4, patch="test"),
        fd("spec/main/requirements.md", additions=10, deletions=4, patch="spec"),
    ]

    metrics = measure_review_size(files)

    assert metrics.effective_lines == 12 + 7.2 + 4.2
    assert metrics.effective_files == 1 + 0.6 + 0.35
    assert metrics.raw_tokens == sum(count_tokens(f.patch) for f in files)
    assert metrics.effective_tokens == math.ceil(
        count_tokens("production") + 0.6 * count_tokens("test") + 0.35 * count_tokens("spec")
    )


def test_explicit_ignored_files_have_zero_weight():
    metrics = measure_review_size(
        [fd("vendor/lib.js", additions=100, patch="x " * 100)],
        ignored_paths={"vendor/lib.js"},
    )

    assert metrics.effective_lines == 0
    assert metrics.effective_files == 0
    assert metrics.effective_tokens == 0
    assert metrics.raw_files == 1


def test_single_exact_boundaries_are_allowed():
    policy = SizeRoutingPolicy(single_max_effective_files=1)
    plan = build_review_plan(
        [fd("src/a.py", additions=1200, patch="x")],
        policy=policy,
        token_counter=lambda _: 40_000,
    )

    assert plan.route is ReviewRoute.SINGLE
    assert plan.reason_code is RoutingReasonCode.WITHIN_SINGLE_LIMIT


def test_one_over_single_boundary_routes_multi():
    plan = build_review_plan(
        [fd("src/a.py", additions=601, patch="x"), fd("src/b.py", additions=600, patch="y")],
        token_counter=lambda _: 10,
    )

    assert plan.route is ReviewRoute.MULTI
    assert plan.reason_code is RoutingReasonCode.REQUIRES_MULTI_REVIEW
    assert len(plan.units) == 2


def test_raw_tokens_reject_docs_over_per_file_cap_even_when_weighted_tokens_fit():
    plan = build_review_plan(
        [fd("docs/large.md", additions=1, patch="x")],
        token_counter=lambda _: 40_001,
    )

    assert plan.metrics.effective_tokens == math.ceil(40_001 * 0.35)
    assert plan.metrics.raw_tokens == 40_001
    assert plan.route is ReviewRoute.SPLIT_REQUEST
    assert plan.reason_code is RoutingReasonCode.UNPACKABLE_CHANGE


def test_multi_exact_boundaries_are_allowed():
    policy = SizeRoutingPolicy(single_max_effective_files=1, multi_max_effective_files=4)
    plan = build_review_plan(
        [
            fd("apps/a/main.py", additions=625, patch="a"),
            fd("apps/b/main.py", additions=625, patch="b"),
            fd("apps/c/main.py", additions=625, patch="c"),
            fd("apps/d/main.py", additions=625, patch="d"),
        ],
        policy=policy,
        token_counter=lambda _: 25_000,
    )

    assert plan.route is ReviewRoute.MULTI
    assert plan.reason_code is RoutingReasonCode.REQUIRES_MULTI_REVIEW
    assert len(plan.units) == 4


def test_one_over_each_multi_boundary_requests_split():
    cases = [
        ([fd("a.py", additions=2501, patch="x")], lambda _: 1),
        ([fd(f"f{i}.py", patch="x") for i in range(81)], lambda _: 1),
        ([fd("a.py", patch="x")], lambda _: 100_001),
        ([fd("docs/a.md", patch="x"), fd("docs/b.md", patch="y")], lambda _: 50_001),
    ]

    for files, counter in cases:
        plan = build_review_plan(files, token_counter=counter)
        assert plan.route is ReviewRoute.SPLIT_REQUEST
        assert plan.reason_code is RoutingReasonCode.SIZE_LIMIT
        assert plan.units == []


def test_single_file_over_shard_cap_is_unpackable():
    policy = SizeRoutingPolicy(single_max_tokens=10, max_tokens_per_shard=30_000)
    plan = build_review_plan([fd("a.py", patch="x")], policy=policy, token_counter=lambda _: 30_001)

    assert plan.route is ReviewRoute.SPLIT_REQUEST
    assert plan.reason_code is RoutingReasonCode.UNPACKABLE_CHANGE


def test_weighted_document_cannot_bypass_raw_per_file_shard_cap():
    policy = SizeRoutingPolicy(single_max_tokens=10, max_tokens_per_shard=30_000)

    plan = build_review_plan(
        [fd("docs/large.md", patch="x")],
        policy=policy,
        token_counter=lambda _: 30_001,
    )

    assert plan.route is ReviewRoute.SPLIT_REQUEST
    assert plan.reason_code is RoutingReasonCode.UNPACKABLE_CHANGE


def test_shared_context_consumes_every_shard_capacity():
    policy = SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000)
    files = [
        fd("README.md", patch="shared"),
        fd("apps/api/main.py", patch="api"),
        fd("apps/web/main.py", patch="web"),
    ]
    token_sizes = {"shared": 10_000, "api": 20_001, "web": 1}

    plan = build_review_plan(
        files, policy=policy, token_counter=token_sizes.__getitem__
    )

    assert plan.route is ReviewRoute.SPLIT_REQUEST
    assert plan.reason_code is RoutingReasonCode.UNPACKABLE_CHANGE


def test_nested_shared_document_is_budgeted_and_listed_for_every_shard():
    policy = SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000)
    files = [
        fd("docs/architecture.md", patch="shared"),
        fd("apps/api/main.py", patch="api"),
        fd("apps/web/main.py", patch="web"),
    ]
    token_sizes = {"shared": 5_000, "api": 20_000, "web": 20_000}

    plan = build_review_plan(
        files, policy=policy, token_counter=token_sizes.__getitem__
    )

    assert plan.route is ReviewRoute.MULTI
    assert len(plan.units) == 2
    assert all("docs/architecture.md" in unit.shared_context_paths for unit in plan.units)
    assert all(unit.effective_tokens == 25_000 for unit in plan.units)


def test_multi_route_with_one_indivisible_group_is_unpackable():
    policy = SizeRoutingPolicy(single_max_effective_lines=1)

    plan = build_review_plan(
        [fd("apps/api/main.py", additions=2, patch="small")],
        policy=policy,
        token_counter=lambda _: 10,
    )

    assert plan.route is ReviewRoute.SPLIT_REQUEST
    assert plan.reason_code is RoutingReasonCode.UNPACKABLE_CHANGE


def test_multi_shards_are_stable_independent_of_input_order_and_cover_once():
    files = [
        fd("apps/api/service.py", additions=500, patch="a"),
        fd("apps/web/page.py", additions=500, patch="b"),
        fd("services/jobs/run.py", additions=500, patch="c"),
        fd("packages/common/util.py", additions=1, patch="d"),
    ]
    token_sizes = {"a": 20_000, "b": 18_000, "c": 12_000, "d": 2_000}
    counter = token_sizes.__getitem__

    first = build_review_plan(files, token_counter=counter)
    reversed_plan = build_review_plan(list(reversed(files)), token_counter=counter)

    assert first.route is ReviewRoute.MULTI
    assert [u.model_dump() for u in first.units] == [u.model_dump() for u in reversed_plan.units]
    owned = [path for unit in first.units for path in unit.paths]
    assert sorted(owned) == sorted(f.path for f in files)
    assert len(owned) == len(set(owned))
    assert len(first.units) <= 4
    assert all(unit.effective_tokens <= 30_000 for unit in first.units)


def test_more_than_four_required_shards_is_unpackable():
    policy = SizeRoutingPolicy(
        single_max_tokens=1,
        multi_max_tokens=200_000,
        max_tokens_per_shard=30_000,
        max_shards=4,
    )
    files = [fd(f"apps/c{i}/f.py", patch=str(i)) for i in range(5)]

    plan = build_review_plan(files, policy=policy, token_counter=lambda _: 20_000)

    assert plan.route is ReviewRoute.SPLIT_REQUEST
    assert plan.reason_code is RoutingReasonCode.UNPACKABLE_CHANGE
