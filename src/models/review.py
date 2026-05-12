from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Decision(str, Enum):
    APPROVE = "approve"
    COMMENT = "comment"
    REQUEST_CHANGES = "request_changes"


class SpecStatus(str, Enum):
    MISSING = "missing"
    PRESENT = "present"


class Mismatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_status: SpecStatus
    aligned: bool = False
    summary: str
    mismatches: list[Mismatch] = Field(default_factory=list)
