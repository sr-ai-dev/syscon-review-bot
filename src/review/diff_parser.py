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
    status: str = "modified"
    previous_path: str | None = None
    is_binary: bool = False


_DIFF_PATH_RE = re.compile(r'^("(?:\\.|[^"\\])*"|\S+)\s+("(?:\\.|[^"\\])*"|\S+)')


def _decode_git_path(value: str, prefix: str = "") -> str:
    """Decode Git's quoted, octal-escaped UTF-8 path representation."""
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    output = bytearray()
    index = 0
    escapes = {"n": b"\n", "t": b"\t", "r": b"\r", '"': b'"', "\\": b"\\"}
    while index < len(value):
        character = value[index]
        if character != "\\":
            output.extend(character.encode("utf-8"))
            index += 1
            continue
        octal = re.match(r"[0-7]{3}", value[index + 1:index + 4])
        if octal:
            output.append(int(octal.group(), 8))
            index += 4
            continue
        escaped = value[index + 1:index + 2]
        output.extend(escapes.get(escaped, escaped.encode("utf-8")))
        index += 2
    decoded = output.decode("utf-8", errors="replace")
    return decoded[len(prefix):] if prefix and decoded.startswith(prefix) else decoded


def _header_paths(file_diff: str) -> tuple[str, str] | None:
    header = file_diff.splitlines()[0] if file_diff else ""
    match = _DIFF_PATH_RE.match(header)
    if not match:
        return None
    return _decode_git_path(match.group(1), "a/"), _decode_git_path(match.group(2), "b/")


def parse_diff(diff_text: str) -> list[FileDiff]:
    if not diff_text.strip():
        return []

    files: list[FileDiff] = []
    file_diffs = re.split(r"^diff --git ", diff_text, flags=re.MULTILINE)

    for file_diff in file_diffs:
        if not file_diff.strip():
            continue

        paths = _header_paths(file_diff)
        if paths is None:
            continue

        previous_path, path = paths
        patch_start = file_diff.find("@@")
        patch = file_diff[patch_start:] if patch_start != -1 else ""

        additions = sum(line.startswith("+") for line in patch.splitlines())
        deletions = sum(line.startswith("-") for line in patch.splitlines())

        is_renamed = bool(re.search(r"^rename (?:from|to) ", file_diff, re.MULTILINE))
        if re.search(r"^new file mode ", file_diff, re.MULTILINE):
            status = "added"
        elif re.search(r"^deleted file mode ", file_diff, re.MULTILINE):
            status = "removed"
        elif is_renamed:
            status = "renamed"
        else:
            status = "modified"

        if is_renamed and not patch:
            rename_from = re.search(r'^rename from (.+)$', file_diff, re.MULTILINE)
            rename_to = re.search(r'^rename to (.+)$', file_diff, re.MULTILINE)
            if rename_from and rename_to:
                patch = (
                    f"rename from {_decode_git_path(rename_from.group(1))}\n"
                    f"rename to {_decode_git_path(rename_to.group(1))}"
                )

        files.append(FileDiff(
            path=path,
            patch=patch,
            additions=additions,
            deletions=deletions,
            status=status,
            previous_path=previous_path if is_renamed else None,
            is_binary=bool(re.search(r"^Binary files .* differ$", file_diff, re.MULTILINE)),
        ))

    return files


def parse_pr_files(raw: list[dict]) -> list[FileDiff]:
    files: list[FileDiff] = []
    for item in raw:
        patch = item.get("patch")
        if not patch and item.get("status") == "renamed":
            previous_path = item.get("previous_filename")
            if previous_path:
                patch = f"rename from {previous_path}\nrename to {item['filename']}"
        if not patch:
            continue
        files.append(FileDiff(
            path=item["filename"],
            patch=patch,
            additions=item.get("additions", 0),
            deletions=item.get("deletions", 0),
            status=item.get("status", "modified"),
            previous_path=item.get("previous_filename"),
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
