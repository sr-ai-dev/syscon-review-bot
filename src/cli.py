import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from src.github.client import GitHubClient
from src.review.engine import ReviewContext, review_pr
from src.review.gpt_client import GPTClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("syscon-review-bot")


REQUIRED_ENV = ("GITHUB_TOKEN", "GITHUB_EVENT_PATH", "GITHUB_EVENT_NAME", "OPENAI_API_KEY")


async def main() -> int:
    for var in REQUIRED_ENV:
        if not os.environ.get(var):
            logger.error(f"Missing required environment variable: {var}")
            return 2

    event_name = os.environ["GITHUB_EVENT_NAME"]
    if event_name != "pull_request":
        logger.info(f"Skipping event '{event_name}' - only pull_request supported")
        return 0

    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    payload = json.loads(event_path.read_text())

    repo = payload.get("repository", {}).get("full_name") or os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        logger.error("Cannot determine repository (full_name missing from event)")
        return 2

    pr = payload.get("pull_request") or {}
    pr_number = pr.get("number")
    if not pr_number:
        logger.error("Cannot determine PR number from event payload")
        return 2

    token = os.environ["GITHUB_TOKEN"]
    openai_key = os.environ["OPENAI_API_KEY"]
    model_env = os.environ.get("OPENAI_MODEL")
    model_override = os.environ.get("REVIEW_MODEL_OVERRIDE") or None
    config_path = os.environ.get("REVIEW_CONFIG_PATH", ".github/review-bot.yml")

    github_client = GitHubClient(token=token)
    if model_env:
        gpt_client = GPTClient(api_key=openai_key, model=model_env)
    else:
        gpt_client = GPTClient(api_key=openai_key)

    try:
        await review_pr(
            context=ReviewContext(repo=repo, pr_number=pr_number),
            github_client=github_client,
            gpt_client=gpt_client,
            config_path=config_path,
            model_override=model_override,
        )
        return 0
    except Exception:
        logger.exception(f"Review failed for {repo}#{pr_number}")
        return 1
    finally:
        await github_client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
