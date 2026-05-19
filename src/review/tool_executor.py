import asyncio
import base64
import fnmatch
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
        self._file_cache: dict[str, str] = {}

    async def read_file(self, path: str) -> str:
        if path in self._file_cache:
            return self._file_cache[path]
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
                decoded = base64.b64decode(content).decode("utf-8", errors="replace")
                self._file_cache[path] = decoded
                return decoded
            except Exception as e:
                logger.warning(f"base64 decode failed for {path}: {e}")
                self._file_cache[path] = ""
                return ""
        self._file_cache[path] = content
        return content

    async def grep(self, pattern: str, path_glob: str | None = None) -> list[dict]:
        try:
            tree_data = await self._client.get_json(
                f"/repos/{self._repo}/git/trees/{quote(self._ref, safe='')}?recursive=1"
            )
        except Exception as e:
            logger.warning(f"grep tree fetch failed: {e}")
            return []

        paths = [
            entry["path"]
            for entry in tree_data.get("tree", [])
            if entry.get("type") == "blob"
        ]
        if path_glob:
            paths = [p for p in paths if fnmatch.fnmatch(p, path_glob)]
        truncated_count = max(0, len(paths) - 50)
        candidates = paths[:50]

        async def _check(path: str) -> dict | None:
            content = await self.read_file(path)
            if pattern not in content:
                return None
            lines = content.split("\n")
            matches = []
            for idx, line in enumerate(lines, start=1):
                if pattern in line:
                    matches.append({"line": idx, "text": line.strip()[:200]})
                    if len(matches) >= 5:
                        break
            return {"path": path, "matches": matches}

        results = await asyncio.gather(*[_check(p) for p in candidates], return_exceptions=False)
        hits = [r for r in results if r is not None]
        final = hits[:10]
        if truncated_count > 0:
            final.append({"_truncated_candidates": truncated_count})
        return final
