# 리뷰 루프 개선 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR 리뷰 봇의 매-커밋 반복 출력과 false positive를 줄인다. (1) 언어/프레임워크 문법 인지 한 줄을 프롬프트에 추가, (2) 이전 봇 리뷰 항목 재출력 금지 강화, (3) 동일 description 묶기 지시, (4) 사람 코멘트(일반·라인) fetch + 마지막 봇 리뷰 시각 이후만 user prompt에 포함, (5) 사람 의사 존중 가이드 명시.

**Architecture:** 데이터·모델 구조는 그대로. `src/review/prompt_builder.py`의 두 함수 본문 확장, `src/github/pr.py`에 코멘트 fetch 두 개 추가, `src/review/engine.py`에서 새 fetch 호출·필터링 후 `build_user_prompt`로 전달.

**Tech Stack:** Python, httpx (기존), Pydantic v2, pytest, pytest-asyncio

---

## File Structure

- `src/review/prompt_builder.py` — `SYSTEM_PROMPT` 두 줄 추가, `build_user_prompt`에 `human_comments` 인자 + 새 섹션
- `src/github/pr.py` — `get_pr_issue_comments`, `get_pr_review_comments` 두 함수 추가
- `src/review/engine.py` — 코멘트 fetch + 필터 + prompt 전달
- 새 모듈 없음. 모델·decision·reviewer 변경 없음.

---

## Task 1: 프롬프트 — 언어 인지 + 묶기 지시

**Files:**
- Modify: `src/review/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_prompt_builder.py`의 `TestBuildSystemPrompt`에 추가:

```python
    def test_includes_language_awareness_directive(self):
        prompt = build_system_prompt()
        assert "언어" in prompt and "프레임워크" in prompt
        assert "컨벤션" in prompt

    def test_includes_bundling_instruction(self):
        prompt = build_system_prompt()
        assert ("묶" in prompt or "1개로" in prompt or "여러 파일에 적용" in prompt)
```

- [ ] **Step 2: 테스트 실패 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py::TestBuildSystemPrompt -v
```
Expected: 2 new tests FAIL.

- [ ] **Step 3: SYSTEM_PROMPT 수정**

`src/review/prompt_builder.py` 의 `SYSTEM_PROMPT` 5번 항목 끝부분(즉, "발견사항이 없으면 quality_findings는 빈 배열로 둔다." 다음 줄)에 두 줄 추가:

```
   검사 시 파일의 언어·프레임워크 문법과 컨벤션을 먼저 인지하라.
   동일한 description이 여러 파일에 적용되면 finding을 1개로 묶는다. `file`은 null로 두고, description 본문에 영향 받는 파일 목록을 나열한다.
```

- [ ] **Step 4: 테스트 통과 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py -v
```
Expected: all PASS (including pre-existing `test_states_role_is_spec_alignment_only`).

- [ ] **Step 5: 커밋**

```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt): instruct lang-aware review and bundle duplicate findings"
```
No `Co-Authored-By: Claude` trailer.

---

## Task 2: 이전 리뷰 재출력 금지 강화

**Files:**
- Modify: `src/review/prompt_builder.py` (`build_user_prompt`)
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_prompt_builder.py`의 `TestBuildUserPrompt`에 추가, 그리고 기존 `test_previous_reviews_marked_as_reference_not_truth` 는 그대로 유지(어차피 통과해야 함):

```python
    def test_previous_reviews_instruct_no_duplicate_findings(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            previous_reviews=["## 🤖 스펙 정합성 리뷰\n이전지적"],
        )
        # 이전 리뷰에 이미 등록된 항목 재출력 금지를 강하게 명시
        assert "동일" in prompt or "다시 적지" in prompt or "재지적" in prompt
        # 신규/변경분 위주
        assert ("신규" in prompt or "새로 생긴" in prompt or "변경" in prompt)
```

- [ ] **Step 2: 테스트 실패 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py::TestBuildUserPrompt::test_previous_reviews_instruct_no_duplicate_findings -v
```
Expected: FAIL.

- [ ] **Step 3: build_user_prompt 본문 변경**

`build_user_prompt` 안의 `parts.append("아래는 이전 커밋에 대해 ...")` 호출의 문자열을 다음으로 교체:

```python
        parts.append(
            "아래는 이전 커밋에 대해 너가 작성한 리뷰다. **진리는 위의 현재 PR 본문과 변경 사항**이며, "
            "이전 리뷰는 참고 자료다. 본문/코드가 갱신됐으면 현재 상태 기준으로 결론을 다시 내려라.\n\n"
            "**중요**: 이전 리뷰에 이미 등록된 finding(스펙 mismatch, quality_findings, architecture_concern)과 "
            "동일한 항목은 새 리뷰에 다시 적지 마라. mismatches·quality_findings에는 "
            "**신규/변경분만** 등록한다 — 이전 커밋 이후 새로 생긴 문제, 또는 이전에는 OK였는데 이번에 어긋난 항목. "
            "이전에 적혔으나 현재 코드가 해결한 항목은 등록하지 않는다. "
            "현재 상태가 명백히 부합하면 이전 결론을 뒤집어도 된다."
        )
```

- [ ] **Step 4: 테스트 통과 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py -v
```
Expected: all PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt): forbid re-emitting findings already in prior bot reviews"
```

---

## Task 3: GitHub 코멘트 fetch 함수

**Files:**
- Modify: `src/github/pr.py`
- Test: `tests/test_engine.py` (간접 검증) 또는 새 `tests/test_pr.py`를 만들 필요 없음 — engine 통합 테스트에서 검증. 본 task는 함수 추가만 하고, 실제 호출은 Task 4에서 테스트.

- [ ] **Step 1: 함수 추가**

`src/github/pr.py` 끝에 두 함수 추가:

```python
async def get_pr_issue_comments(
    client: GitHubClient, repo: str, pr_number: int
) -> list[dict]:
    """일반 PR 코멘트 (issue 코멘트로 저장된다)."""
    return await client.get_json(
        f"/repos/{repo}/issues/{pr_number}/comments"
    )


async def get_pr_review_comments(
    client: GitHubClient, repo: str, pr_number: int
) -> list[dict]:
    """라인 단위 리뷰 코멘트."""
    return await client.get_json(
        f"/repos/{repo}/pulls/{pr_number}/comments"
    )
```

- [ ] **Step 2: import 가능 확인**

```
uv run --with-requirements requirements-dev.txt python -c "from src.github.pr import get_pr_issue_comments, get_pr_review_comments; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: 커밋**

```bash
git add src/github/pr.py
git commit -m "feat(github): fetch PR issue comments and review comments"
```

---

## Task 4: engine — 사람 코멘트 fetch + 필터링

**Files:**
- Modify: `src/review/engine.py`
- Modify: `src/review/prompt_builder.py` (build_user_prompt에 `human_comments: list[str] | None = None` 인자 추가)
- Test: `tests/test_engine.py`

이 태스크가 핵심. 코멘트 fetch → 마지막 봇 리뷰 시각 이후 + 봇 아닌 작성자만 필터 → 압축 문자열 → prompt에 전달.

### Step 1: 헬퍼 함수 + 시그니처 변경 (TDD: 테스트 먼저)

- [ ] **Step 1a: 새 헬퍼 모듈 위치 결정**

필터링 헬퍼는 `src/review/engine.py` 내부 모듈-레벨 함수로 둔다. 모듈 추가하지 않음.

- [ ] **Step 1b: build_user_prompt 시그니처 확장 — 실패 테스트 작성**

`tests/test_prompt_builder.py`의 `TestBuildUserPrompt`에 추가:

```python
    def test_human_comments_section_when_present(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            human_comments=["@alice 코멘트: 이건 의도된 동작입니다 (src/x.py:10)"],
        )
        assert "사람 코멘트" in prompt
        assert "이건 의도된 동작" in prompt

    def test_human_comments_respect_directive(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            human_comments=["@alice: 거부"],
        )
        # 가이드 명시
        assert "의도" in prompt
        assert ("거부" in prompt or "won't fix" in prompt or "다시 지적하지" in prompt)

    def test_no_human_comments_section_when_empty(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
        )
        assert "사람 코멘트" not in prompt
```

- [ ] **Step 1c: 테스트 실패 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py::TestBuildUserPrompt::test_human_comments_section_when_present tests/test_prompt_builder.py::TestBuildUserPrompt::test_human_comments_respect_directive tests/test_prompt_builder.py::TestBuildUserPrompt::test_no_human_comments_section_when_empty -v
```
Expected: 첫 두 개 FAIL (인자 없음 또는 섹션 없음), 마지막은 통과할 수도 있음.

- [ ] **Step 1d: build_user_prompt 수정**

`build_user_prompt` 시그니처에 `human_comments: list[str] | None = None` 추가. `previous_reviews` 섹션 처리 다음, return 직전에 사람 코멘트 섹션 추가:

```python
    if human_comments:
        parts.append("")
        parts.append("## 사람 코멘트 (참고용)")
        parts.append(
            "아래는 마지막 봇 리뷰 이후 사람이 남긴 코멘트다. 봇 지적에 대한 답일 수 있다. "
            "사용자가 '의도', '문법상 정상', '거부', 'won't fix' 등의 의사를 표명한 항목은 "
            "다시 지적하지 마라. '확인 중', '다음에 보겠다' 등 미정 항목은 신중히 판단하라."
        )
        for c in human_comments:
            parts.append("")
            parts.append(c)
```

- [ ] **Step 1e: 테스트 통과 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_prompt_builder.py -v
```
Expected: all PASS.

- [ ] **Step 1f: 커밋**

```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt): pass human comments into user prompt with respect directive"
```

### Step 2: engine 통합

- [ ] **Step 2a: engine 통합 테스트 작성 (TDD)**

`tests/test_engine.py` 상단의 `make_get_json_dispatch` 헬퍼를 확장해 `issue_comments`/`review_comments` 응답도 처리하도록 한다. 그리고 새 테스트 추가:

```python
def make_get_json_dispatch(
    pr_info: dict | None = None,
    reviews: list[dict] | None = None,
    issue_comments: list[dict] | None = None,
    review_comments: list[dict] | None = None,
):
    pr_info = pr_info or {
        "title": "T", "body": "B",
        "head": {"ref": "feat"}, "base": {"ref": "main"},
    }
    reviews = reviews or []
    issue_comments = issue_comments or []
    review_comments = review_comments or []

    async def dispatch(path):
        if path.endswith("/reviews"):
            return reviews
        if path.endswith(f"/issues/{path.rsplit('/', 2)[-2] if False else ''}/comments") or "/issues/" in path and path.endswith("/comments"):
            return issue_comments
        if "/pulls/" in path and path.endswith("/comments"):
            return review_comments
        return pr_info

    return dispatch
```

(단순화: dispatch 분기는 `if "/issues/" in path: return issue_comments`, `elif "/pulls/" in path and path.endswith("/comments"): return review_comments` 정도로 충분.)

새 테스트:

```python
@pytest.mark.asyncio
async def test_review_pr_includes_human_comments_after_last_bot_review(context, aligned_result):
    """봇 리뷰 시각 이후 사람 코멘트는 user prompt에 포함."""
    bot_login = "github-actions[bot]"
    last_review_time = "2026-05-13T10:00:00Z"
    reviews = [
        {
            "body": "## 🤖 스펙 정합성 리뷰\nprev",
            "user": {"login": bot_login},
            "submitted_at": last_review_time,
        }
    ]
    issue_comments = [
        {
            "body": "이건 의도다",
            "user": {"login": "alice"},
            "created_at": "2026-05-13T11:00:00Z",  # 이후 — 포함
        },
        {
            "body": "오래된 토론",
            "user": {"login": "alice"},
            "created_at": "2026-05-13T09:00:00Z",  # 이전 — 제외
        },
        {
            "body": "봇 본인",
            "user": {"login": bot_login},
            "created_at": "2026-05-13T11:30:00Z",  # 작성자 봇 — 제외
        },
    ]
    review_comments = [
        {
            "body": "라인 답글: 정상 동작",
            "user": {"login": "bob"},
            "path": "src/x.py",
            "line": 10,
            "created_at": "2026-05-13T11:15:00Z",  # 이후 — 포함
        },
    ]
    captured = {}

    async def fake_review(system, user, model=None):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(
        reviews=reviews,
        issue_comments=issue_comments,
        review_comments=review_comments,
    )
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig()):
        await review_pr(context, mock_github, mock_gpt)

    user_prompt = captured["user"]
    assert "사람 코멘트" in user_prompt
    assert "이건 의도다" in user_prompt
    assert "라인 답글: 정상 동작" in user_prompt
    assert "src/x.py:10" in user_prompt
    assert "오래된 토론" not in user_prompt
    assert "봇 본인" not in user_prompt


@pytest.mark.asyncio
async def test_review_pr_includes_all_comments_when_no_prior_bot_review(context, aligned_result):
    """봇 리뷰가 한 번도 없으면 모든 사람 코멘트 포함 (작성자 봇 제외)."""
    issue_comments = [
        {
            "body": "PR 설명 보충",
            "user": {"login": "alice"},
            "created_at": "2026-05-13T09:00:00Z",
        },
    ]
    captured = {}

    async def fake_review(system, user, model=None):
        captured["user"] = user
        return aligned_result

    mock_github = _mock_github(reviews=[], issue_comments=issue_comments, review_comments=[])
    mock_gpt = AsyncMock()
    mock_gpt.review.side_effect = fake_review

    with patch("src.review.engine.load_repo_config", return_value=ReviewConfig()):
        await review_pr(context, mock_github, mock_gpt)

    assert "PR 설명 보충" in captured["user"]
```

- [ ] **Step 2b: 테스트 실패 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_engine.py::test_review_pr_includes_human_comments_after_last_bot_review tests/test_engine.py::test_review_pr_includes_all_comments_when_no_prior_bot_review -v
```
Expected: FAIL — engine은 아직 코멘트를 fetch하지 않는다.

- [ ] **Step 2c: engine 수정**

`src/review/engine.py` 의 import 갱신:

```python
from src.github.pr import (
    get_pr_diff, get_pr_info, get_pr_reviews,
    get_pr_issue_comments, get_pr_review_comments,
    get_repo_file,
)
```

그리고 `review_pr` 함수 안, `raw_reviews = await get_pr_reviews(...)` 라인 다음에 추가:

```python
    bot_reviews = filter_bot_reviews(raw_reviews)
    previous_reviews = [r["body"] for r in bot_reviews]

    last_bot_review_time = None
    bot_logins = set()
    if bot_reviews:
        last_bot_review_time = max(r.get("submitted_at") or "" for r in bot_reviews)
        bot_logins = {(r.get("user") or {}).get("login") for r in bot_reviews if r.get("user")}

    issue_comments = await get_pr_issue_comments(
        github_client, context.repo, context.pr_number
    )
    review_comments = await get_pr_review_comments(
        github_client, context.repo, context.pr_number
    )
    human_comments = _filter_and_format_comments(
        issue_comments, review_comments, last_bot_review_time, bot_logins
    )
```

(기존 라인 `previous_reviews = [r["body"] for r in filter_bot_reviews(raw_reviews)]`은 위 두 줄로 바뀐다.)

그리고 `build_user_prompt(...)` 호출에 `human_comments=human_comments` 추가.

모듈 끝에 헬퍼 함수 추가:

```python
def _filter_and_format_comments(
    issue_comments: list[dict],
    review_comments: list[dict],
    after_time: str | None,
    bot_logins: set[str],
) -> list[str]:
    """봇 리뷰 시각 이후 + 봇이 아닌 작성자의 코멘트만 압축 문자열로."""
    formatted: list[tuple[str, str]] = []  # (created_at, line)

    for c in issue_comments:
        login = (c.get("user") or {}).get("login")
        if not login or login in bot_logins:
            continue
        created = c.get("created_at") or ""
        if after_time and created <= after_time:
            continue
        body = (c.get("body") or "").strip()
        if not body:
            continue
        formatted.append((created, f"@{login}: {body}"))

    for c in review_comments:
        login = (c.get("user") or {}).get("login")
        if not login or login in bot_logins:
            continue
        created = c.get("created_at") or ""
        if after_time and created <= after_time:
            continue
        body = (c.get("body") or "").strip()
        if not body:
            continue
        path = c.get("path")
        line = c.get("line") or c.get("original_line")
        loc = f" ({path}:{line})" if path and line else (f" ({path})" if path else "")
        formatted.append((created, f"@{login}{loc}: {body}"))

    formatted.sort(key=lambda t: t[0])
    return [line for _, line in formatted]
```

`filter_files`/`parse_diff` 등은 기존 import 그대로 둔다. 새로 import한 두 함수만 추가.

`build_user_prompt(...)` 호출은:

```python
    user_prompt = build_user_prompt(
        files=filtered,
        pr_title=pr_info["title"],
        pr_body=pr_info.get("body") or "",
        base_branch=pr_info["base"]["ref"],
        head_branch=pr_info["head"]["ref"],
        previous_reviews=previous_reviews,
        human_comments=human_comments,
    )
```

- [ ] **Step 2d: 테스트 통과 확인**

```
uv run --with-requirements requirements-dev.txt pytest tests/test_engine.py -v
```
Expected: all PASS. 기존 engine 테스트들도 깨지면 안 됨.

기존 테스트의 mock dispatch가 `/issues/.../comments` 와 `/pulls/.../comments` 분기를 갖지 않으면 `pr_info`가 잘못 반환된다. `make_get_json_dispatch` 의 dispatch 함수를 다음처럼 단순화한 분기로 갱신:

```python
async def dispatch(path):
    if "/issues/" in path and path.endswith("/comments"):
        return issue_comments
    if "/pulls/" in path and path.endswith("/comments"):
        return review_comments
    if path.endswith("/reviews"):
        return reviews
    return pr_info
```

이 분기 순서가 중요 (`/pulls/{n}/comments` 와 `/pulls/{n}/reviews` 모두 `/pulls/` 포함).

- [ ] **Step 2e: 전체 테스트 실행**

```
uv run --with-requirements requirements-dev.txt pytest -q
```
Expected: 모든 테스트 통과.

- [ ] **Step 2f: 커밋**

```bash
git add src/review/engine.py tests/test_engine.py
git commit -m "feat(engine): fetch and filter human comments after last bot review"
```

---

## Task 5: 통합 확인 + 문서

**Files:**
- Modify: `README.md` (선택)

- [ ] **Step 1: 전체 테스트**

```
uv run --with-requirements requirements-dev.txt pytest -q
```
Expected: all PASS.

- [ ] **Step 2: README 갱신 (선택)**

"정합성 검토 동작" 섹션에 한 줄 추가:

> 마지막 봇 리뷰 이후 작성된 사람 코멘트(일반·라인)를 함께 읽어 의사 표명을 반영한다.

- [ ] **Step 3: 커밋 (변경 있을 때만)**

```bash
git add README.md
git commit -m "docs: mention human-comment awareness in review behavior"
```

---

## Self-Review 체크

- 스펙 커버리지:
  - 1) 언어 인지 한 줄 → Task 1 ✅
  - 2) 이전 리뷰 재출력 금지 강화 → Task 2 ✅
  - 3) 동일 description 묶기 → Task 1 (같이) ✅
  - 4) 사람 코멘트 fetch + 필터 → Task 3, 4 ✅
  - 5) 사람 의사 존중 가이드 → Task 4 Step 1d ✅
- 플레이스홀더: 없음. 모든 코드 블록 실체. ✅
- 타입 일관성: `human_comments: list[str] | None`, `bot_logins: set[str]`, `last_bot_review_time: str | None` — 전 태스크 일관. ✅
- 기존 테스트 회귀: `test_states_role_is_spec_alignment_only` 가 금지하는 단어(점수/score/rubric/critical/warning/minor)를 새 프롬프트에 쓰지 않도록 주의. ✅
- engine 테스트의 `make_get_json_dispatch` 분기 순서 — `/pulls/.../comments` 와 `/pulls/.../reviews` 둘 다 매칭되므로 `/comments` 먼저 검사. ✅
