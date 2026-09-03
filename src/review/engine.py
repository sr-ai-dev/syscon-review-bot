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


async def load_repo_config(
    github_client: GitHubClient,
    repo: str,
    ref: str,
    config_path: str = ".github/review-bot.yml",
) -> ReviewConfig:
    try:
        content = await get_repo_file(github_client, repo, config_path, ref)
    except Exception as e:
        logger.warning(f"Config fetch failed at {config_path} in {repo}: {e} — using defaults")
        return DEFAULT_CONFIG
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
    config = await load_repo_config(
        github_client, context.repo, pr_info["head"]["ref"], config_path
    )
    head_sha = pr_info["head"]["sha"]
    cost_policy = cost_policy or CostPolicy()
    size_policy = size_policy or SizeRoutingPolicy()
    chosen_model = model_override or config.model
    if not chosen_model:
        default_model = getattr(gpt_client, "default_model", None)
        chosen_model = default_model if isinstance(default_model, str) else "gpt-5.6-terra"

    missing_patch_items: list[dict] = []
    try:
        diff_text = await get_pr_diff(github_client, context.repo, context.pr_number)
        files = parse_diff(diff_text)
        raw_files = None
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 406:
            raise
        logger.warning(f"Diff too large (406), falling back to files API for {context.repo}#{context.pr_number}")
        raw_files = await get_pr_files(github_client, context.repo, context.pr_number)
        files = parse_pr_files(raw_files)
        missing_patch_items = [item for item in raw_files if not item.get("patch")]

    if config.require_spec_files:
        if raw_files is None:
            raw_files = await get_pr_files(github_client, context.repo, context.pr_number)
        spec_result = check_spec_files([item["filename"] for item in raw_files])
        if not spec_result.ok:
            logger.info(f"Spec gate failed: {spec_result.message}")
            await submit_spec_gate_review(
                github_client, context.repo, context.pr_number, spec_result.message
            )
            return ReviewRunResult(Decision.REQUEST_CHANGES, spec_gate_passed=False)

    missing_patch_files = filter_files(
        [
            FileDiff(
                path=item["filename"],
                patch="",
                additions=item.get("additions", 0),
                deletions=item.get("deletions", 0),
            )
            for item in missing_patch_items
        ],
        config.ignore,
    )
    if missing_patch_files:
        inventory = filter_files([*files, *missing_patch_files], config.ignore)
        measured_plan = build_review_plan(
            inventory,
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
                required_paths=sorted(item.path for item in inventory),
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

    if not files:
        logger.info("Empty diff, skipping")
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
    bot_logins: set[str] = {
        (r.get("user") or {}).get("login")
        for r in bot_reviews
        if (r.get("user") or {}).get("login")
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
    await submit_review(github_client, context.repo, context.pr_number, result)
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
