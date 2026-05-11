from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Decision(str, Enum):
    APPROVE = "approve"
    COMMENT = "comment"
    REQUEST_CHANGES = "request_changes"


class Issue(BaseModel):
    severity: Literal["critical", "warning", "minor"]
    category: str
    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str


class ReviewResult(BaseModel):
    score: int = Field(ge=1, le=10)
    summary: str
    decision: Decision
    issues: list[Issue] = Field(default_factory=list)
    good_points: list[str] = Field(default_factory=list)
