from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class IgnoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)


class RepositoryCostConfig(BaseModel):
    """Repository limits may only narrow the trusted action policy."""

    model_config = ConfigDict(extra="forbid")

    hard_limit_usd: Decimal | None = Field(default=None, gt=0)
    max_requests_per_pr: int | None = Field(default=None, gt=0)
    max_completion_tokens_per_call: int | None = Field(default=None, gt=0)
    max_tool_result_tokens_per_call: int | None = Field(default=None, gt=0)
    max_history_tokens: int | None = Field(default=None, gt=0)


class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    ignore: IgnoreConfig = Field(default_factory=IgnoreConfig)
    max_expand_lines: int = 50  # backward search cap for hunk expansion
    token_budget: int = 60000
    enable_judge: bool = False  # judge 1.c 룰이 부분→완전 잘못 승격하는 케이스 발견, 기본 OFF
    enable_tool_use: bool = True
    # 저장소 조회 뒤 최종 답변까지 생성할 수 있도록 3회의 모델 응답 기회를 제공한다.
    max_tool_iterations: int = 3
    confidence_threshold: int = 70
    # Chat Completions에서는 reasoning_effort와 repository tools를 함께 쓰지 못한다.
    # 기본값은 tools를 살리며, 필요하면 소비자 설정에서 reasoning을 명시한다.
    reasoning_effort: str | None = None  # "low"|"medium"|"high"|None. None=tools 활성 가능.
    require_spec_files: bool = False
    cost_control: RepositoryCostConfig | None = None
