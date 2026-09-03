import math
import re
from dataclasses import dataclass
from typing import Callable, Iterable

from src.models.review_pipeline import (
    CoverageReport,
    ReviewPlan,
    ReviewRoute,
    ReviewSizeMetrics,
    ReviewUnit,
    RoutingReasonCode,
    SizeRoutingPolicy,
)
from src.review.diff_parser import FileDiff
from src.review.token_counter import count_tokens


TokenCounter = Callable[[str], int]


def file_weight(path: str) -> float:
    """Return the documented weight for a changed path.

    Ignore handling is deliberately external: a path is weight zero only when the
    caller says it was explicitly ignored.
    """
    normalized = path.lstrip("./")
    parts = normalized.split("/")
    basename = parts[-1].lower()

    if parts[0] in {"spec", "docs", "doc"} or basename.endswith(
        (".md", ".mdx", ".rst", ".txt")
    ):
        return 0.35
    if (
        parts[0] in {"test", "tests"}
        or "tests" in parts
        or re.match(r"test_.*\.py$", basename)
        or re.search(r"(?:^|[._-])(?:test|spec)\.[^.]+$", basename)
    ):
        return 0.60
    return 1.0


def measure_review_size(
    files: Iterable[FileDiff],
    *,
    ignored_paths: set[str] | None = None,
    token_counter: TokenCounter = count_tokens,
) -> ReviewSizeMetrics:
    files = list(files)
    ignored = ignored_paths or set()
    effective_lines = 0.0
    effective_files = 0.0
    weighted_tokens = 0.0
    raw_tokens = 0

    for changed_file in files:
        tokens = token_counter(changed_file.patch)
        raw_tokens += tokens
        weight = 0.0 if changed_file.path in ignored else file_weight(changed_file.path)
        effective_lines += weight * (changed_file.additions + 0.5 * changed_file.deletions)
        effective_files += weight
        weighted_tokens += weight * tokens

    return ReviewSizeMetrics(
        effective_lines=effective_lines,
        effective_files=effective_files,
        effective_tokens=math.ceil(weighted_tokens),
        raw_files=len(files),
        raw_tokens=raw_tokens,
    )


def classify_route(
    metrics: ReviewSizeMetrics,
    policy: SizeRoutingPolicy | None = None,
) -> tuple[ReviewRoute, RoutingReasonCode]:
    """Route on raw patch tokens; weighted tokens size reviewer shard inputs."""
    policy = policy or SizeRoutingPolicy()
    if (
        metrics.effective_lines <= policy.single_max_effective_lines
        and metrics.effective_files <= policy.single_max_effective_files
        and metrics.raw_tokens <= policy.single_max_tokens
    ):
        return ReviewRoute.SINGLE, RoutingReasonCode.WITHIN_SINGLE_LIMIT
    if (
        metrics.effective_lines <= policy.multi_max_effective_lines
        and metrics.effective_files <= policy.multi_max_effective_files
        and metrics.raw_tokens <= policy.multi_max_tokens
    ):
        return ReviewRoute.MULTI, RoutingReasonCode.REQUIRES_MULTI_REVIEW
    return ReviewRoute.SPLIT_REQUEST, RoutingReasonCode.SIZE_LIMIT


@dataclass(frozen=True)
class _Group:
    key: str
    files: tuple[FileDiff, ...]
    effective_tokens: float


def _component_key(path: str) -> str:
    parts = path.lstrip("./").split("/")
    if len(parts) >= 2 and parts[0] in {"spec", "apps", "services", "packages"}:
        return "/".join(parts[:2])

    basename = parts[-1].lower()
    stem = basename.rsplit(".", 1)[0]
    stem = re.sub(r"^(?:test|spec)[_-]", "", stem)
    stem = re.sub(r"[._-](?:test|tests|spec)$", "", stem)
    return f"logical/{stem}"


def _weighted_file_tokens(changed_file: FileDiff, token_counter: TokenCounter) -> float:
    # Shard capacity is a scoped effective-token budget. The PR-wide 40k/100k
    # routing thresholds intentionally use raw_tokens in classify_route().
    return file_weight(changed_file.path) * token_counter(changed_file.patch)


def _make_groups(files: list[FileDiff], token_counter: TokenCounter) -> list[_Group]:
    grouped: dict[str, list[FileDiff]] = {}
    for changed_file in sorted(files, key=lambda item: item.path):
        grouped.setdefault(_component_key(changed_file.path), []).append(changed_file)

    groups = [
        _Group(
            key=key,
            files=tuple(group_files),
            effective_tokens=sum(_weighted_file_tokens(item, token_counter) for item in group_files),
        )
        for key, group_files in grouped.items()
    ]
    return sorted(groups, key=lambda group: (-group.effective_tokens, group.key))


def _pack_groups(
    groups: list[_Group], policy: SizeRoutingPolicy
) -> list[list[_Group]] | None:
    bins: list[list[_Group]] = []
    loads: list[float] = []
    for group in groups:
        if group.effective_tokens > policy.max_tokens_per_shard:
            return None
        target = next(
            (
                index
                for index, load in enumerate(loads)
                if load + group.effective_tokens <= policy.max_tokens_per_shard
            ),
            None,
        )
        if target is None:
            if len(bins) == policy.max_shards:
                return None
            bins.append([group])
            loads.append(group.effective_tokens)
        else:
            bins[target].append(group)
            loads[target] += group.effective_tokens

    # A MULTI plan should use at least two useful reviewers when independent
    # groups exist, even when its token size alone would fit one shard.
    if len(bins) == 1 and len(bins[0]) > 1:
        moved = bins[0].pop()
        bins.append([moved])
    return bins


def pack_review_units(
    files: Iterable[FileDiff],
    *,
    policy: SizeRoutingPolicy | None = None,
    token_counter: TokenCounter = count_tokens,
) -> list[ReviewUnit] | None:
    policy = policy or SizeRoutingPolicy()
    files = list(files)

    # An individual file cannot be divided safely between reviewers.
    if any(
        _weighted_file_tokens(changed_file, token_counter) > policy.max_tokens_per_shard
        for changed_file in files
    ):
        return None

    bins = _pack_groups(_make_groups(files, token_counter), policy)
    if bins is None:
        return None

    root_context = sorted(changed_file.path for changed_file in files if "/" not in changed_file.path)
    units: list[ReviewUnit] = []
    for index, groups in enumerate(bins, start=1):
        owned_files = sorted(
            (changed_file for group in groups for changed_file in group.files),
            key=lambda item: item.path,
        )
        units.append(
            ReviewUnit(
                unit_id=f"shard-{index}",
                paths=[changed_file.path for changed_file in owned_files],
                effective_tokens=math.ceil(sum(group.effective_tokens for group in groups)),
                shared_context_paths=root_context,
            )
        )
    return units


def build_review_plan(
    files: Iterable[FileDiff],
    *,
    policy: SizeRoutingPolicy | None = None,
    head_sha: str = "",
    ignored_paths: set[str] | None = None,
    token_counter: TokenCounter = count_tokens,
    cost_ceiling_nusd: int = 1_000_000_000,
) -> ReviewPlan:
    policy = policy or SizeRoutingPolicy()
    all_files = list(files)
    ignored = ignored_paths or set()
    review_files = [changed_file for changed_file in all_files if changed_file.path not in ignored]
    metrics = measure_review_size(
        all_files, ignored_paths=ignored, token_counter=token_counter
    )
    route, reason_code = classify_route(metrics, policy)
    required_paths = sorted(changed_file.path for changed_file in review_files)

    if route is ReviewRoute.SPLIT_REQUEST:
        return ReviewPlan(
            route=route,
            head_sha=head_sha,
            metrics=metrics,
            reason_code=reason_code,
            coverage=CoverageReport(required_paths=required_paths, covered_paths=[]),
            cost_ceiling_nusd=cost_ceiling_nusd,
        )

    if route is ReviewRoute.SINGLE:
        unit = ReviewUnit(
            unit_id="single",
            paths=required_paths,
            effective_tokens=metrics.effective_tokens,
            shared_context_paths=sorted(path for path in required_paths if "/" not in path),
        )
        units = [unit]
    else:
        units = pack_review_units(
            review_files, policy=policy, token_counter=token_counter
        )
        if units is None:
            return ReviewPlan(
                route=ReviewRoute.SPLIT_REQUEST,
                head_sha=head_sha,
                metrics=metrics,
                reason_code=RoutingReasonCode.UNPACKABLE_CHANGE,
                coverage=CoverageReport(required_paths=required_paths, covered_paths=[]),
                cost_ceiling_nusd=cost_ceiling_nusd,
            )

    covered_paths = [path for unit in units for path in unit.paths]
    return ReviewPlan(
        route=route,
        head_sha=head_sha,
        metrics=metrics,
        reason_code=reason_code,
        units=units,
        coverage=CoverageReport(
            required_paths=required_paths,
            covered_paths=covered_paths,
        ),
        cost_ceiling_nusd=cost_ceiling_nusd,
    )
