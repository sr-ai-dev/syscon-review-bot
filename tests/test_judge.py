import pytest
from unittest.mock import AsyncMock

from src.review.judge import run_judge
from src.models.review import ReviewResult, SpecStatus


@pytest.fixture
def contradictory_result():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="모순 있음",
        prior_resolved=["그룹 패널 책임 → 일부 분리됨"],
        architecture_concern="그룹 패널이 멤버 수집·집계 직접 담당",
    )


@pytest.fixture
def judge_fixed_result():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="부분 해결 + 잔존 책임",
        prior_resolved=["(부분) 그룹 패널 책임 → 일부 분리됨, 남은 문제는 architecture_concern 참조"],
        architecture_concern="그룹 패널이 멤버 수집·집계 직접 담당",
    )


@pytest.mark.asyncio
async def test_judge_calls_gpt_with_first_result_json(contradictory_result, judge_fixed_result):
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = judge_fixed_result

    cleaned = await run_judge(mock_gpt, contradictory_result, model="m1")

    mock_gpt.review.assert_called_once()
    args = mock_gpt.review.call_args
    user_arg = args.args[1] if len(args.args) > 1 else args.kwargs["user_prompt"]
    assert "그룹 패널" in user_arg
    assert cleaned.prior_resolved[0].startswith("(부분)")


@pytest.mark.asyncio
async def test_judge_uses_passed_model(contradictory_result, judge_fixed_result):
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = judge_fixed_result

    await run_judge(mock_gpt, contradictory_result, model="gpt-x")

    kwargs = mock_gpt.review.call_args.kwargs
    assert kwargs.get("model") == "gpt-x"
