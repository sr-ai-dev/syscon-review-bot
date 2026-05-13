# 프롬프트 정밀도 보강 — 설계

날짜: 2026-05-13

## 배경

PR #2(`review-loop-improvements`) 머지 후에도 운영 PR(sr-amr-acs-dev/sarics_nx#645) 마지막 리뷰에 false positive 3건이 남았다. 직접 검토 결과 세 mismatch 모두 부당:

1. **`replay-import-validation-dialog.svelte:95`** — 봇이 "제외 항목 위반"으로 지적. 실제 PR 본문은 `replay-time-range-picker`, `replay-timeline-bar`, `time-range.ts` 만 제외 명시. 해당 파일은 PR 본문 "적용 파일" 목록에 포함. → PR 본문 표 파싱 실패.
2. **`task-list.svelte:103`** — `toLocaleString()` → `formatTimestamp()` 변경을 "표시 형식 달라짐"으로 mismatch 처리. PR 핵심 목적이 정확히 그 변경. → PR 의도를 mismatch로 단정.
3. **`data-range-picker.svelte:13`** — `$derived(...)` 사용을 "렌더링마다 새 인스턴스"로 의심. Svelte 5 `$derived`는 의존성 변경 시에만 재실행. → 프레임워크 문법 오해.

PR #2의 "언어·프레임워크 컨벤션 한 줄"만으로는 #3 같은 문법 오해를 막기 부족. #1·#2는 별개 문제(PR 본문 파싱 + 의도 인식).

## 변경 범위

`src/review/prompt_builder.py`의 `SYSTEM_PROMPT` 보강만. 모델·결정·렌더링 구조 변경 없음.

### 1. PR 본문 적용 범위 vs 제외 범위 구분

`## 검토 순서`의 1번 항목(스펙·요구사항 식별) 끝에 추가:

```
PR 본문이 "적용 파일", "제외 항목", "범위", "out of scope" 등으로 변경 범위를 구분해두었으면 정확히 따르라. "적용 파일/범위"로 명시된 항목은 변경하는 게 정상이며 mismatch가 아니다. "제외 항목"으로 명시된 것만 변경 시 mismatch로 처리한다. 도메인이 같다고("replay 폴더 안에 있다") 자동으로 제외 항목으로 분류하지 마라.
```

### 2. PR 의도된 변경을 mismatch로 단정 금지

`## 검토 순서`의 3번 항목(present일 때 대조) 끝에 추가:

```
mismatch는 다음 셋 중 하나여야 한다: (a) 스펙이 요구한 변경이 누락, (b) 스펙 범위 밖의 무관한 변경, (c) 스펙과 다르게 구현. PR 본문의 명시된 목적이 "X를 변경하는 것"이면, X가 변경된 사실 자체를 mismatch로 보지 마라 — 그건 의도된 결과다. 변경 전후 표시·형식·동작이 다른 것은 PR이 의도했을 가능성이 높다.
```

### 3. 언어 컨벤션 일반화 강화

`## 검토 순서`의 5번 항목 안에 이미 있는 한 줄("검사 시 파일의 언어·프레임워크 문법과 컨벤션을 먼저 인지하라.")을 다음 3줄로 교체:

```
검사 시 파일의 언어·프레임워크 문법과 컨벤션을 먼저 인지하라.
식별자가 코드에 명시적으로 호출되지 않아도, 그 언어/프레임워크에서 암묵적으로 참조되는 패턴(매크로, 자동 구독, 자동 inject, 타입 전용 사용, re-export 등)이 있을 수 있다. 'unused import/dead code'로 단정하기 전에 이를 반드시 고려하라.
확신이 없으면 quality_findings에 적지 마라 — false positive는 리뷰 신뢰를 망친다.
```

특정 프레임워크 이름은 박지 않음(유지보수 부담). 일반 개념어(매크로/자동 구독/자동 inject/타입 전용/re-export)로 LLM이 추론.

## 비변경

- `Mismatch`/`QualityFinding`/`ReviewResult` 모델 — 변경 없음
- `compute_decision` — 변경 없음
- `format_review_body` — 변경 없음
- `engine.py` — 변경 없음
- diff 처리 (전체 diff 매번) — 변경 없음
- 사람 코멘트 fetch/필터 — PR #2 그대로

## 영향 파일

- `src/review/prompt_builder.py` — SYSTEM_PROMPT 세 부분 보강
- `tests/test_prompt_builder.py` — 새 검증 테스트 3개
