# PR Review Quality Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR-Agent OSS 접근을 차용해 봇 리뷰의 false-positive 감소·재리뷰 모순 제거. 옵션 1 (Judge pass) + 옵션 2 (Dynamic hunk expansion) + 옵션 3 (PR compression) 구현.

**Architecture:** 엔진 파이프라인을 `fetch diff → parse → EXPAND → COMPRESS → build prompt → LLM → JUDGE → submit`으로 확장. 세 단계 모두 기존 단일 호출 흐름을 유지하며 부수적 추가. Judge는 1회 추가 LLM 호출, Expand는 변경 파일 1회 fetch + 정규식 헤더 탐색, Compress는 토큰 예산 기반 파일 단위 drop.

**Tech Stack:** Python 3.11, Pydantic v2, httpx, OpenAI SDK, tiktoken (신규 의존성), pytest.

**Build Order Rationale:**
- Phase A (Hunk Expansion, option 2) 먼저 — PR #650의 주된 false positive (impl 트레이스 부재) 직접 해결. 가장 가시적 효과.
- Phase B (Compression, option 3) 둘째 — Phase A가 늘린 토큰을 받쳐주는 안전망. 큰 PR에서 budget 초과 방지.
- Phase C (Judge, option 1) 셋째 — Phase A·B의 출력을 LLM이 1차 생성한 뒤 self-reflection 호출로 prior_resolved 모순·prefix 누락·aligned 룰 위반 정리.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/review/hunk_expander.py` (new) | FileDiff hunk를 backward로 enclosing function/class까지 확장 |
| `src/review/language_patterns.py` (new) | 언어별 함수/클래스 헤더 정규식 (Python, JS/TS, Svelte, 기타) |
| `src/review/compressor.py` (new) | tiktoken 토큰 카운트 기반 파일 drop |
| `src/review/judge.py` (new) | 1차 ReviewResult를 self-reflection으로 재정렬 |
| `src/review/judge_prompt.py` (new) | Judge 시스템 프롬프트 |
| `src/review/engine.py` (modify) | EXPAND → COMPRESS → JUDGE wiring |
| `src/models/config.py` (modify) | `enable_judge`, `token_budget`, `max_expand_lines` 필드 추가 |
| `requirements.txt` (modify) | tiktoken 추가 |
| `tests/test_hunk_expander.py` (new) | 헤더 탐색·확장 단위 테스트 |
| `tests/test_compressor.py` (new) | 토큰 예산·파일 drop 단위 테스트 |
| `tests/test_judge.py` (new) | judge 호출·모순 제거 테스트 |
| `tests/test_engine.py` (modify) | 통합 흐름 회귀 |

---

## Phase A: Dynamic Hunk Expansion (옵션 2)

### Task A1: 언어별 헤더 정규식

**Files:**
- Create: `src/review/language_patterns.py`
- Test: `tests/test_language_patterns.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_language_patterns.py
from src.review.language_patterns import detect_language, find_header_lines

def test_detect_language_by_extension():
    assert detect_language("a.py") == "python"
    assert detect_language("b.ts") == "typescript"
    assert detect_language("c.tsx") == "typescript"
    assert detect_language("d.svelte") == "svelte"
    assert detect_language("e.unknown") == "generic"

def test_find_python_headers():
    src = "x = 1\ndef foo():\n    return 1\nclass Bar:\n    pass\n"
    assert find_header_lines(src, "python") == [2, 4]

def test_find_typescript_headers():
    src = "import x\nfunction a() {}\nclass B {}\nconst c = () => 1\nexport function d() {}\n"
    assert find_header_lines(src, "typescript") == [2, 3, 4, 5]

def test_find_svelte_headers_includes_script_and_functions():
    src = "<script lang=\"ts\">\nfunction toggle() {}\n</script>\n<div>hi</div>\n"
    assert 2 in find_header_lines(src, "svelte")

def test_generic_falls_back_to_common_patterns():
    src = "def x():\n  pass\nfunction y() {}\n"
    headers = find_header_lines(src, "generic")
    assert 1 in headers and 3 in headers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_language_patterns.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.review.language_patterns'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/review/language_patterns.py
import re

_EXT_TO_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".svelte": "svelte",
}

_PATTERNS = {
    "python": [
        re.compile(r"^\s*(def |async def |class )"),
    ],
    "typescript": [
        re.compile(r"^\s*(export\s+)?(async\s+)?function\s+\w+"),
        re.compile(r"^\s*(export\s+)?class\s+\w+"),
        re.compile(r"^\s*(export\s+)?const\s+\w+\s*[:=]"),
        re.compile(r"^\s*(public|private|protected)?\s*(async\s+)?\w+\s*\([^)]*\)\s*[:{]"),
    ],
    "svelte": [
        re.compile(r"^\s*<script"),
        re.compile(r"^\s*function\s+\w+"),
        re.compile(r"^\s*const\s+\w+\s*[:=]"),
    ],
    "generic": [
        re.compile(r"^\s*(def |class |function |export\s+(function|class)|async\s+function)"),
    ],
}


def detect_language(path: str) -> str:
    for ext, lang in _EXT_TO_LANG.items():
        if path.endswith(ext):
            return lang
    return "generic"


def find_header_lines(source: str, language: str) -> list[int]:
    patterns = _PATTERNS.get(language, _PATTERNS["generic"])
    headers: list[int] = []
    for idx, line in enumerate(source.split("\n"), start=1):
        for pat in patterns:
            if pat.match(line):
                headers.append(idx)
                break
    return headers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_language_patterns.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/review/language_patterns.py tests/test_language_patterns.py
git commit -m "feat: add language-aware header detection for hunk expansion"
```

---

### Task A2: Hunk Expander 단위 로직

**Files:**
- Create: `src/review/hunk_expander.py`
- Test: `tests/test_hunk_expander.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hunk_expander.py
from src.review.hunk_expander import expand_hunk_to_header

PY_FILE = "\n".join([
    "x = 1",                  # 1
    "",                       # 2
    "def calc(a, b):",        # 3
    "    total = a + b",      # 4
    "    extra = total * 2",  # 5
    "    return extra",       # 6
    "",                       # 7
    "def other():",           # 8
    "    return 0",           # 9
])


def test_expand_to_enclosing_function():
    # hunk starts at line 6 in file; we want lines 3..6 included
    expanded = expand_hunk_to_header(
        full_source=PY_FILE,
        hunk_start_line=6,
        hunk_end_line=6,
        language="python",
        max_lines=20,
    )
    assert expanded.start_line == 3
    assert expanded.end_line == 6
    assert "def calc" in expanded.text
    assert "return extra" in expanded.text


def test_no_expansion_when_no_header_above():
    expanded = expand_hunk_to_header(
        full_source=PY_FILE,
        hunk_start_line=1,
        hunk_end_line=1,
        language="python",
        max_lines=20,
    )
    assert expanded.start_line == 1
    assert "x = 1" in expanded.text


def test_max_lines_caps_search_range():
    # If header is too far up, fall back to hunk start
    long_src = "x = 0\n" * 100 + "def deep():\n    return 1\n"
    # hunk at last line (line 102); header at line 101; within range -> include
    expanded = expand_hunk_to_header(
        full_source=long_src,
        hunk_start_line=102,
        hunk_end_line=102,
        language="python",
        max_lines=5,
    )
    assert expanded.start_line == 101

    # hunk in middle (line 50), no header within 5 lines back -> no expansion
    expanded2 = expand_hunk_to_header(
        full_source=long_src,
        hunk_start_line=50,
        hunk_end_line=50,
        language="python",
        max_lines=5,
    )
    assert expanded2.start_line == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hunk_expander.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/review/hunk_expander.py
from dataclasses import dataclass

from src.review.language_patterns import find_header_lines


@dataclass
class ExpandedHunk:
    start_line: int
    end_line: int
    text: str


def expand_hunk_to_header(
    full_source: str,
    hunk_start_line: int,
    hunk_end_line: int,
    language: str,
    max_lines: int,
) -> ExpandedHunk:
    lines = full_source.split("\n")
    headers = find_header_lines(full_source, language)

    candidate_headers = [h for h in headers if h < hunk_start_line and (hunk_start_line - h) <= max_lines]
    new_start = max(candidate_headers) if candidate_headers else hunk_start_line

    selected = lines[new_start - 1 : hunk_end_line]
    return ExpandedHunk(start_line=new_start, end_line=hunk_end_line, text="\n".join(selected))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hunk_expander.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/review/hunk_expander.py tests/test_hunk_expander.py
git commit -m "feat: backward-expand hunks to enclosing function header"
```

---

### Task A3: FileDiff 통합 — 변경 파일 전체 fetch + 모든 hunk 확장

**Files:**
- Modify: `src/review/hunk_expander.py`
- Modify: `src/review/diff_parser.py` (need to expose hunk line ranges)
- Test: `tests/test_hunk_expander.py`

- [ ] **Step 1: Inspect existing FileDiff/parse_diff**

Run: `grep -n "class FileDiff\|def parse_diff\|@@" src/review/diff_parser.py`

확인 사항: FileDiff에 hunk별 시작/끝 라인 정보가 있는지. 없으면 patch 텍스트에서 `@@ -<old> +<new> @@` 헤더 파싱 필요.

- [ ] **Step 2: Write failing test for FileDiff expansion**

```python
# tests/test_hunk_expander.py (추가)
from src.review.diff_parser import FileDiff
from src.review.hunk_expander import expand_file_diff

PY_FILE_FULL = "\n".join([
    "import os",                # 1
    "",                         # 2
    "def helper():",            # 3
    "    return 1",             # 4
    "",                         # 5
    "def main():",              # 6
    "    x = helper()",         # 7
    "    y = x + 1",            # 8
    "    return y",             # 9
])


def test_expand_file_diff_includes_function_headers():
    # hunk modifies line 8 only
    patch = "@@ -8,1 +8,1 @@\n-    y = x + 1\n+    y = x + 2\n"
    fd = FileDiff(path="a.py", additions=1, deletions=1, patch=patch)
    expanded = expand_file_diff(fd, full_source=PY_FILE_FULL, max_lines=20)
    assert "def main():" in expanded.patch
    assert "    x = helper()" in expanded.patch
    assert "y = x + 2" in expanded.patch
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_hunk_expander.py::test_expand_file_diff_includes_function_headers -v`
Expected: FAIL (function not defined)

- [ ] **Step 4: Implement `expand_file_diff`**

```python
# src/review/hunk_expander.py (추가)
import re

from src.review.diff_parser import FileDiff
from src.review.language_patterns import detect_language

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_hunks(patch: str) -> list[tuple[int, int, str]]:
    """[(new_start, new_lines, hunk_body), ...]"""
    hunks: list[tuple[int, int, str]] = []
    cur_start = cur_lines = None
    cur_body: list[str] = []
    for line in patch.split("\n"):
        m = _HUNK_HEADER_RE.match(line)
        if m:
            if cur_start is not None:
                hunks.append((cur_start, cur_lines or 0, "\n".join(cur_body)))
            cur_start = int(m.group(1))
            cur_lines = int(m.group(2) or "1")
            cur_body = []
        elif cur_start is not None:
            cur_body.append(line)
    if cur_start is not None:
        hunks.append((cur_start, cur_lines or 0, "\n".join(cur_body)))
    return hunks


def expand_file_diff(fd: FileDiff, full_source: str, max_lines: int) -> FileDiff:
    language = detect_language(fd.path)
    file_lines = full_source.split("\n")
    hunks = _parse_hunks(fd.patch)
    if not hunks:
        return fd

    new_parts: list[str] = []
    for new_start, new_lines, body in hunks:
        end_line = new_start + max(new_lines - 1, 0)
        expanded = expand_hunk_to_header(
            full_source=full_source,
            hunk_start_line=new_start,
            hunk_end_line=end_line,
            language=language,
            max_lines=max_lines,
        )
        prefix_lines = file_lines[expanded.start_line - 1 : new_start - 1]
        prefix = "\n".join(" " + line for line in prefix_lines)
        header = f"@@ -{new_start},{new_lines} +{new_start},{new_lines} @@"
        new_parts.append(header)
        if prefix:
            new_parts.append(prefix)
        new_parts.append(body)

    return FileDiff(
        path=fd.path,
        additions=fd.additions,
        deletions=fd.deletions,
        patch="\n".join(new_parts),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_hunk_expander.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/review/hunk_expander.py tests/test_hunk_expander.py
git commit -m "feat: expand multi-hunk FileDiff patches with surrounding function context"
```

---

### Task A4: Engine wiring — 변경 파일 fetch + 확장 호출

**Files:**
- Modify: `src/review/engine.py`
- Modify: `src/models/config.py`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Add `max_expand_lines` to ReviewConfig**

```python
# src/models/config.py 수정 (필드 추가)
class ReviewConfig(BaseModel):
    # ... 기존 필드 ...
    max_expand_lines: int = 50  # backward search cap for hunk expansion
```

- [ ] **Step 2: Write failing engine test**

```python
# tests/test_engine.py (추가)
@pytest.mark.asyncio
async def test_review_pr_expands_hunks_using_head_file_content(context, aligned_result):
    """엔진이 변경 파일을 head SHA로 fetch해서 hunk 확장 후 LLM에 전달."""
    full_source = "\n".join([
        "x = 1",
        "def helper():",
        "    return 1",
        "def main():",
        "    y = helper()",
        "    return y + 1",
    ])
    diff = (
        "diff --git a/a.py b/a.py\n"
        "@@ -6,1 +6,1 @@\n"
        "-    return y\n"
        "+    return y + 1\n"
    )

    captured = {}
    async def fake_review(system, user, model=None):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(diff=diff)
    # get_repo_file이 full source를 돌려주도록 클라이언트 모킹 확장
    mock_github.get_json.side_effect = make_get_json_dispatch()
    mock_github.get.side_effect = [
        diff,  # diff fetch
        # get_repo_file은 base64 dict 형태가 아니라 get_json 사용 → 별도 패치 필요
    ]

    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig()), \
         patch("src.review.engine.get_repo_file", new_callable=AsyncMock, return_value=full_source):
        await review_pr(context, mock_github, mock_gpt)

    assert "def main()" in captured["user"]
    assert "y = helper()" in captured["user"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_engine.py::test_review_pr_expands_hunks_using_head_file_content -v`
Expected: FAIL (확장 안 됨)

- [ ] **Step 4: Wire expander in engine**

```python
# src/review/engine.py 수정
from src.github.pr import get_repo_file  # 이미 있으면 그대로
from src.review.hunk_expander import expand_file_diff

# review_pr 함수 내, filtered 계산 후 prompt build 전:
async def _expand_files(github_client, repo, head_sha, files, max_lines):
    expanded: list = []
    for f in files:
        source = await get_repo_file(github_client, repo, f.path, head_sha)
        if source is None:
            expanded.append(f)
            continue
        expanded.append(expand_file_diff(f, full_source=source, max_lines=max_lines))
    return expanded

# review_pr 본문에 추가
head_sha = pr_info["head"]["sha"]
filtered = await _expand_files(
    github_client, context.repo, head_sha, filtered, config.max_expand_lines
)
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS (모든 회귀 포함)

- [ ] **Step 6: Commit**

```bash
git add src/review/engine.py src/models/config.py tests/test_engine.py
git commit -m "feat: fetch head file content and expand hunks before LLM review"
```

---

## Phase B: PR Compression (옵션 3)

### Task B1: tiktoken 의존성 추가 + 토큰 카운터

**Files:**
- Modify: `requirements.txt`
- Create: `src/review/token_counter.py`
- Test: `tests/test_token_counter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_token_counter.py
from src.review.token_counter import count_tokens

def test_counts_simple_text():
    n = count_tokens("hello world")
    assert n > 0 and n < 10

def test_counts_korean_text():
    n = count_tokens("안녕하세요 토큰 수 측정")
    assert n > 5

def test_counts_empty_string():
    assert count_tokens("") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_token_counter.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Add tiktoken**

```bash
# requirements.txt에 추가
echo "tiktoken>=0.7.0" >> requirements.txt
.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 4: Implement counter**

```python
# src/review/token_counter.py
import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENC.encode(text))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_token_counter.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/review/token_counter.py tests/test_token_counter.py
git commit -m "feat: add tiktoken-based token counter for compression budget"
```

---

### Task B2: Compressor — 토큰 예산 기반 파일 drop

**Files:**
- Create: `src/review/compressor.py`
- Test: `tests/test_compressor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_compressor.py
from src.review.compressor import compress_files
from src.review.diff_parser import FileDiff


def _fd(path, size):
    patch = "@@ -1,1 +1,1 @@\n" + ("a" * size)
    return FileDiff(path=path, additions=1, deletions=0, patch=patch)


def test_keeps_all_when_under_budget():
    files = [_fd("a.py", 100), _fd("b.py", 100)]
    kept, dropped = compress_files(files, budget_tokens=1000)
    assert len(kept) == 2
    assert dropped == []


def test_drops_largest_files_first_until_under_budget():
    files = [_fd("small.py", 50), _fd("huge.py", 5000), _fd("medium.py", 500)]
    kept, dropped = compress_files(files, budget_tokens=200)
    kept_paths = [f.path for f in kept]
    # huge가 가장 먼저 drop, medium도 drop
    assert "huge.py" in dropped
    assert "small.py" in kept_paths


def test_dropped_paths_in_order_of_size_desc():
    files = [_fd("a.py", 1000), _fd("b.py", 2000), _fd("c.py", 3000)]
    _, dropped = compress_files(files, budget_tokens=100)
    assert dropped == ["c.py", "b.py", "a.py"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compressor.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement compressor**

```python
# src/review/compressor.py
from src.review.diff_parser import FileDiff
from src.review.token_counter import count_tokens


def compress_files(
    files: list[FileDiff],
    budget_tokens: int,
) -> tuple[list[FileDiff], list[str]]:
    """예산 초과 시 가장 큰 파일부터 drop. 반환: (남은 파일, drop된 경로 목록)."""
    sized = [(count_tokens(f.patch), f) for f in files]
    total = sum(t for t, _ in sized)
    if total <= budget_tokens:
        return [f for _, f in sized], []

    sized_desc = sorted(sized, key=lambda x: x[0], reverse=True)
    dropped: list[str] = []
    kept: list[FileDiff] = []
    remaining = total
    for tokens, f in sized_desc:
        if remaining > budget_tokens:
            dropped.append(f.path)
            remaining -= tokens
        else:
            kept.append(f)
    return kept, dropped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compressor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/review/compressor.py tests/test_compressor.py
git commit -m "feat: drop largest files first when token budget exceeded"
```

---

### Task B3: Engine wiring — Compression 단계 + 기존 500줄 truncation 제거

**Files:**
- Modify: `src/review/engine.py`
- Modify: `src/review/prompt_builder.py`
- Modify: `src/models/config.py`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Add token_budget to ReviewConfig**

```python
# src/models/config.py
class ReviewConfig(BaseModel):
    # ... 기존 ...
    token_budget: int = 60000  # gpt-5.4-mini context ~128k, leave room for prompt+response
```

- [ ] **Step 2: Write failing engine test**

```python
# tests/test_engine.py (추가)
@pytest.mark.asyncio
async def test_review_pr_drops_oversized_files_and_notes_skipped(context, aligned_result):
    huge = "a" * 250000  # ~60k tokens
    diff = (
        "diff --git a/huge.py b/huge.py\n"
        f"@@ -1,1 +1,1 @@\n+{huge}\n"
        "diff --git a/small.py b/small.py\n"
        "@@ -1,1 +1,1 @@\n+ok\n"
    )

    captured = {}
    async def fake_review(system, user, model=None):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(diff=diff)
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(token_budget=5000)), \
         patch("src.review.engine.get_repo_file", new_callable=AsyncMock, return_value=None):
        await review_pr(context, mock_github, mock_gpt)

    # huge.py drop, small.py 유지
    assert "small.py" in captured["user"]
    assert "huge.py" not in captured["user"] or "토큰 예산" in captured["user"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_engine.py::test_review_pr_drops_oversized_files_and_notes_skipped -v`
Expected: FAIL

- [ ] **Step 4: Wire compressor in engine**

```python
# src/review/engine.py 수정
from src.review.compressor import compress_files

# expand 후, prompt build 전:
filtered, dropped_paths = compress_files(filtered, config.token_budget)
```

- [ ] **Step 5: Pass dropped list to prompt_builder, surface in prompt**

```python
# src/review/prompt_builder.py 수정 (build_user_prompt 시그니처에 dropped_paths 추가)
def build_user_prompt(
    files: list[FileDiff],
    pr_title: str,
    pr_body: str,
    base_branch: str,
    head_branch: str,
    conversation_history: list[str] | None = None,
    dropped_paths: list[str] | None = None,
) -> str:
    # ... 기존 ...
    if dropped_paths:
        parts.append("")
        parts.append("## 토큰 예산 초과로 제외된 파일")
        for p in dropped_paths:
            parts.append(f"- {p}")
        parts.append("(이 파일들은 변경이 컸지만 컨텍스트 한계로 본문에 포함되지 않았다. 가능한 범위에서 참고만 하라.)")
```

- [ ] **Step 6: Remove 500-line per-file truncation**

`src/review/prompt_builder.py`의 `MAX_FILE_LINES = 500` 및 truncation 블록 삭제. (이제 파일 단위 drop이 책임짐.)

- [ ] **Step 7: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/review/engine.py src/review/prompt_builder.py src/models/config.py tests/test_engine.py
git commit -m "feat: token-budget compression replaces per-file line truncation"
```

---

## Phase C: Judge Pass (옵션 1)

### Task C1: Judge 시스템 프롬프트

**Files:**
- Create: `src/review/judge_prompt.py`
- Test: `tests/test_judge_prompt.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_judge_prompt.py
from src.review.judge_prompt import build_judge_system_prompt

def test_judge_prompt_mentions_dedup_and_prior_resolved():
    s = build_judge_system_prompt()
    assert "중복" in s
    assert "prior_resolved" in s
    assert "JSON" in s

def test_judge_prompt_mentions_aligned_rule():
    s = build_judge_system_prompt()
    assert "aligned" in s
    assert "mismatches" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_judge_prompt.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement judge prompt**

```python
# src/review/judge_prompt.py
JUDGE_SYSTEM_PROMPT = """너는 PR 리뷰 결과를 검토하는 judge다. 1차 리뷰 LLM이 생성한 JSON을 받아 다음 규칙으로 정리해 동일 형식의 JSON으로 출력한다.

## 규칙

1. **prior_resolved 일관성**:
   - prior_resolved에 들어간 항목의 주제가 mismatches/architecture_concern/quality_findings에 다시 등장하면 모순이다.
   - 모순 처리:
     - (a) prior_resolved 항목이 `(부분)` prefix 없으면 → 부분 해결이므로 prefix 추가
     - (b) prefix 추가 후에도 동일 주제가 두 곳에 있으면 그대로 유지 (부분 해결 + 남은 문제 자연스러움)
     - (c) prior_resolved 항목이 `(부분)` prefix 있는데 다른 섹션에 같은 주제 없으면 → "남은 문제가 실제로 없는 것"이므로 prefix 제거하여 완전 해결로 승격

2. **aligned 룰**:
   - mismatches가 빈 배열 + spec_status="present"면 aligned=true로 강제
   - mismatches가 비어 있지 않으면 aligned=false로 강제

3. **중복 제거**:
   - mismatches·quality_findings 내에서 같은 file·line·동일 주제 항목이 둘 이상이면 하나로 합친다 (description 병합).

4. **저신뢰 필터**:
   - description이 모호하거나 "할 수도 있다", "흔들릴 수 있다" 같은 hedging만으로 끝나면 quality_findings에서 제거.

5. summary는 정리 후 상태와 일치하도록 1~2문장으로 다시 작성한다.

## 출력 형식

1차 리뷰와 동일한 JSON 스키마. prior_resolved를 마지막 필드로 둔다."""


def build_judge_system_prompt() -> str:
    return JUDGE_SYSTEM_PROMPT
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_judge_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review/judge_prompt.py tests/test_judge_prompt.py
git commit -m "feat: add judge system prompt for review post-processing"
```

---

### Task C2: Judge GPT 호출 + ReviewResult 재생성

**Files:**
- Create: `src/review/judge.py`
- Test: `tests/test_judge.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_judge.py
import pytest
from unittest.mock import AsyncMock

from src.review.judge import run_judge
from src.models.review import ReviewResult, SpecStatus, Mismatch


@pytest.fixture
def contradictory_result():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="모순 있음",
        prior_resolved=["그룹 패널 책임 → 일부 분리됨"],
        architecture_concern="그룹 패널이 멤버 수집·집계 직접 담당",
    )


@pytest.fixture
def judge_fixed_result():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="부분 해결 + 잔존 책임",
        prior_resolved=["(부분) 그룹 패널 책임 → 일부 분리됨, 남은 문제는 architecture_concern 참조"],
        architecture_concern="그룹 패널이 멤버 수집·집계 직접 담당",
    )


@pytest.mark.asyncio
async def test_judge_calls_gpt_with_first_result_json(contradictory_result, judge_fixed_result):
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = judge_fixed_result

    cleaned = await run_judge(mock_gpt, contradictory_result, model="m1")

    mock_gpt.review.assert_called_once()
    args = mock_gpt.review.call_args
    # user prompt에 원본 JSON이 포함되어야 함
    user_arg = args.args[1] if len(args.args) > 1 else args.kwargs["user_prompt"]
    assert "그룹 패널" in user_arg
    assert cleaned.prior_resolved[0].startswith("(부분)")


@pytest.mark.asyncio
async def test_judge_uses_passed_model(contradictory_result, judge_fixed_result):
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = judge_fixed_result

    await run_judge(mock_gpt, contradictory_result, model="gpt-x")

    kwargs = mock_gpt.review.call_args.kwargs
    assert kwargs.get("model") == "gpt-x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_judge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement run_judge**

```python
# src/review/judge.py
from src.models.review import ReviewResult
from src.review.gpt_client import GPTClient
from src.review.judge_prompt import build_judge_system_prompt


async def run_judge(
    gpt: GPTClient,
    first_result: ReviewResult,
    model: str | None = None,
) -> ReviewResult:
    system_prompt = build_judge_system_prompt()
    user_prompt = (
        "## 1차 리뷰 결과 (JSON)\n\n"
        "```json\n"
        f"{first_result.model_dump_json(indent=2)}\n"
        "```\n\n"
        "위 결과를 시스템 프롬프트의 규칙대로 정리한 JSON을 출력하라."
    )
    return await gpt.review(system_prompt, user_prompt, model=model)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_judge.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/review/judge.py tests/test_judge.py
git commit -m "feat: judge LLM call cleans first-pass review result"
```

---

### Task C3: Engine wiring + config flag

**Files:**
- Modify: `src/review/engine.py`
- Modify: `src/models/config.py`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Add enable_judge to ReviewConfig**

```python
# src/models/config.py
class ReviewConfig(BaseModel):
    # ... 기존 ...
    enable_judge: bool = True
```

- [ ] **Step 2: Write failing test**

```python
# tests/test_engine.py (추가)
@pytest.mark.asyncio
async def test_review_pr_runs_judge_when_enabled(context):
    first = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="원본",
        prior_resolved=["X → 일부"], architecture_concern="X 잔존",
    )
    judged = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="judged",
        prior_resolved=["(부분) X → 일부, 잔존은 아키텍처 참조"],
        architecture_concern="X 잔존",
    )

    call_count = {"n": 0}
    async def fake_review(system, user, model=None):
        call_count["n"] += 1
        return first if call_count["n"] == 1 else judged

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=True)), \
         patch("src.review.engine.get_repo_file", new_callable=AsyncMock, return_value=None):
        await review_pr(context, mock_github, mock_gpt)

    assert call_count["n"] == 2  # 1차 + judge
    body = mock_github.post.call_args.kwargs["json_data"]["body"]
    assert "(부분)" in body or "🔶" in body


@pytest.mark.asyncio
async def test_review_pr_skips_judge_when_disabled(context, aligned_result):
    call_count = {"n": 0}
    async def fake_review(system, user, model=None):
        call_count["n"] += 1
        return aligned_result

    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig(enable_judge=False)), \
         patch("src.review.engine.get_repo_file", new_callable=AsyncMock, return_value=None):
        await review_pr(context, mock_github, mock_gpt)

    assert call_count["n"] == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_engine.py -k "judge" -v`
Expected: FAIL

- [ ] **Step 4: Wire judge in engine**

```python
# src/review/engine.py 수정
from src.review.judge import run_judge

# review_pr 본문, 1차 review 호출 후:
result = await gpt_client.review(system_prompt, user_prompt, model=chosen_model)
if config.enable_judge:
    result = await run_judge(gpt_client, result, model=chosen_model)
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/review/engine.py src/models/config.py tests/test_engine.py
git commit -m "feat: enable judge pass after first review to fix contradictions"
```

---

### Task C4: Config YAML 키 지원 + 문서 갱신

**Files:**
- Modify: `src/review/config_loader.py`
- Modify: `tests/test_config_loader.py`
- Modify: `README.md` (해당 절 있으면)

- [ ] **Step 1: Inspect config_loader**

Run: `grep -n "enable_judge\|token_budget\|max_expand_lines" src/review/config_loader.py tests/test_config_loader.py`

기존 loader가 BaseModel 필드를 자동 처리하면 추가 작업 없음. 그렇지 않다면 수동 매핑.

- [ ] **Step 2: Write failing test**

```python
# tests/test_config_loader.py (추가)
def test_loads_judge_compression_expand_keys():
    yaml_text = """
    enable_judge: false
    token_budget: 30000
    max_expand_lines: 80
    """
    cfg = load_config_from_yaml(yaml_text)
    assert cfg.enable_judge is False
    assert cfg.token_budget == 30000
    assert cfg.max_expand_lines == 80
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_config_loader.py -k "judge_compression" -v`
Expected: 통과 또는 실패. 실패 시 loader에 키 매핑 추가.

- [ ] **Step 4: Update loader if needed** (loader가 Pydantic 직접 사용하면 skip)

- [ ] **Step 5: Update README** (관련 절 있으면 enable_judge/token_budget/max_expand_lines 항목 추가)

- [ ] **Step 6: Commit**

```bash
git add src/review/config_loader.py tests/test_config_loader.py README.md
git commit -m "feat: expose enable_judge, token_budget, max_expand_lines via repo config"
```

---

## Final Integration Test

### Task F1: PR #650 실제 호출 검증 (수동)

- [ ] **Step 1: Run against PR #650**

```bash
unset GITHUB_TOKEN; T=$(gh auth token); set -a && source .env && set +a && export GITHUB_TOKEN=$T
.venv/bin/python -c "
# (이미 사용한 PR #650 테스트 스크립트 재실행)
"
```

- [ ] **Step 2: Verify**

- prior_resolved에 "일부" 표현 있으면 `(부분)` prefix 또는 🔶 표식
- 같은 주제가 prior_resolved + architecture_concern에 동시 나타나도 OK (부분 해결)
- `getWaypointNode` impl이 hunk에 포함되어 false positive 사라졌는지

- [ ] **Step 3: 코멘트 안 달고 결과만 캡처해서 사용자에게 보고**

---

## Self-Review Notes

- 각 Phase의 Task는 단독 commit 가능 — 중간에 멈춰도 회귀 없음
- Phase A의 `_expand_files`는 N+1 fetch (파일당 1회). 큰 PR (50파일)에서 ~50회 GitHub API call. 캐시 불필요 (PR당 1회 실행)
- Compression 예산 60k 기본값은 gpt-5.4-mini의 128k context 기준 — 모델 바꿀 때 조정 필요
- Judge 비용: 1차 review 호출 ~$0.005 → 2차 호출도 비슷. 전체 ~2배. config로 끌 수 있음
- 헤더 정규식은 일반적 패턴만 커버. 함수형 컨벤션·매크로 등 누락 가능 → 결과 보고 보강
- aligned 룰 강제는 LLM 자유도 줄이지만 일관성 ↑. 추후 룰 위반 패턴 보이면 judge 프롬프트 보강
