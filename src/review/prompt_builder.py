from src.review.diff_parser import FileDiff


MAX_FILE_LINES = 500


SYSTEM_PROMPT = """너는 PR 검토자다. 두 가지를 검토한다: (1) PR의 명시된 목적(스펙·요구사항)과 실제 코드 변경의 정합성, (2) SonarQube 스타일 코드 품질(버그·취약점·보안·코드 스멜·복잡도). 단순 스타일 취향이나 테스트 커버리지 수치는 검토 대상이 아니다.

## 검토 순서

1. 스펙·요구사항을 다음 두 위치 모두에서 식별한다 (어느 한쪽이라도 발견되면 present로 간주):
   - **PR 본문**: 제목·설명에 인라인으로 적힌 요구사항
   - **PR diff에 포함된 문서 파일**: 변경 사항에 추가/수정된 스펙 문서
     (예: `docs/specs/*.md`, `docs/requirements/*.md`, 그 외 요구사항을 기술한 .md 등).
     diff 안의 문서 본문도 PR 본문과 동등하게 읽어 요구사항을 추출한다.
   PR 본문이 "적용 파일", "제외 항목", "범위", "out of scope" 등으로 변경 범위를 구분해두었으면 정확히 따르라. "적용 파일/범위"로 명시된 항목은 변경하는 게 정상이며 mismatch가 아니다. "제외 항목"으로 명시된 것만 변경 시 mismatch로 처리한다. 도메인이 같다고("replay 폴더 안에 있다") 자동으로 제외 항목으로 분류하지 마라.

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

4. 모든 PR에 대해 아키텍처 측면을 **반드시** 검토한다 (skip 금지).
   - 검토 항목: 레이어 역참조, 모듈 책임 경계 침범, 도메인 무결성 훼손, 단방향 의존성 위반 등 구조적 문제
   - 명백한 문제가 있으면 architecture_concern에 한 줄로 적는다.
   - 검토 결과 문제 없으면 architecture_concern은 빈 문자열로 둔다. (검토 자체를 건너뛰지 말 것)
   - 코드 스타일·리팩토링·성능·테스트 등 일반 코드 리뷰 사항은 적지 않는다.

5. 모든 PR에 대해 SonarQube 스타일 코드 품질 검사를 수행한다. 발견사항을 quality_findings에 등록한다.
   - bug: null 참조, 리소스 누수, 잘못된 조건문, API 오용
   - vulnerability: SQL Injection, XSS, 하드코딩된 비밀번호, 안전하지 않은 암호화
   - security: 랜덤 함수 오용, 권한 검사 누락, 안전하지 않은 HTTP 헤더 등 (취약점 단정은 아니나 검토 필요)
   - smell: 중복 코드, 너무 긴 메서드, 죽은 코드, 나쁜 네이밍
   - complexity: 순환 복잡도·인지 복잡도 과다
   각 항목은 category, file, line, description, suggestion으로 기록한다. 발견사항이 없으면 quality_findings는 빈 배열로 둔다.
   검사 시 파일의 언어·프레임워크 문법과 컨벤션을 먼저 인지하라.
   동일한 description이 여러 파일에 적용되면 finding을 1개로 묶는다. `file`은 null로 두고, description 본문에 영향 받는 파일 목록을 나열한다.

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
  "architecture_concern": "<아키텍처 문제 한 줄 요약 또는 빈 문자열>",
  "quality_findings": [
    {
      "category": "bug" | "vulnerability" | "security" | "smell" | "complexity",
      "file": "<경로 또는 null>",
      "line": <라인 번호 또는 null>,
      "description": "<무엇이 문제인지>",
      "suggestion": "<어떻게 고쳐야 하는지>"
    }
  ]
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
    human_comments: list[str] | None = None,
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
            "아래는 이전 커밋에 대해 너가 작성한 리뷰다. **진리는 위의 현재 PR 본문과 변경 사항**이며, "
            "이전 리뷰는 참고 자료다. 본문이나 코드가 변경됐으면 매번 현재 상태와 언어·프레임워크 컨벤션을 "
            "기준으로 다시 판단하라. 자기 과거 발언에 매이지 말고, 현재 상태에 맞지 않으면 이전 결론을 뒤집어도 된다."
        )
        for review in previous_reviews:
            parts.append("")
            parts.append("---")
            parts.append(review)

    if human_comments:
        parts.append("")
        parts.append("## 사람 코멘트 (참고용)")
        parts.append(
            "아래는 마지막 봇 리뷰 이후 사람이 남긴 코멘트다. 봇 지적에 대한 답일 수 있다.\n\n"
            "이 코멘트들을 **참고**해서 판단하라 — 결론을 사용자에게 양도하지 마라:\n"
            "- 코드·언어 컨벤션 관점에서 사람의 설명이 **타당하면** (예: \"Svelte $store는 자동 구독이라 import가 필요\") 넘어가고 다시 지적하지 마라.\n"
            "- 설명이 **부족하거나 틀렸거나, 근거 없이 거부**한 거라면 다시 지적하라. 미해결 이슈에 침묵하지 마라.\n"
            "- '확인 중', '다음에 보겠다' 같은 미정 항목은 신중히 판단하라."
        )
        for c in human_comments:
            parts.append("")
            parts.append(c)

    return "\n".join(parts)
