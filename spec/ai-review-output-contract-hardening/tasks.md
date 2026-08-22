# AI Review Output Contract Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development task-by-task.

**Goal:** 정상 review의 LLM 호출 수를 늘리지 않고 strict output contract와 typed infra
오류를 제공한다.

**Architecture:** Pydantic schema projection을 별도 pure function으로 만들고,
`GPTClient`가 strict format과 typed exception을 사용하며 CLI가 안전한 infra summary를
남긴다.

**Tech Stack:** Python 3.11+, Pydantic v2, OpenAI SDK, pytest

**Status:** completed

---

### Task 1: Strict response format RED→GREEN

**Files:**
- Create: `tests/test_structured_output.py`
- Create: `src/review/structured_output.py`

1. nested object의 required/additionalProperties/default 제거와 top-level
   `json_schema/strict`를 검증하는 실패 테스트를 작성한다.
2. `uv run --with-requirements requirements-dev.txt python -m pytest -q -p no:cacheprovider tests/test_structured_output.py`를 실행해 RED를 확인한다.
3. `ReviewResult.model_json_schema()`를 재귀 strict projection하는 최소 pure function을
   구현한다.
4. 같은 명령으로 GREEN을 확인한다.

### Task 2: Typed infra error RED→GREEN

**Files:**
- Create: `src/review/errors.py`
- Modify: `tests/test_gpt_client.py`
- Modify: `src/review/gpt_client.py`

1. invalid JSON/Pydantic mismatch가 `RESPONSE_SCHEMA_ERROR`이고 response 원문이 exception
   문자열에 없는 실패 테스트를 작성한다.
2. refusal/incomplete/max-tool-iteration이 `OPENAI_RESPONSE_INCOMPLETE`인 실패 테스트를
   작성한다.
3. retry 소진 OpenAI exception이 `OPENAI_TRANSPORT_ERROR`인 실패 테스트를 작성한다.
4. targeted test를 실행해 각각 예상 원인으로 RED인지 확인한다.
5. enum, typed exception, 최소 boundary mapping을 구현한다.
6. targeted test로 GREEN을 확인한다.

### Task 3: OpenAI request contract RED→GREEN

**Files:**
- Modify: `tests/test_gpt_client.py`
- Modify: `src/review/gpt_client.py`

1. tool 미사용과 tool loop 요청 모두 `response_format.type=json_schema`, `strict=true`인지
   검사하는 실패 테스트를 작성한다.
2. 정상 no-tool review가 OpenAI completion 1회만 호출하는지 고정한다.
3. RED를 확인한 뒤 기존 `json_object`를 shared strict response format으로 교체한다.
4. targeted test로 GREEN을 확인한다.

### Task 4: CLI infra summary RED→GREEN

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/cli.py`

1. typed infra error가 exit `1`, stderr category, safe Step Summary를 만드는 실패 테스트를
   작성한다.
2. summary에 model response 원문과 secret fixture가 없는지 검증한다.
3. RED 확인 후 최소 catch/summary helper를 구현한다.
4. 기존 일반 `REQUEST_CHANGES=0`, spec gate failure=`1` 테스트와 함께 GREEN을 확인한다.

### Task 5: Regression과 scope 검증

**Files:**
- Verify: `src/**`, `tests/**`, `spec/ai-review-output-contract-hardening/**`

1. `prior_resolved` object normalization regression을 실행한다.
2. `uv run --with-requirements requirements-dev.txt python -m pytest -q -p no:cacheprovider`로 전체 suite를 실행한다.
3. `git diff --check`를 실행한다.
4. 변경 파일에 formatting repair, parser retry, finding decision 변경이 없는지 diff를
   검토한다.

## Verification Evidence

- RED: 새 module import 실패 3건으로 contract 미구현 상태를 확인
- Targeted GREEN: `34 passed`
- Full regression: `277 passed in 0.96s`
- `git diff --check`: PASS
- formatting repair call: 0
- parser-triggered full review retry: 0
