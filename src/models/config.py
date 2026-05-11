from typing import Literal

from pydantic import BaseModel, Field


class RulesConfig(BaseModel):
    architecture: bool = True
    type_safety: bool = True
    code_quality: bool = True
    test_coverage: bool = True
    performance: bool = True
    security: bool = True
    error_handling: bool = True
    refactoring: bool = True
    documentation: bool = True


class ApprovalCriteria(BaseModel):
    max_high_issues: int = 0
    max_medium_issues: int = 3


class IgnoreConfig(BaseModel):
    files: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)


class ReviewConfig(BaseModel):
    review_language: str = "korean"
    severity_threshold: Literal["low", "medium", "high"] = "medium"
    model: str | None = None
    rules: RulesConfig = Field(default_factory=RulesConfig)
    custom_rules: list[str] = Field(default_factory=list)
    ignore: IgnoreConfig = Field(default_factory=IgnoreConfig)
    approve_criteria: ApprovalCriteria = Field(default_factory=ApprovalCriteria)
