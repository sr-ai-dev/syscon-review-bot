from decimal import Decimal
import asyncio
from unittest.mock import AsyncMock

import pytest

from src.models.review import Mismatch, ReviewResult, SpecStatus
from src.models.review_pipeline import (
    CoverageReport,
    ReviewPartial,
    ReviewPlan,
    ReviewRoute,
    ReviewSizeMetrics,
    ReviewUnit,
    RoutingReasonCode,
    ScopedFinding,
)
from src.review.cost import CostPolicy
from src.review.diff_parser import FileDiff
from src.review.pipeline import (
    PreflightCostExceeded,
    _validate_synthesis_result,
    _request_envelopes,
    reduce_review_results,
    reduce_review_partials,
    run_review_pipeline,
)
from src.review.errors import ReviewInfraCategory, ReviewInfraError
from src.review.size_router import SizeRoutingPolicy, build_review_plan


def _files(count: int = 2) -> list[FileDiff]:
    return [
        FileDiff(
            path=f"services/s{i}/module.py",
            patch="@@ -1 +1 @@\n-old\n+new\n" * 20,
            additions=20,
            deletions=20,
        )
        for i in range(count)
    ]


def _result(summary: str) -> ReviewResult:
    return ReviewResult(spec_status=SpecStatus.PRESENT, aligned=True, summary=summary)


def _partial(unit_id: str, paths: list[str], summary: str = "ok") -> ReviewPartial:
    return ReviewPartial(
        unit_id=unit_id,
        covered_paths=paths,
        spec_status=SpecStatus.PRESENT,
        aligned=True,
        summary=summary,
        findings=[],
        prior_resolved=[],
    )


@pytest.mark.parametrize(
    ("description", "suggestion", "confidence"),
    [
        ("Required  finding", "apply exact fix", 90),
        ("required finding", "different fix", 90),
        ("required finding", "apply exact fix", 89),
    ],
)
def test_synthesis_rejects_any_finding_field_mutation(
    description: str, suggestion: str, confidence: int
):
    partial = ReviewPartial(
        unit_id="reduced",
        covered_paths=["a.py"],
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="internal",
        findings=[
            ScopedFinding(
                category="mismatch",
                severity="high",
                file="a.py",
                line=1,
                description="required finding",
                suggestion="apply exact fix",
                confidence=90,
            )
        ],
    )
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="final",
        mismatches=[
            Mismatch(
                file="a.py",
                line=1,
                description=description,
                suggestion=suggestion,
                confidence=confidence,
            )
        ],
    )

    with pytest.raises(ReviewInfraError, match="changed the reviewed finding set"):
        _validate_synthesis_result(result, partial)


def test_synthesis_rejects_duplicate_finding():
    partial = ReviewPartial(
        unit_id="reduced",
        covered_paths=["a.py"],
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="internal",
        findings=[
            ScopedFinding(
                category="mismatch",
                severity="high",
                file="a.py",
                line=1,
                description="required finding",
                suggestion="apply exact fix",
                confidence=90,
            )
        ],
    )
    finding = Mismatch(
        file="a.py",
        line=1,
        description="required finding",
        suggestion="apply exact fix",
        confidence=90,
    )
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="final",
        mismatches=[finding, finding.model_copy()],
    )

    with pytest.raises(ReviewInfraError, match="changed the reviewed finding set"):
        _validate_synthesis_result(result, partial)


def test_synthesis_rejects_prior_resolved_mutation():
    partial = _partial("reduced", ["a.py"])
    partial.prior_resolved = ["old issue → exact fix"]
    result = _result("final")
    result.prior_resolved = ["old issue → rewritten fix"]

    with pytest.raises(ReviewInfraError, match="prior_resolved"):
        _validate_synthesis_result(result, partial)


def test_partial_reducer_prefers_higher_severity_before_confidence():
    low = _partial("one", ["a.py"])
    low.findings = [
        ScopedFinding(
            category="bug",
            severity="low",
            file="a.py",
            line=1,
            description="same issue",
            suggestion="low",
            confidence=100,
        )
    ]
    critical = _partial("two", ["a.py"])
    critical.findings = [
        ScopedFinding(
            category="bug",
            severity="critical",
            file="a.py",
            line=1,
            description="same issue",
            suggestion="critical",
            confidence=70,
        )
    ]

    reduced = reduce_review_partials([low, critical], ["a.py"])

    assert reduced.findings[0].severity.value == "critical"
    assert reduced.findings[0].suggestion == "critical"


def test_partial_reducer_removes_prior_resolved_for_active_finding():
    partial = _partial("one", ["a.py"])
    partial.prior_resolved = ["(부분) same issue → 일부 개선, 남은 문제는 아래 참조"]
    partial.findings = [
        ScopedFinding(
            category="bug",
            severity="high",
            file="a.py",
            line=1,
            description="same issue",
            suggestion="finish fix",
            confidence=90,
        )
    ]

    reduced = reduce_review_partials([partial], ["a.py"])

    assert reduced.prior_resolved == []


def test_result_reducer_removes_prior_resolved_for_active_finding():
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="active",
        mismatches=[
            Mismatch(
                file="a.py",
                line=1,
                description="same issue",
                suggestion="finish fix",
                confidence=90,
            )
        ],
        prior_resolved=["same issue → 이전 수정"],
    )

    reduced = reduce_review_results([result], ["a.py"])

    assert reduced.prior_resolved == []


def test_preflight_envelope_includes_schema_messages_and_tool_definition():
    plain = _request_envelopes(
        [("system", "user")],
        model="gpt-5.4-mini",
        output_cap=100,
        use_tools=False,
        reasoning_effort=None,
        include_synthesis=False,
        synthesis_paths=["a.py"],
    )
    with_tools = _request_envelopes(
        [("system", "user")],
        model="gpt-5.4-mini",
        output_cap=100,
        use_tools=True,
        reasoning_effort=None,
        include_synthesis=False,
        synthesis_paths=["a.py"],
    )

    assert plain[0][0] > 100
    assert with_tools[0][0] > plain[0][0]
    assert len(with_tools) == 1


def test_reducer_deduplicates_by_location_and_keeps_highest_confidence():
    low = ReviewResult(
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="low",
        mismatches=[
            Mismatch(
                file="b.py", line=20, description="Same  issue", suggestion="old", confidence=70
            )
        ],
    )
    high = ReviewResult(
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="high",
        mismatches=[
            Mismatch(
                file="b.py", line=20, description="same issue", suggestion="new", confidence=90
            ),
            Mismatch(
                file="a.py", line=1, description="first", suggestion="fix", confidence=80
            ),
        ],
    )

    result = reduce_review_results([low, high], ["a.py", "b.py"])

    assert [(item.file, item.line) for item in result.mismatches] == [
        ("a.py", 1),
        ("b.py", 20),
    ]
    assert result.mismatches[1].confidence == 90
    assert result.mismatches[1].suggestion == "new"


@pytest.mark.asyncio
async def test_multi_pipeline_uses_shared_ledger_and_returns_one_final_result():
    files = _files(2)
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    assert plan.route is ReviewRoute.MULTI
    gpt = AsyncMock()
    gpt.review.side_effect = [
        _partial(plan.units[0].unit_id, plan.units[0].paths, "shard-1"),
        _partial(plan.units[1].unit_id, plan.units[1].paths, "shard-2"),
        _partial("global", plan.coverage.required_paths, "global"),
        _result("final"),
    ]

    outcome = await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=gpt,
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="main",
        head_branch="feature",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1.00"),
    )

    assert outcome.result.summary == "final"
    assert gpt.review.await_count == 4
    assert all(
        call.kwargs["response_model"] is ReviewPartial
        for call in gpt.review.await_args_list[:3]
    )
    ledgers = [call.kwargs["cost_ledger"] for call in gpt.review.await_args_list]
    assert len({id(ledger) for ledger in ledgers}) == 1


@pytest.mark.asyncio
async def test_multi_pipeline_includes_planned_shared_context_in_every_shard_prompt():
    files = [
        FileDiff(
            path="pyproject.toml",
            patch="@@ -1 +1 @@\n-old-root-setting\n+shared-root-setting\n",
            additions=1,
            deletions=1,
        ),
        *_files(2),
    ]
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    assert plan.route is ReviewRoute.MULTI
    assert all("pyproject.toml" in unit.shared_context_paths for unit in plan.units)
    shard_prompts: dict[int, str] = {}

    async def review(system_prompt, user_prompt, **kwargs):
        stage = kwargs["cost_stage"]
        if stage == "synthesis":
            return _result("final")
        index = int(stage.split("-")[-1])
        if index <= len(plan.units):
            shard_prompts[index] = user_prompt
            unit = plan.units[index - 1]
            return _partial(unit.unit_id, unit.paths)
        return _partial("global", plan.coverage.required_paths)

    await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=type("FakeGPT", (), {"review": staticmethod(review)})(),
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="develop",
        head_branch="bugfix/develop/shared-context",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1"),
    )

    assert len(shard_prompts) == len(plan.units)
    assert all("shared-root-setting" in prompt for prompt in shard_prompts.values())


@pytest.mark.asyncio
async def test_multi_prompts_use_only_planned_context_and_include_full_manifest():
    files = [
        FileDiff(
            path="docs/component/notes.md",
            patch="@@ -0,0 +1 @@\n+private-doc-patch\n",
            additions=1,
            deletions=0,
        ),
        FileDiff(
            path="services/a/module.py",
            patch="@@ -1 +1 @@\n-old-a\n+new-a\n",
            additions=1,
            deletions=1,
        ),
    ]
    paths = [item.path for item in files]
    metrics = ReviewSizeMetrics(
        effective_lines=3,
        effective_files=2,
        effective_tokens=20,
        raw_files=2,
        raw_tokens=20,
    )
    plan = ReviewPlan(
        route=ReviewRoute.MULTI,
        metrics=metrics,
        reason_code=RoutingReasonCode.REQUIRES_MULTI_REVIEW,
        units=[
            ReviewUnit(unit_id="docs", paths=[paths[0]], effective_tokens=10),
            ReviewUnit(unit_id="code", paths=[paths[1]], effective_tokens=10),
        ],
        coverage=CoverageReport(required_paths=paths, covered_paths=paths),
    )
    shard_prompts: dict[str, str] = {}

    async def review(system_prompt, user_prompt, **kwargs):
        stage = kwargs["cost_stage"]
        if stage == "synthesis":
            return _result("final")
        index = int(stage.split("-")[-1])
        if index <= len(plan.units):
            unit = plan.units[index - 1]
            shard_prompts[unit.unit_id] = user_prompt
            return _partial(unit.unit_id, unit.paths)
        return _partial("global", paths)

    await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=type("FakeGPT", (), {"review": staticmethod(review)})(),
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="develop",
        head_branch="bugfix/develop/prompts",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1"),
    )

    assert all(path in prompt for prompt in shard_prompts.values() for path in paths)
    assert "private-doc-patch" in shard_prompts["docs"]
    assert "private-doc-patch" not in shard_prompts["code"]


@pytest.mark.asyncio
async def test_global_reviewer_receives_bounded_patch_without_tools_in_reasoning_mode():
    files = _files(2)
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    global_prompt = ""

    async def review(system_prompt, user_prompt, **kwargs):
        nonlocal global_prompt
        stage = kwargs["cost_stage"]
        if stage == "synthesis":
            return _result("final")
        index = int(stage.split("-")[-1])
        if index <= len(plan.units):
            unit = plan.units[index - 1]
            return _partial(unit.unit_id, unit.paths)
        global_prompt = user_prompt
        return _partial("global", plan.coverage.required_paths)

    await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=type("FakeGPT", (), {"review": staticmethod(review)})(),
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="develop",
        head_branch="bugfix/develop/global-patch",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1"),
        tool_executor=AsyncMock(),
        reasoning_effort="high",
    )

    assert "## 전역 변경 patch" in global_prompt
    assert "+new" in global_prompt


@pytest.mark.asyncio
async def test_pipeline_rejects_cost_before_first_model_call():
    files = _files(1)
    plan = build_review_plan(files)
    gpt = AsyncMock()

    with pytest.raises(PreflightCostExceeded):
        await run_review_pipeline(
            plan=plan,
            files=files,
            gpt_client=gpt,
            system_prompt="system" * 10_000,
            pr_title="title",
            pr_body="body",
            base_branch="main",
            head_branch="feature",
            model="gpt-5.4-mini",
            cost_policy=CostPolicy(hard_limit_usd=Decimal("0.000001")),
        )

    gpt.review.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_keeps_newest_history_within_token_cap():
    files = _files(1)
    plan = build_review_plan(files)
    gpt = AsyncMock()
    gpt.review.return_value = _result("ok")

    await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=gpt,
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="main",
        head_branch="feature",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1", max_history_tokens=6),
        conversation_history=["OLD " * 20, "NEW"],
    )

    prompt = gpt.review.call_args.args[1]
    assert "NEW" in prompt
    assert "OLD" not in prompt


@pytest.mark.asyncio
async def test_multi_pipeline_reserves_synthesis_before_starting_shards():
    files = _files(2)
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    synthesis_reservation_seen = False

    async def review(*args, **kwargs):
        nonlocal synthesis_reservation_seen
        ledger = kwargs["cost_ledger"]
        reserved_id = kwargs.get("pre_reserved_call_id")
        if kwargs["cost_stage"] == "synthesis":
            assert reserved_id is not None
            await ledger.reconcile(reserved_id, 1, 0, 1)
            return _result("final")
        synthesis_reservation_seen = ledger.reserved_nusd > 0
        index = int(kwargs["cost_stage"].split("-")[-1])
        if index <= len(plan.units):
            unit = plan.units[index - 1]
            return _partial(unit.unit_id, unit.paths, kwargs["cost_stage"])
        return _partial("global", plan.coverage.required_paths, kwargs["cost_stage"])

    outcome = await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=type("FakeGPT", (), {"review": staticmethod(review)})(),
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="main",
        head_branch="feature",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1"),
    )

    assert synthesis_reservation_seen
    assert outcome.ledger.reserved_nusd == 0


@pytest.mark.asyncio
async def test_parallel_failure_cancels_and_awaits_siblings_then_releases_synthesis():
    files = _files(2)
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    sibling_started = asyncio.Event()
    sibling_settled = asyncio.Event()
    captured_ledger = None

    async def review(*args, **kwargs):
        nonlocal captured_ledger
        captured_ledger = kwargs["cost_ledger"]
        stage = kwargs["cost_stage"]
        if stage == "analysis-1":
            await sibling_started.wait()
            raise RuntimeError("unit failed")
        call_id = f"fake:{stage}"
        await captured_ledger.reserve(call_id, 10_000)
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await captured_ledger.reconcile(call_id, None, None, None)
            sibling_settled.set()
            raise

    with pytest.raises(RuntimeError, match="unit failed"):
        await run_review_pipeline(
            plan=plan,
            files=files,
            gpt_client=type("FakeGPT", (), {"review": staticmethod(review)})(),
            system_prompt="system",
            pr_title="title",
            pr_body="body",
            base_branch="main",
            head_branch="feature",
            model="gpt-5.4-mini",
            cost_policy=CostPolicy(hard_limit_usd="1"),
        )

    assert sibling_settled.is_set()
    assert captured_ledger.reserved_nusd == 0
    assert captured_ledger.usage_unknown_nusd == 20_000


@pytest.mark.asyncio
async def test_reasoning_mode_omits_iteration_limit():
    files = _files(1)
    plan = build_review_plan(files)
    gpt = AsyncMock()
    gpt.review.return_value = _result("ok")

    await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=gpt,
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="main",
        head_branch="feature",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1"),
        tool_executor=AsyncMock(),
        reasoning_effort="high",
    )

    assert "max_tool_iterations" not in gpt.review.call_args.kwargs


@pytest.mark.asyncio
async def test_tool_plan_has_no_iteration_limit_argument():
    files = _files(1)
    plan = build_review_plan(files)
    gpt = AsyncMock()
    gpt.review.return_value = _result("ok")

    await run_review_pipeline(
        plan=plan,
        files=files,
        gpt_client=gpt,
        system_prompt="system",
        pr_title="title",
        pr_body="body",
        base_branch="main",
        head_branch="feature",
        model="gpt-5.4-mini",
        cost_policy=CostPolicy(hard_limit_usd="1"),
        tool_executor=AsyncMock(),
    )

    assert "max_tool_iterations" not in gpt.review.call_args.kwargs


@pytest.mark.asyncio
async def test_multi_pipeline_rejects_finding_outside_shard_scope():
    files = _files(2)
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    bad = ReviewPartial(
        unit_id=plan.units[0].unit_id,
        covered_paths=plan.units[0].paths,
        spec_status=SpecStatus.PRESENT,
        aligned=False,
        summary="out of scope",
        findings=[
            ScopedFinding(
                category="mismatch",
                severity="high",
                file="outside.py",
                line=1,
                description="bad",
                suggestion="fix",
            )
        ],
    )
    gpt = AsyncMock()
    gpt.review.return_value = bad

    with pytest.raises(ReviewInfraError) as exc_info:
        await run_review_pipeline(
            plan=plan,
            files=files,
            gpt_client=gpt,
            system_prompt="system",
            pr_title="title",
            pr_body="body",
            base_branch="main",
            head_branch="feature",
            model="gpt-5.4-mini",
            cost_policy=CostPolicy(hard_limit_usd="1"),
        )

    assert exc_info.value.category is ReviewInfraCategory.RESPONSE_SCHEMA_ERROR


@pytest.mark.asyncio
async def test_multi_pipeline_rejects_missing_attested_coverage():
    files = _files(2)
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    incomplete = _partial(plan.units[0].unit_id, [], "incomplete")
    gpt = AsyncMock()
    gpt.review.return_value = incomplete

    with pytest.raises(ReviewInfraError) as exc_info:
        await run_review_pipeline(
            plan=plan,
            files=files,
            gpt_client=gpt,
            system_prompt="system",
            pr_title="title",
            pr_body="body",
            base_branch="main",
            head_branch="feature",
            model="gpt-5.4-mini",
            cost_policy=CostPolicy(hard_limit_usd="1"),
        )

    assert exc_info.value.category is ReviewInfraCategory.RESPONSE_SCHEMA_ERROR


@pytest.mark.asyncio
async def test_synthesis_cannot_drop_an_internal_finding():
    files = _files(2)
    plan = build_review_plan(
        files,
        policy=SizeRoutingPolicy(single_max_tokens=1, max_tokens_per_shard=30_000),
        token_counter=len,
    )
    first = _partial(plan.units[0].unit_id, plan.units[0].paths)
    first.findings.append(
        ScopedFinding(
            category="mismatch",
            severity="high",
            file=plan.units[0].paths[0],
            line=1,
            description="required finding",
            suggestion="fix",
            confidence=90,
        )
    )
    gpt = AsyncMock()
    gpt.review.side_effect = [
        first,
        _partial(plan.units[1].unit_id, plan.units[1].paths),
        _partial("global", plan.coverage.required_paths),
        _result("incorrectly empty"),
    ]

    with pytest.raises(ReviewInfraError) as exc_info:
        await run_review_pipeline(
            plan=plan,
            files=files,
            gpt_client=gpt,
            system_prompt="system",
            pr_title="title",
            pr_body="body",
            base_branch="main",
            head_branch="feature",
            model="gpt-5.4-mini",
            cost_policy=CostPolicy(hard_limit_usd="1"),
        )

    assert exc_info.value.category is ReviewInfraCategory.RESPONSE_SCHEMA_ERROR
