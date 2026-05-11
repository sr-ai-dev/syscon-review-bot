from src.review.language_detector import detect_languages, LANGUAGE_BY_EXT
from src.review.diff_parser import FileDiff


def _file(path: str) -> FileDiff:
    return FileDiff(path=path, patch="", additions=0, deletions=0)


class TestDetectLanguages:
    def test_python_detected(self):
        langs = detect_languages([_file("src/main.py")])
        assert "Python" in langs

    def test_typescript_detected(self):
        langs = detect_languages([_file("src/main.ts"), _file("src/App.tsx")])
        assert "TypeScript" in langs

    def test_cpp_detected(self):
        langs = detect_languages([_file("src/main.cpp"), _file("src/util.hpp")])
        assert "C++" in langs

    def test_multiple_languages(self):
        langs = detect_languages([_file("a.py"), _file("b.java"), _file("c.cpp")])
        assert "Python" in langs
        assert "Java" in langs
        assert "C++" in langs

    def test_unknown_extension(self):
        langs = detect_languages([_file("config.weird")])
        assert "Unknown" in langs

    def test_no_files_returns_empty(self):
        assert detect_languages([]) == []

    def test_deduplicates(self):
        langs = detect_languages([_file("a.py"), _file("b.py")])
        assert langs.count("Python") == 1

    def test_language_table_has_common_languages(self):
        assert LANGUAGE_BY_EXT[".py"] == "Python"
        assert LANGUAGE_BY_EXT[".ts"] == "TypeScript"
        assert LANGUAGE_BY_EXT[".cpp"] == "C++"
        assert LANGUAGE_BY_EXT[".java"] == "Java"
