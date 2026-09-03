from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.models.review import Mismatch, ReviewResult, SpecStatus
from src.models.review_pipeline import ReviewRoute
from src.review.cost import CostPolicy
from src.review.diff_parser import FileDiff
from src.review.pipeline import (
    PreflightCostExceeded,
    reduce_review_results,
    run_review_pipeline,
)
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
        _result("shard-1"),
        _result("shard-2"),
        _result("global"),
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
        model="gpt-5.6-terra",
        cost_policy=CostPolicy(hard_limit_usd="1.00"),
    )

    assert outcome.result.summary == "final"
    assert gpt.review.await_count == 4
    ledgers = [call.kwargs["cost_ledger"] for call in gpt.review.await_args_list]
    assert len({id(ledger) for ledger in ledgers}) == 1


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
            model="gpt-5.6-terra",
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
        model="gpt-5.6-terra",
        cost_policy=CostPolicy(hard_limit_usd="1", max_history_tokens=6),
        conversation_history=["OLD " * 20, "NEW"],
    )

    prompt = gpt.review.call_args.args[1]
    assert "NEW" in prompt
    assert "OLD" not in prompt
