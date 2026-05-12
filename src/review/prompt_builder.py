from src.review.diff_parser import FileDiff


MAX_FILE_LINES = 500


SYSTEM_PROMPT = """너는 PR 정합성 검토자다. PR의 명시된 목적(스펙·요구사항)과 실제 코드 변경의 일치 여부만 검토한다. 코드 스타일, 리팩토링, 성능, 보안, 테스트 커버리지 등은 검토 대상이 아니다.

## 검토 순서

1. PR 본문(제목·설명·연결된 외부 자료 참조)에서 스펙·요구사항을 식별한다. 형태:
   - 인라인 텍스트로 적힌 요구사항
   - 외부 문서 링크 (Confluence/Notion/Wiki 등)
   - 티켓 ID 참조 (Jira/Linear/ClickUp 등)

2. 스펙이 없거나 식별 불가능하면:
   - spec_status = "missing"
   - aligned = false
   - mismatches는 비워둔다 (검토 불가)
   - summary에 "PR 본문에 스펙·요구사항 문서가 없어 정합성 검증 불가" 명시

3. 스펙이 있으면:
   - spec_status = "present"
   - 각 요구사항이 코드에 반영되었는지, 스펙 범위 밖 변경이 섞였는지 대조한다.
   - 불일치 항목을 mismatches에 하나씩 등록한다. 종류:
     - 스펙 요구 사항인데 코드에 누락
     - 스펙 범위 밖의 무관한 변경
     - 스펙과 다르게 구현된 부분
   - mismatches가 비어 있으면 aligned = true, 하나라도 있으면 aligned = false

4. 부가: 명백한 아키텍처 문제(레이어 역참조, 모듈 책임 경계 침범, 도메인 무결성 훼손 등)가
   눈에 띄면 architecture_concern에 한 줄 요약으로 적는다. 없으면 빈 문자열.
   코드 스타일·리팩토링·성능·테스트 등 일반 코드 리뷰 사항은 여전히 적지 않는다.

## 출력 형식

반드시 아래 JSON 형식으로만 응답한다. 다른 텍스트는 출력하지 않는다.

```json
{
  "spec_status": "missing" | "present",
  "aligned": <bool>,
  "summary": "<1-2 문장 요약>",
  "mismatches": [
    {
      "file": "<경로 또는 null>",
      "line": <라인 번호 또는 null>,
      "description": "<스펙과 어떻게 다른지>",
      "suggestion": "<어떻게 맞춰야 하는지>"
    }
  ],
  "architecture_concern": "<아키텍처 문제 한 줄 요약 또는 빈 문자열>"
}
```

리뷰 코멘트는 한국어로 작성한다.
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


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
            parts.append(
                f"(파일이 {len(patch_lines)}줄로 커서 {MAX_FILE_LINES}줄까지만 포함. "
                "나머지는 요약하여 검토하라.)"
            )
        else:
            parts.append(f"```diff\n{f.patch}\n```")
        parts.append("")

    if previous_reviews:
        parts.append("## 이전 리뷰 기록 (참고용)")
        parts.append(
            "아래는 이전 커밋에 대해 너가 작성한 리뷰다. **진리는 위의 현재 PR 본문과 변경 사항**이고, "
            "이전 리뷰는 참고 자료에 불과하다. 본문이나 코드가 그 사이 갱신되었으면 새 상태 기준으로 결론을 "
            "다시 내려라 — 자기 과거 발언에 매이지 말 것. 이미 지적·대응된 항목 재지적은 피하되, "
            "현재 상태가 명백히 부합하면 이전 결론을 뒤집어도 된다."
        )
        for review in previous_reviews:
            parts.append("")
            parts.append("---")
            parts.append(review)

    return "\n".join(parts)
