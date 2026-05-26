"""PR spec documentation check.

Every PR must include changes to at least one spec/<feature>/ directory,
with tasks.md and at least one of {requirements.md, design.md} modified.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

TASKS_FILE = "tasks.md"
SUPPORTING_FILES = ("requirements.md", "design.md")
SPEC_FILES = (*SUPPORTING_FILES, TASKS_FILE)
SPEC_DIR_PATTERN = re.compile(r"^spec/([^/]+)/")
REQUIREMENT_MESSAGE = (
    f"{TASKS_FILE}가 반드시 있어야 하며, "
    f"{' 또는 '.join(SUPPORTING_FILES)} 중 1개 이상도 함께 있어야 합니다."
)


@dataclass
class CheckResult:
    ok: bool
    message: str


def check_spec_files(changed_files: list[str]) -> CheckResult:
    spec_dirs: dict[str, set[str]] = {}

    for path in changed_files:
        m = SPEC_DIR_PATTERN.match(path)
        if not m:
            continue
        feature = m.group(1)
        filename = path.removeprefix(f"spec/{feature}/")
        if filename in SPEC_FILES:
            spec_dirs.setdefault(feature, set()).add(filename)

    if not spec_dirs:
        return CheckResult(
            ok=False,
            message=(
                "PR에 spec 문서 변경이 없습니다. "
                f"모든 PR은 spec/<기능명>/ 아래 {REQUIREMENT_MESSAGE}"
            ),
        )

    errors = []
    for feature, files in sorted(spec_dirs.items()):
        missing = []
        if TASKS_FILE not in files:
            missing.append(TASKS_FILE)
        if not any(f in files for f in SUPPORTING_FILES):
            missing.append(f"{' 또는 '.join(SUPPORTING_FILES)} 중 1개")
        if missing:
            present = ", ".join(sorted(files)) if files else "없음"
            errors.append(f"  spec/{feature}/: 현재 {present} (누락: {', '.join(missing)})")

    if errors:
        return CheckResult(
            ok=False,
            message=(
                "spec 문서 요건 미충족:\n"
                + "\n".join(errors)
                + f"\n\n각 spec/<기능명>/ 디렉토리에 {REQUIREMENT_MESSAGE}"
            ),
        )

    features = ", ".join(sorted(spec_dirs.keys()))
    return CheckResult(ok=True, message=f"spec 문서 요건 충족 ({features})")


def main() -> None:
    changed_files = [line.strip() for line in sys.stdin if line.strip()]
    result = check_spec_files(changed_files)
    if result.ok:
        print(f"✅ {result.message}")
    else:
        print(f"❌ {result.message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
