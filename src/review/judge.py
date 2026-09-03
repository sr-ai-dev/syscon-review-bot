from src.models.review import ReviewResult
from src.review.gpt_client import GPTClient
from src.review.cost import CostLedger
from src.review.judge_prompt import build_judge_system_prompt


async def run_judge(
    gpt: GPTClient,
    first_result: ReviewResult,
    model: str | None = None,
    cost_ledger: CostLedger | None = None,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> ReviewResult:
    system_prompt = build_judge_system_prompt()
    user_prompt = (
        "## 1차 리뷰 결과 (JSON)\n\n"
        "```json\n"
        f"{first_result.model_dump_json(indent=2)}\n"
        "```\n\n"
        "위 결과를 시스템 프롬프트의 규칙대로 정리한 JSON을 출력하라."
    )
    return await gpt.review(
        system_prompt,
        user_prompt,
        model=model,
        max_completion_tokens=max_completion_tokens,
        cost_ledger=cost_ledger,
        cost_stage="judge",
        reasoning_effort=reasoning_effort,
    )
