import fnmatch
import re
from dataclasses import dataclass

from src.models.config import IgnoreConfig


@dataclass
class FileDiff:
    path: str
    patch: str
    additions: int
    deletions: int


def parse_diff(diff_text: str) -> list[FileDiff]:
    if not diff_text.strip():
        return []

    files: list[FileDiff] = []
    file_diffs = re.split(r"^diff --git ", diff_text, flags=re.MULTILINE)

    for file_diff in file_diffs:
        if not file_diff.strip():
            continue

        path_match = re.search(r"^a/(.+?) b/", file_diff, re.MULTILINE)
        if not path_match:
            continue

        path = path_match.group(1)
        patch_start = file_diff.find("@@")
        patch = file_diff[patch_start:] if patch_start != -1 else ""

        additions = len(re.findall(r"^\+[^+]", patch, re.MULTILINE))
        deletions = len(re.findall(r"^-[^-]", patch, re.MULTILINE))

        files.append(FileDiff(
            path=path,
            patch=patch,
            additions=additions,
            deletions=deletions,
        ))

    return files


def filter_files(files: list[FileDiff], ignore: IgnoreConfig) -> list[FileDiff]:
    result = []
    for f in files:
        ext = "." + f.path.rsplit(".", 1)[-1] if "." in f.path else ""
        if ext in ignore.extensions:
            continue
        if any(fnmatch.fnmatch(f.path, pattern) for pattern in ignore.files):
            continue
        result.append(f)
    return result
