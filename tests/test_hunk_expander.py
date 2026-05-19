import re

from src.review.diff_parser import FileDiff
from src.review.hunk_expander import expand_file_diff, expand_hunk_to_header, _parse_hunks

PY_FILE = "\n".join([
    "x = 1",                  # 1
    "",                       # 2
    "def calc(a, b):",        # 3
    "    total = a + b",      # 4
    "    extra = total * 2",  # 5
    "    return extra",       # 6
    "",                       # 7
    "def other():",           # 8
    "    return 0",           # 9
])


def test_expand_to_enclosing_function():
    # hunk starts at line 6 in file; we want lines 3..6 included
    expanded = expand_hunk_to_header(
        full_source=PY_FILE,
        hunk_start_line=6,
        hunk_end_line=6,
        language="python",
        max_lines=20,
    )
    assert expanded.start_line == 3
    assert expanded.end_line == 6
    assert "def calc" in expanded.text
    assert "return extra" in expanded.text


def test_no_expansion_when_no_header_above():
    expanded = expand_hunk_to_header(
        full_source=PY_FILE,
        hunk_start_line=1,
        hunk_end_line=1,
        language="python",
        max_lines=20,
    )
    assert expanded.start_line == 1
    assert "x = 1" in expanded.text


def test_max_lines_caps_search_range():
    # If header is too far up, fall back to hunk start
    long_src = "x = 0\n" * 100 + "def deep():\n    return 1\n"
    # hunk at last line (line 102); header at line 101; within range -> include
    expanded = expand_hunk_to_header(
        full_source=long_src,
        hunk_start_line=102,
        hunk_end_line=102,
        language="python",
        max_lines=5,
    )
    assert expanded.start_line == 101

    # hunk in middle (line 50), no header within 5 lines back -> no expansion
    expanded2 = expand_hunk_to_header(
        full_source=long_src,
        hunk_start_line=50,
        hunk_end_line=50,
        language="python",
        max_lines=5,
    )
    assert expanded2.start_line == 50


PY_FILE_FULL = "\n".join([
    "import os",                # 1
    "",                         # 2
    "def helper():",            # 3
    "    return 1",             # 4
    "",                         # 5
    "def main():",              # 6
    "    x = helper()",         # 7
    "    y = x + 1",            # 8
    "    return y",             # 9
])


def test_expand_file_diff_includes_function_headers():
    # hunk modifies line 8 only
    patch = "@@ -8,1 +8,1 @@\n-    y = x + 1\n+    y = x + 2\n"
    fd = FileDiff(path="a.py", additions=1, deletions=1, patch=patch)
    expanded = expand_file_diff(fd, full_source=PY_FILE_FULL, max_lines=20)
    assert "def main():" in expanded.patch
    assert "    x = helper()" in expanded.patch
    assert "y = x + 2" in expanded.patch


def test_expand_file_diff_header_has_correct_start_after_expansion():
    src = "\n".join([
        "import os",        # 1
        "",                 # 2
        "def main():",      # 3
        "    a = 1",        # 4
        "    b = 2",        # 5
        "    return a + b", # 6
    ])
    patch = "@@ -6,1 +6,1 @@\n-    return a + b\n+    return a * b\n"
    fd = FileDiff(path="a.py", additions=1, deletions=1, patch=patch)
    expanded = expand_file_diff(fd, full_source=src, max_lines=20)
    # header start should now point to the expanded position (3), not 6
    m = re.search(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", expanded.patch)
    assert m is not None, expanded.patch
    old_start, old_count, new_start, new_count = (int(x) for x in m.groups())
    assert old_start == 3
    assert new_start == 3
    # Body now has 3 prefix context lines + 1 deletion + 1 addition
    # old: 3 context + 1 deletion = 4
    # new: 3 context + 1 addition = 4
    assert old_count == 4
    assert new_count == 4


def test_parse_hunks_strips_trailing_empty_line_from_body():
    patch = "@@ -1,1 +1,1 @@\n-old\n+new\n"  # trailing newline -> empty last element
    hunks = _parse_hunks(patch)
    assert len(hunks) == 1
    _, _, body = hunks[0]
    # body should not end with an extra empty line
    assert not body.endswith("\n")
    assert body.split("\n")[-1] != ""
