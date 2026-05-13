# 리뷰 루프 개선 — 설계

날짜: 2026-05-13

## 배경

현재 봇은 PR 코드 리뷰를 매 커밋마다 새로 작성한다. 실제 운영(sr-amr-acs-dev/sarics_nx#645)에서 다음 문제가 드러났다:

1. **언어/프레임워크 문법 무지** — Svelte `$store` 자동 구독 패턴을 모르고 `import { locale }`을 "unused import"로 잘못 신고. false positive가 12~14건 양산.
2. **이전 리뷰 항목 그대로 재출력** — 매 커밋마다 같은 finding을 그대로 다시 적는다. "참고용" 가이드가 너무 약함.
3. **동일 description의 중복 finding** — 같은 issue가 N개 파일에 적용될 때 N건의 finding으로 등록 → 표가 노이즈로 가득.
4. **사람 코멘트 무시** — 사용자가 "이건 의도다", "Svelte 문법상 정상이다" 등 응답을 달아도 다음 리뷰는 그 의사를 모른다 → 같은 항목 또 지적.

## 변경 범위

다섯 가지를 한 PR로 적용. diff 처리 방식은 **변경 없음** (현재 그대로 전체 diff를 매번 본다 — 맥락 보존 우선).

### 1. 언어·프레임워크 문법 인지

`SYSTEM_PROMPT` 5번 항목 끝에 한 줄 추가:

> 검사 시 파일의 언어·프레임워크 문법과 컨벤션을 먼저 인지하라.

원칙만 명시 — Svelte/Vue/React 등 열거 안 함 (열거 시 유지보수 끝없음). LLM이 일반화.

### 2. 이전 리뷰 재출력 금지 강화

`build_user_prompt`의 "이전 리뷰 기록 (참고용)" 섹션 본문 톤을 강하게:

- 이미 적힌 finding과 동일한 항목은 새 리뷰에 다시 적지 마라.
- 코드가 새로 바뀐 결과 새로 생긴 finding만 등록한다.
- 이전에 적었으나 이제 해결된 항목은 등록하지 않는다.
- 즉 quality_findings·mismatches는 "신규/변경분" 위주로만 채운다.

### 3. 동일 description 묶기

`SYSTEM_PROMPT` 5번 항목에 한 줄 추가:

> 동일한 description이 여러 파일에 적용되면 finding을 1개로 묶어라. `file`은 null로 두고, description 본문에 영향 받는 파일 목록을 나열한다.

모델 구조 변경 없이 description 본문에 파일 목록을 넣는 방식. 표 위치 칸은 "_전체 PR_"로 렌더링됨.

### 4. 사람 코멘트 수집

GitHub API 두 곳에서 사람 코멘트를 가져와 새 user prompt 섹션 `## 사람 코멘트`에 포함:

- `GET /repos/{repo}/issues/{n}/comments` — 일반 PR 코멘트
- `GET /repos/{repo}/pulls/{n}/comments` — 라인 리뷰 코멘트 (봇 리뷰 표 아래 답글 포함)

**필터링**: 마지막 봇 리뷰의 `submitted_at` 이후 시각(`created_at`) 코멘트만 포함. 봇 리뷰 이전 코멘트는 일반 토론이라 노이즈.

봇 자신이 단 코멘트(작성자가 봇 계정인 것)도 제외.

각 코멘트는 다음 정보로 압축:
- 작성자 로그인
- (라인 코멘트이면) `file:line`
- 본문

봇 계정 식별은 기존 `BOT_REVIEW_MARKER` 패턴이 본문에 들어가지 않으므로, 코멘트 작성자(`user.login`)가 봇과 같은지로 판별. PR 리뷰 작성자(`github-actions`/`actions/bot` 등 — 환경 변수 `GITHUB_ACTOR` 또는 마지막 봇 리뷰의 `user.login`)를 기준으로 한다. 가장 단순한 방법: **마지막 봇 리뷰의 user.login과 같은 작성자는 제외**.

### 5. 사람 의사 존중

`## 사람 코멘트` 섹션 헤더에 가이드 명시:

> 사람의 코멘트는 봇 리뷰 항목에 대한 응답일 수 있다. 사용자가 "의도", "문법상 정상", "거부", "won't fix" 등의 의사를 표명한 항목은 다음 리뷰에서 다시 지적하지 마라. 사용자가 "이건 다음에 보겠다", "확인 중" 등 미정으로 둔 항목은 신중히 판단하라.

## 비변경

- 모델(`QualityFinding`, `Mismatch`) 구조 — 변경 없음
- `compute_decision` — 변경 없음
- `format_review_body` — 변경 없음 (description에 파일 목록이 들어가도 그대로 렌더됨)
- diff 처리 (전체 diff 매번) — 변경 없음
- 결정 라벨/이벤트 매핑 — 변경 없음

## 영향 파일

- `src/review/prompt_builder.py` — SYSTEM_PROMPT 두 줄 추가, build_user_prompt 시그니처/본문 확장
- `src/github/pr.py` — `get_pr_issue_comments`, `get_pr_review_comments` 추가
- `src/review/engine.py` — 코멘트 fetch, 필터링, 프롬프트에 전달
- 테스트 — test_prompt_builder, test_engine, 새 test_pr (or 통합)
