import base64

import httpx

from src.github.client import GitHubClient


async def get_pr_diff(client: GitHubClient, repo: str, pr_number: int) -> str:
    return await client.get(
        f"/repos/{repo}/pulls/{pr_number}",
        accept="application/vnd.github.v3.diff",
    )


async def get_pr_info(client: GitHubClient, repo: str, pr_number: int) -> dict:
    return await client.get_json(f"/repos/{repo}/pulls/{pr_number}")


async def get_repo_file(
    client: GitHubClient,
    repo: str,
    path: str,
    ref: str,
) -> str | None:
    try:
        data = await client.get_json(f"/repos/{repo}/contents/{path}?ref={ref}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
    return base64.b64decode(data["content"]).decode()
