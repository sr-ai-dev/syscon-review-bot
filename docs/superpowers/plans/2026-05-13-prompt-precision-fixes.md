# 프롬프트 정밀도 보강 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** PR #2 머지 후에도 남은 false positive 3건(PR 본문 표 파싱 오류, 의도된 변경을 mismatch로 단정, 프레임워크 문법 오해)을 SYSTEM_PROMPT 보강으로 줄인다.

**Architecture:** `src/review/prompt_builder.py` SYSTEM_PROMPT 3곳 보강. 모델·결정·렌더링·engine 변경 없음. 각 보강은 별도 task, TDD 적용.

**Tech Stack:** Python, pytest

---

## Task 1: PR 본문 적용·제외 범위 정확 구분

**Files:**
- Modify: `src/review/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: 실패하는 테스트 작성** in `TestBuildSystemPrompt`:

```python
    def test_includes_scope_distinction_directive(self):
        prompt = build_system_prompt()
        # 적용 vs 제외 범위 구분 강조
        assert "적용" in prompt
        assert "제외" in prompt
        # 도메인 같다고 자동 제외 분류 금지
        assert "도메인" in prompt or "폴더" in prompt or "자동으로" in prompt
```

- [ ] **Step 2: Run** `uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py::TestBuildSystemPrompt::test_includes_scope_distinction_directive -v` — expect FAIL.

- [ ] **Step 3: SYSTEM_PROMPT 수정.** 1번 항목(스펙·요구사항 식별)의 끝(즉 `diff 안의 문서 본문도 PR 본문과 동등하게 읽어 요구사항을 추출한다.` 다음 줄)에 추가:

```
   PR 본문이 "적용 파일", "제외 항목", "범위", "out of scope" 등으로 변경 범위를 구분해두었으면 정확히 따르라. "적용 파일/범위"로 명시된 항목은 변경하는 게 정상이며 mismatch가 아니다. "제외 항목"으로 명시된 것만 변경 시 mismatch로 처리한다. 도메인이 같다고("replay 폴더 안에 있다") 자동으로 제외 항목으로 분류하지 마라.
```

(들여쓰기 3 spaces — 같은 1번 항목 continuation 형태.)

- [ ] **Step 4: Run** `uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py -v` — all PASS (특히 `test_states_role_is_spec_alignment_only` 금지 단어 점수/score/rubric/critical/warning/minor 회피).

- [ ] **Step 5: Commit.**
```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt): respect explicit applied/excluded scope in PR body"
```

---

## Task 2: 의도된 변경을 mismatch로 단정 금지

**Files:**
- Modify: `src/review/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: 실패 테스트** in `TestBuildSystemPrompt`:

```python
    def test_intended_changes_not_mismatch(self):
        prompt = build_system_prompt()
        # PR의 의도된 변경은 mismatch 아님 강조
        assert "의도" in prompt
        assert ("형식" in prompt or "동작" in prompt or "결과" in prompt)
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: SYSTEM_PROMPT 수정.** 3번 항목의 끝(즉 `mismatches가 비어 있으면 aligned = true, 하나라도 있으면 aligned = false` 다음 줄)에 추가:

```
   mismatch는 다음 셋 중 하나여야 한다: (a) 스펙이 요구한 변경이 누락, (b) 스펙 범위 밖의 무관한 변경, (c) 스펙과 다르게 구현. PR 본문의 명시된 목적이 "X를 변경하는 것"이면, X가 변경된 사실 자체를 mismatch로 보지 마라 — 그건 의도된 결과다. 변경 전후 표시·형식·동작이 다른 것은 PR이 의도했을 가능성이 높다.
```

(들여쓰기 3 spaces.)

- [ ] **Step 4: Run** — all PASS.

- [ ] **Step 5: Commit.**
```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt): intended changes are not mismatches"
```

---

## Task 3: 언어 컨벤션 가이드 강화 (한 줄 → 세 줄)

**Files:**
- Modify: `src/review/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: 실패 테스트** in `TestBuildSystemPrompt`:

```python
    def test_implicit_reference_patterns_listed(self):
        prompt = build_system_prompt()
        # 암묵적 참조 패턴 일반화 (특정 프레임워크 이름 박지 않음)
        assert "암묵" in prompt
        assert ("매크로" in prompt or "자동 구독" in prompt or "자동 inject" in prompt or "re-export" in prompt or "타입 전용" in prompt)
        # false positive 경고
        assert "false positive" in prompt or "신뢰" in prompt
```

- [ ] **Step 2: Run** — expect FAIL.

- [ ] **Step 3: SYSTEM_PROMPT 수정.** 5번 항목 안의 한 줄 `검사 시 파일의 언어·프레임워크 문법과 컨벤션을 먼저 인지하라.` 을 다음 세 줄로 교체 (들여쓰기 그대로):

```
   검사 시 파일의 언어·프레임워크 문법과 컨벤션을 먼저 인지하라.
   식별자가 코드에 명시적으로 호출되지 않아도, 그 언어/프레임워크에서 암묵적으로 참조되는 패턴(매크로, 자동 구독, 자동 inject, 타입 전용 사용, re-export 등)이 있을 수 있다. 'unused import/dead code'로 단정하기 전에 이를 반드시 고려하라.
   확신이 없으면 quality_findings에 적지 마라 — false positive는 리뷰 신뢰를 망친다.
```

- [ ] **Step 4: Run** — all PASS (기존 `test_includes_language_awareness_directive` 도 그대로 통과해야).

- [ ] **Step 5: Commit.**
```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt): generalize implicit-reference awareness to reduce false positives"
```

---

## Task 4: 전체 테스트 + push + PR

- [ ] **Step 1: 전체 테스트** `uv run --with-requirements requirements-dev.txt pytest -q` — all pass.

- [ ] **Step 2: Push + PR** to base `main`.

---

## Self-Review

- 스펙 커버리지: 3개 보강 모두 별도 task ✅
- 플레이스홀더 없음 ✅
- 금지 단어 (점수/score/rubric/critical/warning/minor) 회피 — 위 텍스트 모두 회피됨 ✅
- 모델/결정/엔진 변경 없음 — 회귀 위험 최소 ✅
- TDD 적용 (테스트 먼저, 실패 확인, 구현, 통과 확인) ✅
