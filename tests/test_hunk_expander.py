from src.review.hunk_expander import expand_hunk_to_header

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
