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
