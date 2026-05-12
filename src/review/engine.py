import logging
from dataclasses import dataclass

from src.github.client import GitHubClient
from src.github.pr import get_pr_diff, get_pr_info, get_pr_reviews, get_repo_file
from src.github.reviewer import filter_bot_reviews, submit_review
from src.models.config import ReviewConfig
from src.review.decision import compute_decision
from src.review.diff_parser import filter_files, parse_diff
from src.review.gpt_client import GPTClient
from src.review.language_detector import detect_languages
from src.review.prompt_builder import build_system_prompt, build_user_prompt
from src.review.rules.loader import DEFAULT_CONFIG, load_config_from_yaml


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
) -> None:
    logger.info(f"Reviewing {context.repo}#{context.pr_number}")

    pr_info = await get_pr_info(github_client, context.repo, context.pr_number)
    # Load config from the PR head ref so a PR can iterate on its own review-bot.yml.
    # Trade-off: a PR can weaken its own rules; reviewers should watch for config changes.
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
    previous_reviews = [r["body"] for r in filter_bot_reviews(raw_reviews)]

    languages = detect_languages(filtered)
    system_prompt = build_system_prompt(config, languages)
    user_prompt = build_user_prompt(
        files=filtered,
        pr_title=pr_info["title"],
        pr_body=pr_info.get("body") or "",
        base_branch=pr_info["base"]["ref"],
        head_branch=pr_info["head"]["ref"],
        previous_reviews=previous_reviews,
    )

    chosen_model = model_override or config.model
    result = await gpt_client.review(system_prompt, user_prompt, model=chosen_model)

    result.decision = compute_decision(
        score=result.score,
        issues=result.issues,
        criteria=config.approve_criteria,
    )

    await submit_review(github_client, context.repo, context.pr_number, result)
    logger.info(
        f"Submitted review for {context.repo}#{context.pr_number}: "
        f"score={result.score}, decision={result.decision.value}, "
        f"languages={languages}"
    )
