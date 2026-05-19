import re
from dataclasses import dataclass

from src.review.diff_parser import FileDiff
from src.review.language_patterns import detect_language, find_header_lines


@dataclass
class ExpandedHunk:
    start_line: int
    end_line: int
    text: str


def expand_hunk_to_header(
    full_source: str,
    hunk_start_line: int,
    hunk_end_line: int,
    language: str,
    max_lines: int,
) -> ExpandedHunk:
    """Expand a hunk backward to its enclosing function/class header.

    Args:
        full_source: Complete source code as string
        hunk_start_line: 1-indexed starting line of the hunk
        hunk_end_line: 1-indexed ending line of the hunk
        language: Language identifier (python, typescript, svelte, generic)
        max_lines: Maximum lines to search backward for a header

    Returns:
        ExpandedHunk with expanded range or original hunk if no header found
    """
    lines = full_source.split("\n")
    headers = find_header_lines(full_source, language)

    # Find candidate headers that are:
    # 1. Before the hunk start
    # 2. Within max_lines distance
    candidate_headers = [
        h for h in headers
        if h < hunk_start_line and (hunk_start_line - h) <= max_lines
    ]
    new_start = max(candidate_headers) if candidate_headers else hunk_start_line

    # Extract text from new_start to hunk_end_line
    selected = lines[new_start - 1 : hunk_end_line]
    return ExpandedHunk(
        start_line=new_start, end_line=hunk_end_line, text="\n".join(selected)
    )


_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_hunks(patch: str) -> list[tuple[int, int, str]]:
    """Parse unified diff patch into list of (new_start, new_lines, hunk_body) tuples."""
    hunks: list[tuple[int, int, str]] = []
    cur_start: int | None = None
    cur_lines: int | None = None
    cur_body: list[str] = []

    def _finalize_body(body: list[str]) -> str:
        # Strip trailing empty strings produced by split on a trailing newline
        while body and body[-1] == "":
            body.pop()
        return "\n".join(body)

    for line in patch.split("\n"):
        m = _HUNK_HEADER_RE.match(line)
        if m:
            if cur_start is not None:
                hunks.append((cur_start, cur_lines or 0, _finalize_body(cur_body)))
            cur_start = int(m.group(1))
            cur_lines = int(m.group(2) or "1")
            cur_body = []
        elif cur_start is not None:
            cur_body.append(line)
    if cur_start is not None:
        hunks.append((cur_start, cur_lines or 0, _finalize_body(cur_body)))
    return hunks


def _count_body_lines(body: str) -> tuple[int, int]:
    """Return (old_count, new_count) by counting -/+/' ' prefixes in body."""
    old, new = 0, 0
    for line in body.split("\n"):
        if not line:
            continue
        prefix = line[0]
        if prefix == "-":
            old += 1
        elif prefix == "+":
            new += 1
        elif prefix == " ":
            old += 1
            new += 1
    return old, new


def expand_file_diff(fd: FileDiff, full_source: str, max_lines: int) -> FileDiff:
    """Expand all hunks in a FileDiff to include enclosing function/class headers.

    Each hunk body is prepended with context lines (prefixed with a space)
    from the enclosing header up to the hunk start, preserving unified diff format.

    Args:
        fd: FileDiff with path and patch text
        full_source: Complete file source as a string
        max_lines: Maximum lines to search backward for a header

    Returns:
        New FileDiff with expanded patch text, or original fd if patch has no hunks.
    """
    hunks = _parse_hunks(fd.patch)
    if not hunks:
        return fd

    language = detect_language(fd.path)
    file_lines = full_source.split("\n")
    new_parts: list[str] = []

    for new_start, new_lines, body in hunks:
        end_line = new_start + max(new_lines - 1, 0)
        expanded = expand_hunk_to_header(
            full_source=full_source,
            hunk_start_line=new_start,
            hunk_end_line=end_line,
            language=language,
            max_lines=max_lines,
        )
        # Lines between expanded start and hunk start (exclusive) become context lines
        prefix_lines = file_lines[expanded.start_line - 1 : new_start - 1]
        prefix_count = len(prefix_lines)
        old_changed, new_changed = _count_body_lines(body)
        old_count = old_changed + prefix_count
        new_count = new_changed + prefix_count
        start = expanded.start_line
        header = f"@@ -{start},{old_count} +{start},{new_count} @@"
        new_parts.append(header)
        if prefix_lines:
            prefix = "\n".join(" " + line for line in prefix_lines)
            new_parts.append(prefix)
        new_parts.append(body)

    return FileDiff(
        path=fd.path,
        patch="\n".join(new_parts),
        additions=fd.additions,
        deletions=fd.deletions,
    )
