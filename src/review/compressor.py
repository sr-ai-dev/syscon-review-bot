from src.review.diff_parser import FileDiff
from src.review.token_counter import count_tokens


def compress_files(
    files: list[FileDiff],
    budget_tokens: int,
) -> tuple[list[FileDiff], list[str]]:
    """예산 초과 시 가장 큰 파일부터 drop.

    Returns (남은 파일, drop된 경로 목록).
    """
    sized = [(count_tokens(f.patch), f) for f in files]
    total = sum(t for t, _ in sized)
    if total <= budget_tokens:
        return [f for _, f in sized], []

    sized_desc = sorted(sized, key=lambda x: x[0], reverse=True)
    dropped: list[str] = []
    kept: list[FileDiff] = []
    remaining = total
    for tokens, f in sized_desc:
        if remaining > budget_tokens:
            dropped.append(f.path)
            remaining -= tokens
        else:
            kept.append(f)
    return kept, dropped
