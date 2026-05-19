from src.review.compressor import compress_files
from src.review.diff_parser import FileDiff


def _fd(path, size):
    patch = "@@ -1,1 +1,1 @@\n" + ("a" * size)
    return FileDiff(path=path, additions=1, deletions=0, patch=patch)


def test_keeps_all_when_under_budget():
    files = [_fd("a.py", 100), _fd("b.py", 100)]
    kept, dropped = compress_files(files, budget_tokens=1000)
    assert len(kept) == 2
    assert dropped == []


def test_drops_largest_files_first_until_under_budget():
    files = [_fd("small.py", 50), _fd("huge.py", 5000), _fd("medium.py", 500)]
    kept, dropped = compress_files(files, budget_tokens=200)
    kept_paths = [f.path for f in kept]
    # huge가 가장 먼저 drop, medium도 drop
    assert "huge.py" in dropped
    assert "small.py" in kept_paths


def test_dropped_paths_in_order_of_size_desc():
    # drop largest first; once remaining fits in budget the rest are kept.
    # Use budget=200: total exceeds it → drop c first, then b; a fits after.
    files = [_fd("a.py", 1000), _fd("b.py", 2000), _fd("c.py", 3000)]
    kept, dropped = compress_files(files, budget_tokens=200)
    assert dropped == ["c.py", "b.py"]
    assert len(kept) == 1
    assert kept[0].path == "a.py"


def test_keeps_smallest_file_when_all_exceed_budget():
    files = [_fd("a.py", 5000), _fd("b.py", 2000), _fd("c.py", 3000)]
    kept, dropped = compress_files(files, budget_tokens=100)
    # 모두 100 초과지만 가장 작은 b.py는 keep
    assert len(kept) == 1
    assert kept[0].path == "b.py"
    assert "b.py" not in dropped
    assert set(dropped) == {"a.py", "c.py"}
