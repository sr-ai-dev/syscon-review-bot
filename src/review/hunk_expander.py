from dataclasses import dataclass

from src.review.language_patterns import find_header_lines


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
