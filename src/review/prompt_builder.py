from src.models.config import ReviewConfig
from src.review.diff_parser import FileDiff
from src.review.rules.builtin import BUILTIN_RULES
from src.review.rules.language_hints import build_language_section


MAX_FILE_LINES = 500


def build_system_prompt(config: ReviewConfig, languages: list[str]) -> str:
    parts = [
        "너는 다양한 프로그래밍 언어를 다루는 시니어 코드 리뷰어다.",
        "아래 기준에 따라 PR을 리뷰하라.",
        "",
        "## 리뷰 기준",
    ]

    enabled_rules = config.rules.model_dump()
    for rule_key, enabled in enabled_rules.items():
        if enabled and rule_key in BUILTIN_RULES:
            parts.append(f"- {BUILTIN_RULES[rule_key]}")

    lang_section = build_language_section(languages)
    if lang_section:
        parts.append("")
        parts.append(lang_section)

    if config.custom_rules:
        parts.append("")
        parts.append("## 팀 커스텀 규칙")
        for rule in config.custom_rules:
            parts.append(f"- {rule}")

    parts.append("")
    parts.append("## 출력 형식")
    parts.append("반드시 아래 JSON 형식으로만 응답하라:")
    parts.append("""```json
{
  "score": <1-10 정수>,
  "summary": "<전체 요약 1-2문장>",
  "decision": "approve | comment | request_changes",
  "issues": [
    {
      "severity": "critical | warning | minor",
      "category": "<카테고리>",
      "file": "<파일 경로 또는 null>",
      "line": <라인 번호 또는 null>,
      "description": "<이슈 설명>",
      "suggestion": "<수정 제안>"
    }
  ],
  "good_points": ["<잘된 점>"]
}
```""")
    parts.append("")
    parts.append(f"리뷰 코멘트 작성 언어: {config.review_language}")

    return "\n".join(parts)


def build_user_prompt(
    files: list[FileDiff],
    pr_title: str,
    pr_body: str,
    base_branch: str,
    head_branch: str,
    previous_reviews: list[str] | None = None,
) -> str:
    parts = [
        "## PR 정보",
        f"- 제목: {pr_title}",
        f"- 설명: {pr_body}",
        f"- 브랜치: {head_branch} → {base_branch}",
        "",
        "## 변경 사항",
    ]

    for f in files:
        parts.append(f"### {f.path} (+{f.additions}, -{f.deletions})")
        patch_lines = f.patch.split("\n")
        if len(patch_lines) > MAX_FILE_LINES:
            truncated = "\n".join(patch_lines[:MAX_FILE_LINES])
            parts.append(f"```diff\n{truncated}\n```")
            parts.append(f"(파일이 {len(patch_lines)}줄로 커서 {MAX_FILE_LINES}줄까지만 포함. 나머지는 요약하여 리뷰하라.)")
        else:
            parts.append(f"```diff\n{f.patch}\n```")
        parts.append("")

    if previous_reviews:
        parts.append("## 이전 리뷰 기록")
        parts.append(
            "아래는 이전 커밋에 대해 너가 직접 작성한 리뷰다. "
            "동일한 PR에 대한 후속 리뷰이므로 일관성을 유지하라: "
            "이미 지적·대응된 이슈는 재지적하지 말고, 점수/판정 기준도 이전과 크게 어긋나지 않게 하라."
        )
        for review in previous_reviews:
            parts.append("")
            parts.append("---")
            parts.append(review)

    return "\n".join(parts)
