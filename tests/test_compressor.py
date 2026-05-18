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
    files = [_fd("a.py", 1000), _fd("b.py", 2000), _fd("c.py", 3000)]
    _, dropped = compress_files(files, budget_tokens=100)
    assert dropped == ["c.py", "b.py", "a.py"]
