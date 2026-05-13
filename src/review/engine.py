import logging
from dataclasses import dataclass

from src.github.client import GitHubClient
from src.github.pr import (
    get_pr_diff,
    get_pr_info,
    get_pr_reviews,
    get_pr_issue_comments,
    get_pr_review_comments,
    get_repo_file,
)
from src.github.reviewer import filter_bot_reviews, submit_review
from src.models.config import ReviewConfig
from src.review.decision import compute_decision
from src.review.diff_parser import filter_files, parse_diff
from src.review.gpt_client import GPTClient
from src.review.prompt_builder import build_system_prompt, build_user_prompt
from src.review.config_loader import DEFAULT_CONFIG, load_config_from_yaml


logger = logging.getLogger(__name__)


@dataclass
class ReviewContext:
    repo: str
    pr_number: int


async def load_repo_config(
    github_client: GitHubClient,
    repo: str,
    ref: str,
    config_path: str = ".github/review-bot.yml",
) -> ReviewConfig:
    content = await get_repo_file(github_client, repo, config_path, ref)
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
) -> None:
    logger.info(f"Reviewing {context.repo}#{context.pr_number}")

    pr_info = await get_pr_info(github_client, context.repo, context.pr_number)
    config = await load_repo_config(
        github_client, context.repo, pr_info["head"]["ref"], config_path
    )

    diff_text = await get_pr_diff(github_client, context.repo, context.pr_number)
    files = parse_diff(diff_text)
    if not files:
        logger.info("Empty diff, skipping")
        return

    filtered = filter_files(files, config.ignore)
    if not filtered:
        logger.info("All files filtered out")
        return

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
    )

    if dry_run:
        print("===== SYSTEM PROMPT =====")
        print(system_prompt)
        print()
        print("===== USER PROMPT =====")
        print(user_prompt)
        logger.info("Dry run complete (GPT/submit skipped)")
        return

    chosen_model = model_override or config.model
    result = await gpt_client.review(system_prompt, user_prompt, model=chosen_model)

    decision = compute_decision(result)
    await submit_review(github_client, context.repo, context.pr_number, result)
    logger.info(
        f"Submitted review for {context.repo}#{context.pr_number}: "
        f"spec_status={result.spec_status.value}, aligned={result.aligned}, "
        f"decision={decision.value}"
    )


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
