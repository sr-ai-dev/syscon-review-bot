import base64
import logging
from typing import Protocol
from urllib.parse import quote

from src.github.client import GitHubClient


logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    async def read_file(self, path: str) -> str: ...
    async def grep(self, pattern: str, path_glob: str | None = None) -> list[dict]: ...


class GitHubToolExecutor:
    def __init__(self, client: GitHubClient, repo: str, ref: str):
        self._client = client
        self._repo = repo
        self._ref = ref

    async def read_file(self, path: str) -> str:
        try:
            data = await self._client.get_json(
                f"/repos/{self._repo}/contents/{quote(path, safe='/')}?ref={quote(self._ref, safe='')}"
            )
        except Exception as e:
            logger.warning(f"read_file({path}) failed: {e}")
            return ""
        content = data.get("content", "")
        if data.get("encoding") == "base64":
            try:
                return base64.b64decode(content).decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"base64 decode failed for {path}: {e}")
                return ""
        return content

    async def grep(self, pattern: str, path_glob: str | None = None) -> list[dict]:
        q = f"{pattern} repo:{self._repo}"
        if path_glob:
            q += f" path:{path_glob}"
        try:
            data = await self._client.get_json(f"/search/code?q={quote(q)}")
        except Exception as e:
            logger.warning(f"grep({pattern}) failed: {e}")
            return []
        items = data.get("items", [])[:10]
        return [{"path": item["path"]} for item in items]
