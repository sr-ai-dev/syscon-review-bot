# AI Review Blocker/Advisory Triage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 정상 workflow blocker와 malformed-state advisory를 분리해 advisory-only review가 수정 요구를 만들지 않게 한다.

**Architecture:** `ReviewResult`에 별도 `advisory_findings` lane을 추가한다. Prompt가 분류를 수행하고, deterministic decision은 advisory를 무시하며, reviewer는 별도 표로 표시한다.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest

---

### Task 1: Advisory model RED/GREEN

**Files:**
- Modify: `tests/test_models.py`
- Modify: `src/models/review.py`

1. `AdvisoryFinding` 생성과 `ReviewResult.advisory_findings == []`를 검증하는 실패 테스트를 작성한다.
2. `python -m pytest tests/test_models.py -q`로 RED를 확인한다.
3. 기존 finding 공통 필드와 같은 최소 Pydantic model 및 default list를 구현한다.
4. 같은 명령으로 GREEN을 확인한다.

### Task 2: Advisory decision RED/GREEN

**Files:**
- Modify: `tests/test_decision.py`
- Verify: `src/review/decision.py`

1. advisory-only 결과가 `Decision.APPROVE`인지 검증하는 실패 테스트를 작성한다.
2. RED가 model/schema 부재로 발생하는지 확인한다.
3. `compute_decision()`이 advisory를 blocker로 사용하지 않음을 최소 코드로 보장한다.
4. 기존 blocker 테스트와 함께 GREEN을 확인한다.

### Task 3: Prompt classification RED/GREEN

**Files:**
- Modify: `tests/test_prompt_builder.py`
- Modify: `src/review/prompt_builder.py`

1. 정상 workflow 재현, malformed-state advisory, 재리뷰 비승격, JSON field를 요구하는 테스트를 작성한다.
2. targeted pytest로 RED를 확인한다.
3. system prompt의 분류 기준과 output JSON schema를 최소 수정한다.
4. targeted pytest로 GREEN을 확인한다.

### Task 4: Review rendering RED/GREEN

**Files:**
- Modify: `tests/test_reviewer.py`
- Modify: `src/github/reviewer.py`

1. advisory section과 advisory-only Approved verdict를 검증하는 테스트를 작성한다.
2. targeted pytest로 RED를 확인한다.
3. `참고 사항 (Advisory)` 표 렌더링을 구현한다.
4. targeted pytest로 GREEN을 확인한다.

### Task 5: 전체 검증과 commit

**Files:**
- Verify: all changed files

1. 전체 `python -m pytest -q`를 실행한다.
2. `git diff --check`와 변경 scope를 확인한다.
3. spec과 code/test를 responsibility별 cohesive commit으로 기록한다.

### Task 6: SR-AMR consumer policy

**Repository:** `SR-AMR-Base2`

**Files:**
- Modify: `AGENTS.md`

1. `AI Review Triage` 규칙을 추가한다.
2. blocker/advisory 기준, 최대 2회 remediation, 범위 밖 hardening 분리를 명시한다.
3. shared document boundary와 `git diff --check`를 실행한다.
4. bot code와 별도 commit으로 기록한다.
