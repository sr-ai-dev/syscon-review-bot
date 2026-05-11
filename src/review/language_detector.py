from src.review.diff_parser import FileDiff


LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hxx": "C++",
    ".h": "C/C++ Header",
    ".c": "C",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
}


def detect_languages(files: list[FileDiff]) -> list[str]:
    seen: list[str] = []
    for f in files:
        if "." in f.path:
            ext = "." + f.path.rsplit(".", 1)[-1].lower()
            lang = LANGUAGE_BY_EXT.get(ext, "Unknown")
        else:
            lang = "Unknown"
        if lang not in seen:
            seen.append(lang)
    return seen
