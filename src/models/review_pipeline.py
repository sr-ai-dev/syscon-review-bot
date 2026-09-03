from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.review import SpecStatus


class ReviewRoute(str, Enum):
    SINGLE = "single"
    MULTI = "multi"
    SPLIT_REQUEST = "split_request"


class RoutingReasonCode(str, Enum):
    WITHIN_SINGLE_LIMIT = "WITHIN_SINGLE_LIMIT"
    REQUIRES_MULTI_REVIEW = "REQUIRES_MULTI_REVIEW"
    SIZE_LIMIT = "SIZE_LIMIT"
    INCOMPLETE_DIFF = "INCOMPLETE_DIFF"
    UNPACKABLE_CHANGE = "UNPACKABLE_CHANGE"
    COST_PREFLIGHT_EXCEEDED = "COST_PREFLIGHT_EXCEEDED"
    COST_RUNTIME_EXCEEDED = "COST_RUNTIME_EXCEEDED"


class SizeRoutingPolicy(BaseModel):
    """Trusted upper bounds used before any model call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    single_max_effective_lines: float = Field(default=1_200, ge=0)
    single_max_effective_files: float = Field(default=40, ge=0)
    single_max_tokens: int = Field(default=40_000, ge=0)
    multi_max_effective_lines: float = Field(default=2_500, ge=0)
    multi_max_effective_files: float = Field(default=80, ge=0)
    multi_max_tokens: int = Field(default=100_000, ge=0)
    max_shards: int = Field(default=4, ge=2, le=4)
    max_tokens_per_shard: int = Field(default=30_000, gt=0)

    @model_validator(mode="after")
    def validate_ordered_limits(self):
        pairs = (
            (self.single_max_effective_lines, self.multi_max_effective_lines, "effective lines"),
            (self.single_max_effective_files, self.multi_max_effective_files, "effective files"),
            (self.single_max_tokens, self.multi_max_tokens, "tokens"),
        )
        for single, multi, label in pairs:
            if single > multi:
                raise ValueError(f"single {label} limit cannot exceed multi limit")
        return self


class ReviewSizeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    effective_lines: float = Field(ge=0)
    effective_files: float = Field(ge=0)
    effective_tokens: int = Field(ge=0)
    raw_files: int = Field(ge=0)
    raw_tokens: int = Field(ge=0)


class ReviewUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    paths: list[str]
    effective_tokens: int = Field(ge=0)
    shared_context_paths: list[str] = Field(default_factory=list)
    required: bool = True

    @property
    def covered_paths(self) -> list[str]:
        return self.paths


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_paths: list[str]
    covered_paths: list[str]

    @property
    def missing_paths(self) -> list[str]:
        covered = set(self.covered_paths)
        return [path for path in self.required_paths if path not in covered]


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ADVISORY = "advisory"


class ScopedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    severity: FindingSeverity
    description: str
    suggestion: str
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    confidence: int = Field(default=70, ge=0, le=100)


class ReviewPartial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str
    covered_paths: list[str]
    spec_status: SpecStatus
    aligned: bool
    summary: str
    findings: list[ScopedFinding] = Field(default_factory=list)
    prior_resolved: list[str] = Field(default_factory=list)


class ReviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: ReviewRoute
    head_sha: str = ""
    metrics: ReviewSizeMetrics
    reason_code: RoutingReasonCode
    units: list[ReviewUnit] = Field(default_factory=list)
    coverage: CoverageReport
    cost_ceiling_nusd: int = Field(default=1_000_000_000, ge=0)

    @model_validator(mode="after")
    def validate_owned_coverage(self):
        if self.route is ReviewRoute.SPLIT_REQUEST:
            if self.units:
                raise ValueError("split request cannot contain review units")
            return self

        owned = [path for unit in self.units for path in unit.paths]
        if len(owned) != len(set(owned)):
            raise ValueError("each path must be owned by exactly one review unit")
        if set(owned) != set(self.coverage.required_paths):
            raise ValueError("coverage mismatch between required and owned paths")
        if set(self.coverage.covered_paths) != set(self.coverage.required_paths):
            raise ValueError("coverage mismatch between required and covered paths")
        return self
