import json
import logging

from src.review.tool_executor import ToolExecutor


logger = logging.getLogger(__name__)


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Fetch the full text of a file at the PR head commit. "
                "Use when you need to inspect the body of a function or class referenced in the diff. "
                "Returns the file content as a string (truncated if very large)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative path, e.g. 'src/foo/bar.py'",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search the repo for files matching a code pattern. "
                "Use to locate where a symbol is defined when the file path is unknown. "
                "Returns up to 10 matches as {path} entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Code pattern to search for (e.g. function or class name)",
                    },
                    "path_glob": {
                        "type": "string",
                        "description": "Optional path glob filter, e.g. 'src/**' or '*.ts'",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]


async def dispatch_tool_call(
    tool_call: dict,
    executor: ToolExecutor,
    max_chars: int = 12000,
) -> str:
    name = tool_call["function"]["name"]
    try:
        args = json.loads(tool_call["function"]["arguments"] or "{}")
    except json.JSONDecodeError as e:
        return f"error: invalid arguments JSON: {e}"

    try:
        if name == "read_file":
            result = await executor.read_file(args["path"])
            return _truncate(result, max_chars)
        if name == "grep":
            matches = await executor.grep(args["pattern"], args.get("path_glob"))
            return _truncate(json.dumps(matches, ensure_ascii=False), max_chars)
    except KeyError as e:
        return f"error: missing argument {e}"
    except Exception as e:
        logger.warning(f"tool {name} raised: {e}")
        return f"error: {e}"

    return f"error: unknown tool '{name}'"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n…(잘림: {len(text) - max_chars} chars truncated)"
