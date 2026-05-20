"""PR spec documentation check.

Every PR must include changes to at least one spec/<feature>/ directory,
with 2+ of {requirements.md, design.md, tasks.md} modified.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

REQUIRED_FILES = ("requirements.md", "design.md", "tasks.md")
MIN_REQUIRED = 2
SPEC_DIR_PATTERN = re.compile(r"^spec/([^/]+)/")


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
        if filename in REQUIRED_FILES:
            spec_dirs.setdefault(feature, set()).add(filename)

    if not spec_dirs:
        return CheckResult(
            ok=False,
            message=(
                "PR에 spec 문서 변경이 없습니다. "
                f"모든 PR은 spec/<기능명>/ 아래 {', '.join(REQUIRED_FILES)} 중 "
                f"{MIN_REQUIRED}개 이상을 포함해야 합니다."
            ),
        )

    errors = []
    for feature, files in sorted(spec_dirs.items()):
        if len(files) < MIN_REQUIRED:
            missing = [f for f in REQUIRED_FILES if f not in files]
            errors.append(
                f"  spec/{feature}/: {len(files)}/{MIN_REQUIRED} 파일 변경됨 "
                f"(누락: {', '.join(missing)})"
            )

    if errors:
        return CheckResult(
            ok=False,
            message=(
                "spec 문서 요건 미충족:\n"
                + "\n".join(errors)
                + f"\n\n각 spec/<기능명>/ 디렉토리에 {', '.join(REQUIRED_FILES)} 중 "
                f"{MIN_REQUIRED}개 이상 변경이 필요합니다."
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
