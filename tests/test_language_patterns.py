from src.review.language_patterns import detect_language, find_header_lines


def test_detect_language_by_extension():
    assert detect_language("a.py") == "python"
    assert detect_language("b.ts") == "typescript"
    assert detect_language("c.tsx") == "typescript"
    assert detect_language("d.svelte") == "svelte"
    assert detect_language("e.unknown") == "generic"


def test_find_python_headers():
    src = "x = 1\ndef foo():\n    return 1\nclass Bar:\n    pass\n"
    assert find_header_lines(src, "python") == [2, 4]


def test_find_typescript_headers():
    src = "import x\nfunction a() {}\nclass B {}\nconst c = () => 1\nexport function d() {}\n"
    assert find_header_lines(src, "typescript") == [2, 3, 4, 5]


def test_find_svelte_headers_includes_script_and_functions():
    src = "<script lang=\"ts\">\nfunction toggle() {}\n</script>\n<div>hi</div>\n"
    assert 2 in find_header_lines(src, "svelte")


def test_generic_falls_back_to_common_patterns():
    src = "def x():\n  pass\nfunction y() {}\n"
    headers = find_header_lines(src, "generic")
    assert 1 in headers and 3 in headers
