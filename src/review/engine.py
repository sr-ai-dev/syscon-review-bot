import asyncio
import logging
from dataclasses import dataclass

import httpx

from src.github.client import GitHubClient
from src.github.pr import (
    get_pr_diff,
    get_pr_files,
    get_pr_info,
    get_pr_reviews,
    get_pr_issue_comments,
    get_pr_review_comments,
    get_repo_file,
)
from src.github.reviewer import (
    filter_bot_reviews,
    get_review_author_login,
    has_review_for_head,
    has_split_request_for_head,
    submit_review,
    submit_spec_gate_review,
    submit_split_request,
)
from src.models.config import ReviewConfig
from src.models.review import Decision
from src.models.review_pipeline import (
    CoverageReport,
    ReviewPlan,
    ReviewRoute,
    RoutingReasonCode,
    SizeRoutingPolicy,
)
from src.review.decision import compute_decision
from src.review.diff_parser import FileDiff, filter_files, parse_diff, parse_pr_files
from src.review.gpt_client import GPTClient
from src.review.prompt_builder import build_system_prompt, build_user_prompt
from src.review.config_loader import DEFAULT_CONFIG, load_config_from_yaml
from src.review.hunk_expander import expand_file_diff
from src.review.compressor import compress_files
from src.review.judge import run_judge
from src.review.postprocess import postprocess
from src.review.errors import ReviewInfraCategory, ReviewInfraError
from src.spec_check import check_spec_files
from src.review.tool_executor import GitHubToolExecutor
from src.review.cost import (
    CostLimitExceeded,
    CostPolicy,
    RequestLimitExceeded,
    UnknownModelPricing,
)
from src.review.pipeline import PreflightCostExceeded, run_review_pipeline
from src.review.size_router import build_review_plan


logger = logging.getLogger(__name__)


@dataclass
class ReviewContext:
    repo: str
    pr_number: int


@dataclass(frozen=True)
class ReviewRunResult:
    decision: Decision
    spec_gate_passed: bool = True
    route: ReviewRoute | None = None
    cost_nusd: int = 0


class HeadSnapshotChanged(RuntimeError):
    """The PR head moved while a review snapshot was being collected."""

    def __init__(self, expected_sha: str, actual_sha: str):
        self.expected_sha = expected_sha
        self.actual_sha = actual_sha
        super().__init__(
            f"PR head changed during snapshot collection: {expected_sha} -> {actual_sha}; rerun review"
        )


async def load_repo_config(
    github_client: GitHubClient,
    repo: str,
    ref: str,
    config_path: str = ".github/review-bot.yml",
) -> ReviewConfig:
    try:
        content = await get_repo_file(github_client, repo, config_path, ref)
    except Exception as exc:
        raise ReviewInfraError(
            ReviewInfraCategory.GITHUB_TRANSPORT_ERROR,
            f"Failed to fetch repository review config {config_path} at {ref}",
        ) from exc
    if content is None:
        logger.info(f"No config file at {config_path} in {repo}, using defaults")
        return DEFAULT_CONFIG
    return load_config_from_yaml(content)


async def review_pr(
    context: ReviewContext,
    github_client: GitHubClient,
    gpt_client: GPTClient,
    config_path: str = ".github/review-bot.yml",
    model_override: str | None = None,
    dry_run: bool = False,
    cost_policy: CostPolicy | None = None,
    size_policy: SizeRoutingPolicy | None = None,
) -> ReviewRunResult:
    logger.info(f"Reviewing {context.repo}#{context.pr_number}")

    pr_info = await get_pr_info(github_client, context.repo, context.pr_number)
    head_sha = pr_info["head"]["sha"]
    base_sha = (pr_info.get("base") or {}).get("sha")
    if not isinstance(base_sha, str) or not base_sha:
        raise ReviewInfraError(
            ReviewInfraCategory.GITHUB_RESPONSE_ERROR,
            "Pull request response omitted base.sha",
        )
    config = await load_repo_config(
        github_client, context.repo, base_sha, config_path
    )
    cost_policy = cost_policy or CostPolicy()
    cost_policy = cost_policy.restricted_by(config.cost_control)
    size_policy = size_policy or SizeRoutingPolicy()
    chosen_model = model_override or config.model
    if not chosen_model:
        default_model = getattr(gpt_client, "default_model", None)
        chosen_model = default_model if isinstance(default_model, str) else "gpt-5.4-mini"

    try:
        diff_text = await get_pr_diff(github_client, context.repo, context.pr_number)
        files = parse_diff(diff_text)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 406:
            raise
        logger.warning(f"Diff too large (406), falling back to files API for {context.repo}#{context.pr_number}")
        diff_text = None
        files = []

    # The files inventory is authoritative for coverage. GitHub can truncate a
    # successful diff response, so a 200 response alone is insufficient.
    raw_files = await get_pr_files(github_client, context.repo, context.pr_number)
    if diff_text is None:
        files = parse_pr_files(raw_files)

    await _assert_head_unchanged(github_client, context, head_sha)

    if config.require_spec_files:
        spec_result = check_spec_files([item["filename"] for item in raw_files])
        if not spec_result.ok:
            logger.info(f"Spec gate failed: {spec_result.message}")
            await _assert_head_unchanged(github_client, context, head_sha)
            reviews = await get_pr_reviews(
                github_client, context.repo, context.pr_number
            )
            bot_reviews = filter_bot_reviews(reviews)
            if has_review_for_head(bot_reviews, head_sha, "spec-gate"):
                logger.info(
                    "Spec gate review already exists for %s#%s at %s",
                    context.repo,
                    context.pr_number,
                    head_sha,
                )
                return ReviewRunResult(Decision.REQUEST_CHANGES, spec_gate_passed=False)
            await submit_spec_gate_review(
                github_client,
                context.repo,
                context.pr_number,
                spec_result.message,
                head_sha,
            )
            return ReviewRunResult(Decision.REQUEST_CHANGES, spec_gate_passed=False)

    inventory = filter_files([_inventory_file(item) for item in raw_files], config.ignore)
    parsed = filter_files(files, config.ignore)
    all_inventory_by_path = {item.path: item for item in inventory}
    binary_paths = {
        path for path, item in all_inventory_by_path.items() if item.is_binary
    }
    inventory_by_path = {
        path: item
        for path, item in all_inventory_by_path.items()
        if path not in binary_paths
    }
    parsed_by_path = {
        item.path: item for item in parsed if item.path not in binary_paths
    }
    inventory_paths = set(inventory_by_path)
    parsed_paths = set(parsed_by_path)
    inventory_count_mismatch = (
        isinstance(pr_info.get("changed_files"), int)
        and pr_info["changed_files"] != len(raw_files)
    )
    path_mismatch = inventory_paths != parsed_paths
    missing_required_patch = any(
        path not in parsed_by_path or not parsed_by_path[path].patch
        for path in inventory_paths
    )
    line_count_mismatch = any(
        path in parsed_by_path
        and (
            parsed_by_path[path].additions != inventory_by_path[path].additions
            or parsed_by_path[path].deletions != inventory_by_path[path].deletions
        )
        for path in inventory_paths
    )
    if (
        inventory_count_mismatch
        or path_mismatch
        or missing_required_patch
        or line_count_mismatch
    ):
        measured_plan = build_review_plan(
            list(inventory_by_path.values()),
            policy=size_policy,
            head_sha=head_sha,
            cost_ceiling_nusd=cost_policy.hard_limit_nusd,
        )
        split_plan = ReviewPlan(
            route=ReviewRoute.SPLIT_REQUEST,
            head_sha=head_sha,
            metrics=measured_plan.metrics,
            reason_code=RoutingReasonCode.INCOMPLETE_DIFF,
            coverage=CoverageReport(
                required_paths=sorted(inventory_paths),
                covered_paths=[],
            ),
            cost_ceiling_nusd=cost_policy.hard_limit_nusd,
        )
        if not dry_run:
            await _submit_split_plan(
                github_client,
                context,
                split_plan,
                size_policy,
                [RoutingReasonCode.INCOMPLETE_DIFF.value],
            )
        return ReviewRunResult(
            Decision.REQUEST_CHANGES,
            route=ReviewRoute.SPLIT_REQUEST,
        )

    # Pure renames carry a synthetic metadata patch, so planning, prompts, and
    # coverage retain the rename. Binary entries are intentionally ignored.
    files = [
        FileDiff(
            path=path,
            patch=parsed_by_path[path].patch,
            additions=inventory_by_path[path].additions,
            deletions=inventory_by_path[path].deletions,
            status=inventory_by_path[path].status,
            previous_path=inventory_by_path[path].previous_path,
            is_binary=parsed_by_path[path].is_binary,
        )
        for path in sorted(inventory_paths)
    ]

    if not files:
        logger.info("No reviewable text diff after ignoring binary files")
        return ReviewRunResult(Decision.APPROVE)

    filtered = filter_files(files, config.ignore)
    if not filtered:
        logger.info("All files filtered out")
        return ReviewRunResult(Decision.APPROVE)

    plan = build_review_plan(
        filtered,
        policy=size_policy,
        head_sha=head_sha,
        cost_ceiling_nusd=cost_policy.hard_limit_nusd,
    )
    if plan.route is ReviewRoute.SPLIT_REQUEST:
        if not dry_run:
            await _submit_split_plan(
                github_client, context, plan, size_policy, [plan.reason_code.value]
            )
        return ReviewRunResult(
            Decision.REQUEST_CHANGES,
            route=ReviewRoute.SPLIT_REQUEST,
        )

    filtered = await _expand_files(
        github_client, context.repo, head_sha, filtered, config.max_expand_lines
    )
    filtered, dropped_paths = compress_files(filtered, config.token_budget)
    if dropped_paths:
        if not dry_run:
            await _submit_split_plan(
                github_client,
                context,
                plan,
                size_policy,
                [RoutingReasonCode.INCOMPLETE_DIFF.value],
            )
        return ReviewRunResult(
            Decision.REQUEST_CHANGES, route=ReviewRoute.SPLIT_REQUEST
        )

    raw_reviews = await get_pr_reviews(github_client, context.repo, context.pr_number)
    bot_reviews = filter_bot_reviews(raw_reviews)
    if has_review_for_head(bot_reviews, head_sha, "normal"):
        logger.info(
            "Normal review already exists for %s#%s at %s",
            context.repo,
            context.pr_number,
            head_sha,
        )
        return ReviewRunResult(
            _decision_from_existing_review(bot_reviews, head_sha),
            route=plan.route,
        )
    bot_logins: set[str] = {
        login
        for r in bot_reviews
        if (login := get_review_author_login(r)) is not None
    }

    issue_comments_raw = await get_pr_issue_comments(
        github_client, context.repo, context.pr_number
    )
    review_comments_raw = await get_pr_review_comments(
        github_client, context.repo, context.pr_number
    )
    conversation_history = _build_conversation_history(
        bot_reviews, issue_comments_raw, review_comments_raw, bot_logins
    )

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(
        files=filtered,
        pr_title=pr_info["title"],
        pr_body=pr_info.get("body") or "",
        base_branch=pr_info["base"]["ref"],
        head_branch=pr_info["head"]["ref"],
        conversation_history=conversation_history,
        dropped_paths=dropped_paths,
    )

    if dry_run:
        print("===== SYSTEM PROMPT =====")
        print(system_prompt)
        print()
        print("===== USER PROMPT =====")
        print(user_prompt)
        logger.info("Dry run complete (GPT/submit skipped)")
        return ReviewRunResult(Decision.APPROVE, route=plan.route)

    executor = None
    if config.enable_tool_use:
        executor = GitHubToolExecutor(github_client, context.repo, head_sha)

    try:
        outcome = await run_review_pipeline(
            plan=plan,
            files=filtered,
            gpt_client=gpt_client,
            system_prompt=system_prompt,
            pr_title=pr_info["title"],
            pr_body=pr_info.get("body") or "",
            base_branch=pr_info["base"]["ref"],
            head_branch=pr_info["head"]["ref"],
            model=chosen_model,
            cost_policy=cost_policy,
            conversation_history=conversation_history,
            tool_executor=executor,
            max_tool_iterations=config.max_tool_iterations,
            reasoning_effort=config.reasoning_effort,
            include_judge=config.enable_judge,
        )
        result = outcome.result
        if config.enable_judge:
            result = await run_judge(
                gpt_client,
                result,
                model=chosen_model,
                cost_ledger=outcome.ledger,
                max_completion_tokens=cost_policy.max_completion_tokens_per_call,
                reasoning_effort=config.reasoning_effort,
            )
        result = postprocess(result, threshold=config.confidence_threshold)
    except (PreflightCostExceeded, CostLimitExceeded, RequestLimitExceeded, UnknownModelPricing) as exc:
        logger.warning("Review stopped by trusted cost policy: %s", type(exc).__name__)
        await _submit_split_plan(
            github_client,
            context,
            plan,
            size_policy,
            [
                RoutingReasonCode.COST_PREFLIGHT_EXCEEDED.value
                if isinstance(exc, (PreflightCostExceeded, UnknownModelPricing))
                else RoutingReasonCode.COST_RUNTIME_EXCEEDED.value
            ],
        )
        return ReviewRunResult(
            Decision.REQUEST_CHANGES,
            route=ReviewRoute.SPLIT_REQUEST,
            cost_nusd=getattr(exc, "accounted_nusd", 0),
        )

    decision = compute_decision(result)
    await _assert_head_unchanged(github_client, context, head_sha)
    latest_reviews = await get_pr_reviews(
        github_client, context.repo, context.pr_number
    )
    latest_bot_reviews = filter_bot_reviews(latest_reviews)
    if has_review_for_head(latest_bot_reviews, head_sha, "normal"):
        logger.info(
            "Normal review was submitted concurrently for %s#%s at %s",
            context.repo,
            context.pr_number,
            head_sha,
        )
    else:
        await submit_review(
            github_client, context.repo, context.pr_number, result, head_sha
        )
    logger.info(
        f"Submitted review for {context.repo}#{context.pr_number}: "
        f"spec_status={result.spec_status.value}, aligned={result.aligned}, "
        f"decision={decision.value}"
    )
    return ReviewRunResult(
        decision,
        route=plan.route,
        cost_nusd=outcome.ledger.actual_nusd + outcome.ledger.usage_unknown_nusd,
    )


async def _submit_split_plan(
    github_client: GitHubClient,
    context: ReviewContext,
    plan: ReviewPlan,
    policy: SizeRoutingPolicy,
    reason_codes: list[str],
) -> None:
    await _assert_head_unchanged(github_client, context, plan.head_sha)
    reviews = await get_pr_reviews(
        github_client, context.repo, context.pr_number
    )
    bot_reviews = filter_bot_reviews(reviews)
    if has_split_request_for_head(bot_reviews, plan.head_sha):
        logger.info(
            "Split request already exists for %s#%s at %s",
            context.repo,
            context.pr_number,
            plan.head_sha,
        )
        return
    await submit_split_request(
        github_client,
        context.repo,
        context.pr_number,
        effective_lines=plan.metrics.effective_lines,
        effective_files=plan.metrics.effective_files,
        raw_diff_tokens=plan.metrics.raw_tokens,
        max_effective_lines=policy.multi_max_effective_lines,
        max_effective_files=policy.multi_max_effective_files,
        max_raw_diff_tokens=policy.multi_max_tokens,
        reason_codes=reason_codes,
        suggested_groups=[unit.paths for unit in plan.units],
        head_sha=plan.head_sha,
    )


async def _assert_head_unchanged(
    github_client: GitHubClient,
    context: ReviewContext,
    expected_sha: str,
) -> None:
    current_pr_info = await get_pr_info(
        github_client, context.repo, context.pr_number
    )
    actual_sha = current_pr_info["head"]["sha"]
    if actual_sha != expected_sha:
        raise HeadSnapshotChanged(expected_sha, actual_sha)


def _inventory_file(item: dict) -> FileDiff:
    return FileDiff(
        path=item["filename"],
        patch=item.get("patch") or "",
        additions=item.get("additions", 0),
        deletions=item.get("deletions", 0),
        status=item.get("status", "modified"),
        previous_path=item.get("previous_filename"),
        is_binary=not item.get("patch")
        and item.get("status") != "renamed"
        and item.get("additions", 0) == 0
        and item.get("deletions", 0) == 0,
    )


async def _fetch_and_expand(github_client, repo, head_sha, f, max_lines):
    """Fetch file content and expand hunks, with error tolerance."""
    try:
        source = await get_repo_file(github_client, repo, f.path, head_sha)
    except Exception as e:
        logger.warning(f"Failed to fetch {f.path}@{head_sha} for hunk expansion: {e}")
        return f
    if source is None:
        return f
    return expand_file_diff(f, full_source=source, max_lines=max_lines)


async def _expand_files(github_client, repo, head_sha, files, max_lines):
    """Expand all files' hunks in parallel."""
    tasks = [
        _fetch_and_expand(github_client, repo, head_sha, f, max_lines)
        for f in files
    ]
    return await asyncio.gather(*tasks)


def _decision_from_existing_review(reviews: list[dict], head_sha: str) -> Decision:
    for review in reviews:
        body = review.get("body") or ""
        if has_review_for_head([review], head_sha, "normal"):
            return (
                Decision.REQUEST_CHANGES
                if "### 판정: ❌" in body
                else Decision.APPROVE
            )
    return Decision.APPROVE


def _build_conversation_history(
    bot_reviews: list[dict],
    issue_comments: list[dict],
    review_comments: list[dict],
    bot_logins: set[str],
) -> list[str]:
    """봇 리뷰(전체 본문) + 사람 코멘트를 시간순 단일 리스트로."""
    items: list[tuple[str, str]] = []

    for r in bot_reviews:
        submitted = r.get("submitted_at") or ""
        sha8 = (r.get("commit_id") or "")[:8] or "?"
        body = (r.get("body") or "").strip()
        if not body:
            continue
        header = f"[{submitted or '?'} | 커밋 {sha8} | 🤖 봇]"
        items.append((submitted, f"{header}\n{body}"))

    for c in issue_comments:
        login = (c.get("user") or {}).get("login")
        if not login or login in bot_logins:
            continue
        created = c.get("created_at") or ""
        body = (c.get("body") or "").strip()
        if not body:
            continue
        header = f"[{created or '?'} | @{login}]"
        items.append((created, f"{header}\n{body}"))

    for c in review_comments:
        login = (c.get("user") or {}).get("login")
        if not login or login in bot_logins:
            continue
        created = c.get("created_at") or ""
        body = (c.get("body") or "").strip()
        if not body:
            continue
        path = c.get("path")
        line = c.get("line") or c.get("original_line")
        if path and line:
            loc = f" ({path}:{line})"
        elif path:
            loc = f" ({path})"
        else:
            loc = ""
        header = f"[{created or '?'} | @{login}{loc}]"
        items.append((created, f"{header}\n{body}"))

    items.sort(key=lambda t: t[0])
    return [s for _, s in items]
