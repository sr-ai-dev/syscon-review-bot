# Cross-file Tool-use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR 리뷰 LLM이 호출 시그니처만으로 의미 추론하지 않도록, OpenAI function calling으로 `read_file` / `grep` tool을 제공해 LLM이 자율적으로 정의 파일을 fetch하고 본문을 검증하게 한다.

**Architecture:** `gpt_client.review()`를 tool-use 루프로 개조한다. 호출자가 `ToolExecutor`를 주입하면, 매 OpenAI 응답에 `tool_calls`가 있을 때마다 dispatcher가 executor에 위임해 결과를 메시지로 누적하고 다시 호출한다. `tool_calls`가 없는 응답이 나오면 그 content를 ReviewResult로 파싱한다. 안전장치로 max_iterations 상한·결과 토큰 cap·HTTP 에러 graceful 처리. Engine은 PR head SHA 기준 `GitHubToolExecutor`를 만들어 주입한다. Judge pass는 손대지 않음 (1차 LLM에만 tool 제공).

**Tech Stack:** Python 3.11, OpenAI SDK (function calling, JSON output), httpx, pytest, GitHub Contents API + Code Search API.

**Build Order Rationale:**
- E1 (ToolExecutor)부터: 외부 의존(GitHub) 캡슐화 먼저, 나머지는 인터페이스만 보고 작업
- E2 (Tool schema/dispatcher): OpenAI tool 정의는 executor 인터페이스에 맞춰 결정
- E3 (GPT loop): 위 둘 위에서 loop 구현
- E4 (System prompt): LLM에게 도구 사용 지침
- E5 (Engine wiring + config): 통합
- E6 (PR #650 실호출 검증)

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/review/tool_executor.py` (new) | `ToolExecutor` 추상 + `GitHubToolExecutor` 구현 (read_file/grep) |
| `src/review/llm_tools.py` (new) | OpenAI tool JSON schema 정의 + tool_call dispatch |
| `src/review/gpt_client.py` (modify) | `review()`에 `tool_executor` 파라미터 추가, tool-use 루프 |
| `src/review/prompt_builder.py` (modify) | 시스템 프롬프트에 tool 사용 지침 추가 |
| `src/models/config.py` (modify) | `enable_tool_use: bool`, `max_tool_iterations: int`, `tool_result_token_cap: int` 추가 |
| `src/review/engine.py` (modify) | head SHA 기준 `GitHubToolExecutor` 생성, gpt_client.review 호출 시 주입 |
| `tests/test_tool_executor.py` (new) | executor 단위 테스트 |
| `tests/test_llm_tools.py` (new) | tool schema 형식 + dispatcher 단위 테스트 |
| `tests/test_gpt_client.py` (modify) | tool-use 루프 모킹 테스트 |
| `tests/test_engine.py` (modify) | 통합 — engine이 executor 만들고 주입하는지 |

---

## Phase E: Tool-use loop

### Task E1: ToolExecutor 인터페이스 + GitHubToolExecutor

**Files:**
- Create: `src/review/tool_executor.py`
- Test: `tests/test_tool_executor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tool_executor.py
import pytest
from unittest.mock import AsyncMock

from src.review.tool_executor import GitHubToolExecutor


@pytest.mark.asyncio
async def test_read_file_returns_source():
    mock_gh = AsyncMock()
    mock_gh.get_json.return_value = {
        "content": "ZGVmIGZvbygpOgogICAgcmV0dXJuIDE=\n",  # base64 of "def foo():\n    return 1"
        "encoding": "base64",
    }
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")

    src = await ex.read_file("a.py")
    assert "def foo()" in src


@pytest.mark.asyncio
async def test_read_file_returns_empty_on_404():
    import httpx

    mock_gh = AsyncMock()

    class _Resp:
        status_code = 404

    mock_gh.get_json.side_effect = httpx.HTTPStatusError(
        "not found", request=None, response=_Resp()
    )
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    assert await ex.read_file("missing.py") == ""


@pytest.mark.asyncio
async def test_grep_returns_path_matches_capped():
    mock_gh = AsyncMock()
    mock_gh.get_json.return_value = {
        "items": [
            {"path": f"src/file_{i}.py"} for i in range(30)
        ]
    }
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    matches = await ex.grep("foo")
    assert len(matches) <= 10
    assert all("path" in m for m in matches)


@pytest.mark.asyncio
async def test_grep_swallows_search_errors_returns_empty():
    mock_gh = AsyncMock()
    mock_gh.get_json.side_effect = Exception("rate limited")
    ex = GitHubToolExecutor(mock_gh, "owner/repo", "deadbeef")
    assert await ex.grep("foo") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_tool_executor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/review/tool_executor.py
import base64
import logging
from typing import Protocol
from urllib.parse import quote

from src.github.client import GitHubClient


logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    async def read_file(self, path: str) -> str: ...
    async def grep(self, pattern: str, path_glob: str | None = None) -> list[dict]: ...


class GitHubToolExecutor:
    def __init__(self, client: GitHubClient, repo: str, ref: str):
        self._client = client
        self._repo = repo
        self._ref = ref

    async def read_file(self, path: str) -> str:
        try:
            data = await self._client.get_json(
                f"/repos/{self._repo}/contents/{quote(path, safe='/')}?ref={quote(self._ref, safe='')}"
            )
        except Exception as e:
            logger.warning(f"read_file({path}) failed: {e}")
            return ""
        content = data.get("content", "")
        if data.get("encoding") == "base64":
            try:
                return base64.b64decode(content).decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"base64 decode failed for {path}: {e}")
                return ""
        return content

    async def grep(self, pattern: str, path_glob: str | None = None) -> list[dict]:
        q = f"{pattern} repo:{self._repo}"
        if path_glob:
            q += f" path:{path_glob}"
        try:
            data = await self._client.get_json(f"/search/code?q={quote(q)}")
        except Exception as e:
            logger.warning(f"grep({pattern}) failed: {e}")
            return []
        items = data.get("items", [])[:10]
        return [{"path": item["path"]} for item in items]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_tool_executor.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/review/tool_executor.py tests/test_tool_executor.py
git commit -m "feat: add GitHub-backed tool executor for LLM read_file/grep"
```

---

### Task E2: OpenAI tool schema + dispatcher

**Files:**
- Create: `src/review/llm_tools.py`
- Test: `tests/test_llm_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_tools.py
import json
import pytest
from unittest.mock import AsyncMock

from src.review.llm_tools import TOOL_SCHEMAS, dispatch_tool_call


def test_tool_schemas_include_read_file_and_grep():
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert "read_file" in names
    assert "grep" in names


def test_tool_schemas_follow_openai_format():
    for t in TOOL_SCHEMAS:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "description" in t["function"]
        assert "parameters" in t["function"]
        assert t["function"]["parameters"]["type"] == "object"


@pytest.mark.asyncio
async def test_dispatch_read_file_calls_executor():
    ex = AsyncMock()
    ex.read_file.return_value = "file body"
    out = await dispatch_tool_call(
        {"function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}},
        ex,
    )
    ex.read_file.assert_awaited_once_with("a.py")
    assert "file body" in out


@pytest.mark.asyncio
async def test_dispatch_grep_calls_executor():
    ex = AsyncMock()
    ex.grep.return_value = [{"path": "a.py"}, {"path": "b.py"}]
    out = await dispatch_tool_call(
        {"function": {"name": "grep", "arguments": json.dumps({"pattern": "foo", "path_glob": "src/**"})}},
        ex,
    )
    ex.grep.assert_awaited_once_with("foo", "src/**")
    assert "a.py" in out and "b.py" in out


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error_string():
    ex = AsyncMock()
    out = await dispatch_tool_call(
        {"function": {"name": "delete_repo", "arguments": "{}"}},
        ex,
    )
    assert "error" in out.lower() or "unknown" in out.lower()


@pytest.mark.asyncio
async def test_dispatch_truncates_oversized_result():
    ex = AsyncMock()
    ex.read_file.return_value = "x" * 100000
    out = await dispatch_tool_call(
        {"function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}},
        ex,
        max_chars=1000,
    )
    assert len(out) <= 1200  # 1000 + 짧은 truncation 안내
    assert "truncated" in out.lower() or "잘림" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_llm_tools.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement**

```python
# src/review/llm_tools.py
import json
import logging

from src.review.tool_executor import ToolExecutor


logger = logging.getLogger(__name__)


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Fetch the full text of a file at the PR head commit. "
                "Use when you need to inspect the body of a function or class referenced in the diff. "
                "Returns the file content as a string (truncated if very large)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative path, e.g. 'src/foo/bar.py'",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search the repo for files matching a code pattern. "
                "Use to locate where a symbol is defined when the file path is unknown. "
                "Returns up to 10 matches as {path} entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Code pattern to search for (e.g. function or class name)",
                    },
                    "path_glob": {
                        "type": "string",
                        "description": "Optional path glob filter, e.g. 'src/**' or '*.ts'",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]


async def dispatch_tool_call(
    tool_call: dict,
    executor: ToolExecutor,
    max_chars: int = 12000,
) -> str:
    name = tool_call["function"]["name"]
    try:
        args = json.loads(tool_call["function"]["arguments"] or "{}")
    except json.JSONDecodeError as e:
        return f"error: invalid arguments JSON: {e}"

    try:
        if name == "read_file":
            result = await executor.read_file(args["path"])
            return _truncate(result, max_chars)
        if name == "grep":
            matches = await executor.grep(args["pattern"], args.get("path_glob"))
            return _truncate(json.dumps(matches, ensure_ascii=False), max_chars)
    except KeyError as e:
        return f"error: missing argument {e}"
    except Exception as e:
        logger.warning(f"tool {name} raised: {e}")
        return f"error: {e}"

    return f"error: unknown tool '{name}'"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n…(잘림: {len(text) - max_chars} chars truncated)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_llm_tools.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/review/llm_tools.py tests/test_llm_tools.py
git commit -m "feat: define OpenAI tool schemas and dispatcher for read_file/grep"
```

---

### Task E3: GPTClient tool-use 루프

**Files:**
- Modify: `src/review/gpt_client.py`
- Modify: `tests/test_gpt_client.py`

- [ ] **Step 1: Inspect existing GPTClient**

Run: `cat /Users/kyungjuchoi/Projects/syscon-review-bot/src/review/gpt_client.py`

확인: 현재 `review(system, user, model=None)` 시그니처. response_format = json_object. tool_choice 미사용.

- [ ] **Step 2: Write failing tests**

Add to `tests/test_gpt_client.py`:

```python
import json
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.review.gpt_client import GPTClient


def _mock_msg(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _mock_tool_call(id_, name, args):
    func = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=id_, type="function", function=func)


@pytest.mark.asyncio
async def test_tool_use_loop_dispatches_then_returns_final():
    gpt = GPTClient(api_key="x")
    call_counter = {"n": 0}

    async def fake_create(**kwargs):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            tc = _mock_tool_call("c1", "read_file", {"path": "a.py"})
            return _mock_msg(content=None, tool_calls=[tc])
        return _mock_msg(content=json.dumps({
            "spec_status": "present",
            "aligned": True,
            "summary": "ok",
        }))

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    executor = AsyncMock()
    executor.read_file.return_value = "file body"

    result = await gpt.review("sys", "usr", tool_executor=executor)

    assert call_counter["n"] == 2
    executor.read_file.assert_awaited_once_with("a.py")
    assert result.summary == "ok"


@pytest.mark.asyncio
async def test_tool_use_loop_respects_max_iterations():
    gpt = GPTClient(api_key="x")

    async def always_tool(**kwargs):
        tc = _mock_tool_call("c1", "read_file", {"path": "a.py"})
        return _mock_msg(content=None, tool_calls=[tc])

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=always_tool)

    executor = AsyncMock()
    executor.read_file.return_value = "x"

    with pytest.raises(ValueError, match="max_tool_iterations"):
        await gpt.review("sys", "usr", tool_executor=executor, max_tool_iterations=3)

    assert gpt._client.chat.completions.create.await_count == 3


@pytest.mark.asyncio
async def test_review_without_tool_executor_keeps_old_behavior():
    gpt = GPTClient(api_key="x")

    async def respond_json(**kwargs):
        # 도구 없이 호출되면 tools 인자가 전달되지 않아야 함
        assert "tools" not in kwargs
        return _mock_msg(content=json.dumps({
            "spec_status": "present", "aligned": True, "summary": "ok",
        }))

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=respond_json)

    result = await gpt.review("sys", "usr")
    assert result.summary == "ok"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_gpt_client.py -k "tool_use_loop or without_tool_executor" -v`
Expected: FAIL (`review` doesn't accept tool_executor / no loop)

- [ ] **Step 4: Implement tool-use loop**

Modify `src/review/gpt_client.py`:

```python
import json

import openai
from openai import AsyncOpenAI
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.models.review import ReviewResult
from src.review.llm_tools import TOOL_SCHEMAS, dispatch_tool_call
from src.review.tool_executor import ToolExecutor


RETRYABLE_OPENAI_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class GPTClient:
    def __init__(self, api_key: str, model: str = "gpt-5.4-mini"):
        self._client = AsyncOpenAI(api_key=api_key)
        self._default_model = model

    @retry(
        retry=retry_if_exception_type(RETRYABLE_OPENAI_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _call_openai(self, **kwargs):
        return await self._client.chat.completions.create(**kwargs)

    async def review(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        tool_executor: ToolExecutor | None = None,
        max_tool_iterations: int = 8,
    ) -> ReviewResult:
        chosen_model = model or self._default_model
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if tool_executor is None:
            response = await self._call_openai(
                model=chosen_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            return self._parse(response.choices[0].message.content)

        for _ in range(max_tool_iterations):
            response = await self._call_openai(
                model=chosen_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
            msg = response.choices[0].message
            if not getattr(msg, "tool_calls", None):
                return self._parse(msg.content)

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                result_text = await dispatch_tool_call(
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}},
                    tool_executor,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        raise ValueError(
            f"GPT exhausted max_tool_iterations={max_tool_iterations} without producing a final response"
        )

    def _parse(self, content: str) -> ReviewResult:
        try:
            data = json.loads(content)
            return ReviewResult(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"Failed to parse GPT response: {e}\nContent: {content}")
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/ -q`
Expected: ALL PASS. 기존 tests/test_gpt_client.py 가 `_call_openai` 호출 형태에 의존하면 mock 조정 필요할 수 있음. 우선 실행해보고 깨진 것만 surgical fix.

- [ ] **Step 6: Commit**

```bash
git add src/review/gpt_client.py tests/test_gpt_client.py
git commit -m "feat: tool-use loop in GPTClient.review with read_file/grep"
```

---

### Task E4: 시스템 프롬프트에 tool 사용 지침 추가

**Files:**
- Modify: `src/review/prompt_builder.py`
- Modify: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_prompt_builder.py (추가)
from src.review.prompt_builder import build_system_prompt

def test_system_prompt_mentions_tool_usage_guidance():
    s = build_system_prompt()
    assert "read_file" in s
    assert "grep" in s
    # 핵심 휴리스틱: 호출 시그니처만 보고 단정 금지
    assert "정의" in s or "본문" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_prompt_builder.py -k tool_usage -v`
Expected: FAIL

- [ ] **Step 3: Add a tool guidance section to SYSTEM_PROMPT**

`src/review/prompt_builder.py`의 `SYSTEM_PROMPT` 안 — `## 검토 순서` 위, `## 재리뷰 절차` 아래에 다음 섹션을 삽입:

```
## 도구 사용 지침

너에게는 두 개의 도구가 주어진다:
- `read_file(path)`: 파일 전체 텍스트를 PR head 시점으로 fetch
- `grep(pattern, path_glob?)`: 패턴과 일치하는 파일 경로를 최대 10개 반환

다음 경우 도구를 **반드시** 사용한다:
1. diff에서 호출만 보이는 함수·메서드의 동작을 의심해 bug/mismatch를 적으려고 할 때 → 정의 파일을 `grep`으로 찾고 `read_file`로 본문 확인. 본문이 인자를 실제로 사용하는지, 부작용이 있는지 직접 검증.
2. 변경 파일이 import한 다른 모듈의 시그니처·상수 값을 알아야 판정이 가능한 경우.
3. 스펙(`docs/specs/*` 등) 본문 일부가 diff에 포함되지 않았으나 PR이 참조하는 경우.

도구를 쓰지 않고 호출 시그니처·식별자명만으로 추론해 bug/mismatch를 단정하면 안 된다. 추론한 위반이 정의 본문에서 실제로 발생하는지 확인 후에만 finding으로 등록한다.

도구 호출 결과가 비어 있거나 에러("error: …")면 그 사실 자체를 finding의 근거로 삼지 말고, 보수적으로 finding을 등록하지 않는다.
```

- [ ] **Step 4: Run test**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_prompt_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat: instruct LLM to verify call semantics via read_file/grep before flagging"
```

---

### Task E5: Engine wiring + config flag

**Files:**
- Modify: `src/models/config.py`
- Modify: `src/review/engine.py`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Add config fields**

`src/models/config.py`의 `ReviewConfig`에 추가:

```python
    enable_tool_use: bool = True
    max_tool_iterations: int = 8
```

- [ ] **Step 2: Write failing tests**

Add to `tests/test_engine.py`:

```python
@pytest.mark.asyncio
async def test_review_pr_creates_tool_executor_when_enabled(context, aligned_result):
    captured = {}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8):
        captured["tool_executor"] = tool_executor
        captured["max_tool_iterations"] = max_tool_iterations
        return aligned_result

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_tool_use=True, max_tool_iterations=5)), \
         _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    assert captured["tool_executor"] is not None
    # executor의 read_file/grep 메서드가 노출돼야 함 (덕 타이핑 검증)
    assert hasattr(captured["tool_executor"], "read_file")
    assert hasattr(captured["tool_executor"], "grep")
    assert captured["max_tool_iterations"] == 5


@pytest.mark.asyncio
async def test_review_pr_omits_tool_executor_when_disabled(context, aligned_result):
    captured = {}
    async def fake_review(system, user, model=None, tool_executor=None, max_tool_iterations=8):
        captured["tool_executor"] = tool_executor
        return aligned_result

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_tool_use=False)), \
         _NO_EXPAND:
        await review_pr(context, mock_github, mock_gpt)

    assert captured["tool_executor"] is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_engine.py -k "tool_executor" -v`
Expected: FAIL

- [ ] **Step 4: Wire executor in engine**

`src/review/engine.py` 수정:

```python
# 상단 import 추가
from src.review.tool_executor import GitHubToolExecutor

# review_pr 안, gpt_client.review 호출 부분 변경
head_sha = pr_info["head"]["sha"]
# (이미 hunk expansion에 head_sha 사용 중)

executor = None
if config.enable_tool_use:
    executor = GitHubToolExecutor(github_client, context.repo, head_sha)

result = await gpt_client.review(
    system_prompt,
    user_prompt,
    model=chosen_model,
    tool_executor=executor,
    max_tool_iterations=config.max_tool_iterations,
)
if config.enable_judge:
    result = await run_judge(gpt_client, result, model=chosen_model)
```

기존 `gpt_client.review(...)` 호출은 위 형태로 교체.

- [ ] **Step 5: Run all tests**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/ -q`
Expected: ALL PASS. 기존 engine 테스트들이 `mock_gpt.review`에 `tool_executor=...` keyword arg가 전달돼도 깨지지 않는지 확인. AsyncMock은 추가 kwargs를 무시하므로 일반적으로 통과.

만약 `aligned_result` 픽스처를 쓰는 테스트가 `mock_gpt.review.return_value = aligned_result` 식이면 그대로 작동. side_effect 쓰는 테스트의 fake_review 시그니처에 `tool_executor=None, max_tool_iterations=8`도 추가해야 할 수 있음. 깨진 것만 수정.

- [ ] **Step 6: Commit**

```bash
git add src/review/engine.py src/models/config.py tests/test_engine.py
git commit -m "feat: wire GitHubToolExecutor into engine, gated by enable_tool_use"
```

---

### Task E6: Config YAML 키 노출

**Files:**
- Modify: `src/review/config_loader.py` (필요 시)
- Modify: `tests/test_config_loader.py`

- [ ] **Step 1: Inspect loader**

Run: `grep -n "enable_judge\|token_budget\|max_expand_lines" /Users/kyungjuchoi/Projects/syscon-review-bot/src/review/config_loader.py`

확인: 기존 loader가 `enable_judge` 등 새 키를 어떻게 처리하는지. 동일 패턴으로 `enable_tool_use`, `max_tool_iterations` 추가.

- [ ] **Step 2: Write failing test**

```python
# tests/test_config_loader.py (추가)
def test_loads_tool_use_keys():
    yaml_text = """
enable_tool_use: false
max_tool_iterations: 4
"""
    cfg = load_config_from_yaml(yaml_text)
    assert cfg.enable_tool_use is False
    assert cfg.max_tool_iterations == 4
```

- [ ] **Step 3: Run test**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_config_loader.py -k tool_use -v`

- [ ] **Step 4: Add keys to loader if needed**

기존 loader가 명시 매핑이면 두 키 추가. Pydantic 자동 처리면 skip.

- [ ] **Step 5: Run full suite**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/ -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/review/config_loader.py tests/test_config_loader.py
git commit -m "feat: expose enable_tool_use and max_tool_iterations via repo config"
```

---

### Task F2: PR #650 실호출 검증 (수동)

- [ ] **Step 1: Run against PR #650**

```bash
cd /Users/kyungjuchoi/Projects/syscon-review-bot
unset GITHUB_TOKEN; T=$(gh auth token); set -a && source .env && set +a && export GITHUB_TOKEN=$T
.venv/bin/python -c "
import asyncio, json, os
from src.github.client import GitHubClient
from src.github.pr import get_pr_diff, get_pr_info, get_pr_reviews, get_pr_issue_comments, get_pr_review_comments
from src.github.reviewer import filter_bot_reviews, format_review_body
from src.review.diff_parser import parse_diff, filter_files
from src.review.prompt_builder import build_system_prompt, build_user_prompt
from src.review.engine import _build_conversation_history, _expand_files
from src.review.compressor import compress_files
from src.review.gpt_client import GPTClient
from src.review.tool_executor import GitHubToolExecutor
from src.models.config import ReviewConfig

async def main():
    gh = GitHubClient(token=os.environ['GITHUB_TOKEN'])
    repo = 'sr-amr-acs-dev/sarics_nx'
    pr_num = 650
    pr_info = await get_pr_info(gh, repo, pr_num)
    diff_text = await get_pr_diff(gh, repo, pr_num)
    files = parse_diff(diff_text)
    cfg = ReviewConfig(enable_tool_use=True, enable_judge=False)
    filtered = filter_files(files, cfg.ignore)
    head_sha = pr_info['head']['sha']
    filtered = await _expand_files(gh, repo, head_sha, filtered, cfg.max_expand_lines)
    filtered, dropped = compress_files(filtered, cfg.token_budget)
    raw_reviews = await get_pr_reviews(gh, repo, pr_num)
    bot_reviews = filter_bot_reviews(raw_reviews)
    bot_logins = {(r.get('user') or {}).get('login') for r in bot_reviews if (r.get('user') or {}).get('login')}
    issue_comments = await get_pr_issue_comments(gh, repo, pr_num)
    review_comments = await get_pr_review_comments(gh, repo, pr_num)
    conv = _build_conversation_history(bot_reviews, issue_comments, review_comments, bot_logins)
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(
        files=filtered, pr_title=pr_info['title'], pr_body=pr_info.get('body') or '',
        base_branch=pr_info['base']['ref'], head_branch=pr_info['head']['ref'],
        conversation_history=conv, dropped_paths=dropped,
    )
    gpt = GPTClient(api_key=os.environ['OPENAI_API_KEY'])
    executor = GitHubToolExecutor(gh, repo, head_sha)
    result = await gpt.review(system_prompt, user_prompt, tool_executor=executor, max_tool_iterations=cfg.max_tool_iterations)
    print('=== JSON ===')
    print(json.dumps(json.loads(result.model_dump_json()), indent=2, ensure_ascii=False))
    print()
    print('=== RENDERED ===')
    print(format_review_body(result))
    await gh.close()

asyncio.run(main())
"
```

- [ ] **Step 2: Verify expected behavior**

기대 결과:
- `getWaypointNode(port.direction)` 관련 mismatches/quality_findings가 사라지거나 description이 "인자 미사용 확인됨, 동작 무관"으로 바뀐다 (LLM이 `read_file`로 정의 본문 확인 결과).
- `includeStationWaypoint` 필드 초기값 mismatch도 사라진다 (LLM이 생성자 본문 확인).
- prior_resolved 부분 해결은 그대로 (해결된 항목 아님).

기대대로 안 나오면:
- LLM이 도구 호출 안 함 → 시스템 프롬프트 강화 (Task E4 본문 더 단호하게)
- 호출은 했지만 결과 무시 → 도구 결과 후 등록한 finding 검증 단계 추가

- [ ] **Step 3: 결과 사용자에게 보고**

---

## Self-Review Notes

- E1: `GitHubToolExecutor.read_file`이 `get_repo_file`과 거의 동일 — 중복? 차이는 (a) 에러 시 빈 문자열 반환 (executor는 LLM tool용이라 에러도 graceful), (b) base64 decode 인라인. `get_repo_file` 재사용도 가능하나, tool은 다른 에러 정책이라 분리 유지.
- E3: 기존 `test_gpt_client.py`의 mock이 `self._client.chat.completions.create` 형태에 의존하면 그대로 작동. retry 데코레이터를 `_call_openai`로 이동했으므로 retry 테스트 시그니처 미세 조정 필요할 수 있음 — 실행해보고 surgical fix.
- E5: `head_sha` 추출은 이미 Phase A 코드에 있음. 재사용.
- 비용: PR당 LLM 호출 1회 + tool 호출 N회 + tool 결과 토큰. PR #650 같은 케이스에서 LLM이 2-5회 read_file을 부를 것으로 예상 → 토큰 +10-30k. 비용 +$0.02 수준.
- GitHub Code Search rate limit 10 req/min — `grep` 남용 시 hit 가능. `max_tool_iterations=8`이 자연 가드. 추가 보호 필요하면 후속 작업.
- 보안: tool은 read-only. 위험한 작업 없음. `delete_repo` 같은 hallucinated tool은 dispatcher에서 "unknown" 반환.
