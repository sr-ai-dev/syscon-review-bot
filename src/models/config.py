from pydantic import BaseModel, ConfigDict, Field


class IgnoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)


class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    ignore: IgnoreConfig = Field(default_factory=IgnoreConfig)
    max_expand_lines: int = 50  # backward search cap for hunk expansion
    token_budget: int = 60000
    enable_judge: bool = False  # judge 1.c 룰이 부분→완전 잘못 승격하는 케이스 발견, 기본 OFF
    enable_tool_use: bool = True
    max_tool_iterations: int = 8
    confidence_threshold: int = 70
    reasoning_effort: str | None = "high"  # "low"|"medium"|"high"|None. None=비활성. 사용 시 tools/temperature 비활성됨.
    require_spec_files: bool = True
