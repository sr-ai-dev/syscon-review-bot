import re

_EXT_TO_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".svelte": "svelte",
}

_PATTERNS = {
    "python": [
        re.compile(r"^\s*(def |async def |class )"),
    ],
    "typescript": [
        re.compile(r"^\s*(export\s+)?(async\s+)?function\s+\w+"),
        re.compile(r"^\s*(export\s+)?class\s+\w+"),
        re.compile(r"^\s*(export\s+)?const\s+\w+\s*[:=]"),
        re.compile(r"^\s*(public|private|protected)?\s*(async\s+)?(?!(?:if|while|for|switch|return|catch|do)\b)\w+\s*\([^)]*\)\s*[:{]"),
    ],
    "svelte": [
        re.compile(r"^\s*<script"),
        re.compile(r"^\s*function\s+\w+"),
        re.compile(r"^\s*const\s+\w+\s*[:=]"),
    ],
    "generic": [
        re.compile(r"^\s*(def |class |function |export\s+(function|class)|async\s+function)"),
    ],
}


def detect_language(path: str) -> str:
    """Detect programming language from file extension."""
    for ext, lang in _EXT_TO_LANG.items():
        if path.endswith(ext):
            return lang
    return "generic"


def find_header_lines(source: str, language: str) -> list[int]:
    """Find line numbers of function/class headers in source code.

    Args:
        source: Source code as string
        language: Language identifier (python, typescript, svelte, generic)

    Returns:
        List of 1-indexed line numbers where headers are found
    """
    patterns = _PATTERNS.get(language, _PATTERNS["generic"])
    headers: list[int] = []
    for idx, line in enumerate(source.split("\n"), start=1):
        for pat in patterns:
            if pat.match(line):
                headers.append(idx)
                break
    return headers
