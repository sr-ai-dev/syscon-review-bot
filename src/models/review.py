from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Decision(str, Enum):
    APPROVE = "approve"
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
    confidence: int = Field(default=70, ge=0, le=100)


class SpecDocFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str
    confidence: int = Field(default=70, ge=0, le=100)


class FindingCategory(str, Enum):
    BUG = "bug"
    VULNERABILITY = "vulnerability"
    SECURITY = "security"
    SMELL = "smell"
    COMPLEXITY = "complexity"


class QualityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FindingCategory
    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str
    confidence: int = Field(default=70, ge=0, le=100)


class ArchitectureFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str
    confidence: int = Field(default=80, ge=0, le=100)


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_status: SpecStatus
    aligned: bool = False
    summary: str
    mismatches: list[Mismatch] = Field(default_factory=list)
    spec_doc_findings: list[SpecDocFinding] = Field(default_factory=list)
    architecture_findings: list[ArchitectureFinding] = Field(default_factory=list)
    quality_findings: list[QualityFinding] = Field(default_factory=list)
    prior_resolved: list[str] = Field(default_factory=list)
