# Confidence Field + Dedup Post-processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 출력의 룰 위반(중복 등록, prior_resolved prefix 누락, 저신뢰 finding)을 코드 단 후처리로 정리해 재리뷰 일관성·신뢰도 향상.

**Architecture:** `Mismatch`·`QualityFinding`에 `confidence: int (0-100)` 필드 추가. 시스템 프롬프트에서 LLM에게 각 finding마다 confidence 강제 출력. 신규 `postprocess` 모듈이 (1) 임계값 미만 finding drop, (2) 같은 (file, line) mismatches+quality 중복 통합 (mismatch 우선), (3) prior_resolved 주제가 다른 섹션에 남아있으면 `(부분)` prefix 자동 부착. 엔진은 LLM 호출 직후 postprocess 호출. 렌더러는 각 finding에 `[conf N]` 표시.

**Tech Stack:** Python 3.11, Pydantic v2, pytest.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/models/review.py` (modify) | `Mismatch`, `QualityFinding`에 `confidence: int` 필드 추가 |
| `src/review/prompt_builder.py` (modify) | JSON 출력 형식 schema에 `confidence` 필드 명시, self-check 룰을 출력 강제로 격상 |
| `src/review/postprocess.py` (new) | `postprocess(result, threshold) -> ReviewResult` — filter + dedup + prefix enforcement |
| `src/review/engine.py` (modify) | LLM 호출 직후 postprocess 호출 |
| `src/github/reviewer.py` (modify) | mismatches/quality_findings 렌더링에 `[conf N]` 추가 |
| `src/models/config.py` (modify) | `confidence_threshold: int = 70` 필드 추가 |
| `tests/test_postprocess.py` (new) | postprocess 단위 테스트 |
| `tests/test_models.py` (modify) | confidence 필드 검증 |
| `tests/test_reviewer.py` (modify) | confidence 렌더 검증 |
| `tests/test_engine.py` (modify) | 통합 회귀 |
| `tests/test_prompt_builder.py` (modify) | confidence 출력 강제 검증 |

---

## Phase G

### Task G1: `Mismatch`·`QualityFinding`에 `confidence` 필드 추가

**Files:**
- Modify: `src/models/review.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models.py 추가
def test_mismatch_requires_confidence_field():
    from src.models.review import Mismatch
    # 명시 제공
    m = Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=85)
    assert m.confidence == 85

def test_mismatch_confidence_must_be_in_range():
    from src.models.review import Mismatch
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=150)
    with pytest.raises(ValidationError):
        Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=-5)

def test_quality_finding_confidence_field():
    from src.models.review import QualityFinding, FindingCategory
    q = QualityFinding(
        category=FindingCategory.BUG, file="a.py", line=1,
        description="d", suggestion="s", confidence=75,
    )
    assert q.confidence == 75

def test_mismatch_confidence_defaults_to_70():
    from src.models.review import Mismatch
    # 기존 호출자 (테스트 등)가 confidence 안 줘도 동작하도록 default
    m = Mismatch(file="a.py", line=1, description="d", suggestion="s")
    assert m.confidence == 70
```

- [ ] **Step 2: Verify fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_models.py -k confidence -v`
Expected: FAIL — `confidence` 필드 없음

- [ ] **Step 3: Add field to models**

`src/models/review.py`의 `Mismatch`·`QualityFinding`에 다음 필드 추가:

```python
confidence: int = Field(default=70, ge=0, le=100)
```

전체 클래스 예시 (Mismatch):

```python
class Mismatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str
    confidence: int = Field(default=70, ge=0, le=100)
```

QualityFinding도 동일하게 마지막에 추가.

- [ ] **Step 4: Verify pass**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/ -q`
Expected: PASS — 기존 테스트들이 confidence 인자 안 주고 호출해도 default 70으로 통과해야 함. extra="forbid"이므로 confidence는 정의된 필드라 OK.

- [ ] **Step 5: Commit**

```bash
git add src/models/review.py tests/test_models.py
git commit -m "feat: add confidence field to Mismatch and QualityFinding (default 70)"
```

---

### Task G2: 시스템 프롬프트 JSON에 confidence 강제

**Files:**
- Modify: `src/review/prompt_builder.py`
- Modify: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_prompt_builder.py 추가
def test_system_prompt_requires_confidence_in_json_schema():
    from src.review.prompt_builder import build_system_prompt
    s = build_system_prompt()
    # 출력 형식 JSON 스키마에 confidence 필드가 명시되어 있어야 함
    # mismatches와 quality_findings 양쪽 모두
    schema_section = s[s.index("출력 형식"):]
    assert schema_section.count("confidence") >= 2  # mismatches + quality_findings
```

- [ ] **Step 2: Verify fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_prompt_builder.py -k confidence -v`
Expected: FAIL — confidence 키워드가 schema에 없음

- [ ] **Step 3: Edit SYSTEM_PROMPT JSON schema**

`src/review/prompt_builder.py`의 SYSTEM_PROMPT 안 `"mismatches": [...]` 항목과 `"quality_findings": [...]` 항목 각각에 `"confidence": <0-100 정수>` 필드 추가.

`mismatches` 블록:

```json
  "mismatches": [
    {
      "file": "<경로 또는 null>",
      "line": <라인 번호 또는 null>,
      "description": "<스펙과 어떻게 다른지>",
      "suggestion": "<어떻게 맞춰야 하는지>",
      "confidence": <0-100 정수 — self-check 기준으로 산정한 확신도>
    }
  ],
```

`quality_findings` 블록:

```json
  "quality_findings": [
    {
      "category": "bug" | "vulnerability" | "security" | "smell" | "complexity",
      "file": "<경로 또는 null>",
      "line": <라인 번호 또는 null>,
      "description": "<무엇이 문제인지>",
      "suggestion": "<어떻게 고쳐야 하는지>",
      "confidence": <0-100 정수>
    }
  ],
```

또한 self-check 룰 문단 끝에 다음 문장 추가:

```
**confidence는 출력 JSON 필드로 반드시 포함하라.** 직접 산정한 값을 그대로 적어라.
```

- [ ] **Step 4: Verify pass**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat: require LLM to emit confidence per finding in output JSON"
```

---

### Task G3: postprocess — 저신뢰 필터 + 중복 제거

**Files:**
- Create: `src/review/postprocess.py`
- Test: `tests/test_postprocess.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_postprocess.py
import pytest

from src.models.review import (
    FindingCategory, Mismatch, QualityFinding, ReviewResult, SpecStatus,
)
from src.review.postprocess import postprocess


def _result(**kw):
    base = dict(spec_status=SpecStatus.PRESENT, aligned=True, summary="s")
    base.update(kw)
    return ReviewResult(**base)


def test_filters_low_confidence_mismatches():
    r = _result(
        mismatches=[
            Mismatch(file="a.py", line=1, description="확실", suggestion="s", confidence=85),
            Mismatch(file="b.py", line=2, description="약함", suggestion="s", confidence=40),
        ],
    )
    out = postprocess(r, threshold=70)
    paths = [m.file for m in out.mismatches]
    assert paths == ["a.py"]


def test_filters_low_confidence_quality_findings():
    r = _result(
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="a.py", line=1,
                description="확실", suggestion="s", confidence=75,
            ),
            QualityFinding(
                category=FindingCategory.SMELL, file="b.py", line=2,
                description="모호", suggestion="s", confidence=50,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert [q.file for q in out.quality_findings] == ["a.py"]


def test_dedups_same_file_line_across_mismatches_and_quality_keeping_mismatch():
    r = _result(
        mismatches=[
            Mismatch(file="a.py", line=10, description="스펙 위반", suggestion="s", confidence=80),
        ],
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="a.py", line=10,
                description="같은 위치 버그", suggestion="s", confidence=80,
            ),
            QualityFinding(
                category=FindingCategory.SMELL, file="b.py", line=5,
                description="다른 위치", suggestion="s", confidence=80,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert len(out.mismatches) == 1
    assert len(out.quality_findings) == 1
    assert out.quality_findings[0].file == "b.py"  # 같은 (a.py, 10) 항목은 mismatch만 유지


def test_aligned_recomputed_when_mismatches_changed():
    # 초기엔 aligned=True인데 mismatch가 들어있는 모순 케이스도 정리
    r = _result(
        aligned=True,
        mismatches=[
            Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=85),
        ],
    )
    out = postprocess(r, threshold=70)
    assert out.aligned is False  # mismatches 있으면 False 강제


def test_aligned_recomputed_when_all_mismatches_filtered_out():
    r = _result(
        aligned=False,
        spec_status=SpecStatus.PRESENT,
        mismatches=[
            Mismatch(file="a.py", line=1, description="약한", suggestion="s", confidence=30),
        ],
    )
    out = postprocess(r, threshold=70)
    # 모두 필터되면 mismatches=[]이고 spec_status=present면 aligned=True
    assert out.mismatches == []
    assert out.aligned is True


def test_low_arch_concern_confidence_cleared():
    """arch concern은 단일 string이라 confidence를 어디서? 별도 시그널 없으면 그대로 둠."""
    r = _result(architecture_concern="단순 framework wiring")
    out = postprocess(r, threshold=70)
    # arch는 LLM이 confidence를 별도로 표현할 수단 없으므로 보존
    assert out.architecture_concern == "단순 framework wiring"
```

- [ ] **Step 2: Verify fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_postprocess.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement postprocess (filter + dedup, no prefix yet)**

```python
# src/review/postprocess.py
from src.models.review import Mismatch, QualityFinding, ReviewResult, SpecStatus


def postprocess(result: ReviewResult, threshold: int = 70) -> ReviewResult:
    """LLM 출력 정리:
    - confidence < threshold finding drop
    - 같은 (file, line) mismatches + quality_findings 중복 → mismatch 우선 유지
    - mismatches 변화에 따라 aligned 재계산 (spec_status=present 일 때만 영향)

    prior_resolved prefix 강제는 다음 task(G4)에서 추가.
    """
    kept_mismatches = [m for m in result.mismatches if m.confidence >= threshold]

    mismatch_locations: set[tuple[str | None, int | None]] = {
        (m.file, m.line) for m in kept_mismatches
    }
    kept_quality = [
        q for q in result.quality_findings
        if q.confidence >= threshold and (q.file, q.line) not in mismatch_locations
    ]

    new_aligned = result.aligned
    if result.spec_status == SpecStatus.PRESENT:
        new_aligned = len(kept_mismatches) == 0

    return result.model_copy(update={
        "mismatches": kept_mismatches,
        "quality_findings": kept_quality,
        "aligned": new_aligned,
    })
```

- [ ] **Step 4: Verify pass**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_postprocess.py -v`
Expected: PASS — 6 테스트

Full suite: `.venv/bin/pytest tests/ -q` — 회귀 없음

- [ ] **Step 5: Commit**

```bash
git add src/review/postprocess.py tests/test_postprocess.py
git commit -m "feat: postprocess filters low-confidence findings and dedups across sections"
```

---

### Task G4: postprocess — prior_resolved `(부분)` prefix 자동 강제

**Files:**
- Modify: `src/review/postprocess.py`
- Modify: `tests/test_postprocess.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_postprocess.py 추가
def test_prior_resolved_gets_partial_prefix_when_topic_still_in_findings():
    r = _result(
        prior_resolved=["그룹 패널 책임 → helper 분리로 일부 완화"],
        architecture_concern="그룹 패널이 멤버 수집·집계·Command 실행 직접 담당",
    )
    out = postprocess(r, threshold=70)
    # 같은 주제 단어 ("그룹 패널")가 arch에 남아있으므로 prior_resolved에 (부분) prefix 강제
    assert out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_keeps_full_when_topic_not_in_findings():
    r = _result(
        prior_resolved=["필드 초기값 → 생성자에서 보정"],
        architecture_concern="다른 주제",
    )
    out = postprocess(r, threshold=70)
    # 주제 일치 안 함 → prefix 추가하지 않음
    assert not out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_partial_prefix_already_present_kept():
    r = _result(
        prior_resolved=["(부분) 그룹 패널 책임 → 일부 완화"],
        architecture_concern="그룹 패널 책임",
    )
    out = postprocess(r, threshold=70)
    # 이미 prefix 있음 → 중복 추가 금지
    assert out.prior_resolved[0].count("(부분)") == 1


def test_prior_resolved_topic_match_uses_findings_after_filtering():
    """confidence 필터 후 남은 findings 기준으로 prefix 결정."""
    r = _result(
        prior_resolved=["그룹 패널 책임 → helper 분리"],
        quality_findings=[
            QualityFinding(
                category=FindingCategory.SMELL, file=None, line=None,
                description="그룹 패널 책임 집중", suggestion="s", confidence=40,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    # quality_findings는 confidence=40으로 필터됨 → 주제 매칭 없음 → prefix 추가 안 함
    assert not out.prior_resolved[0].startswith("(부분)")
```

- [ ] **Step 2: Verify fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_postprocess.py -k prior_resolved -v`
Expected: FAIL

- [ ] **Step 3: Add prefix enforcement to postprocess**

`src/review/postprocess.py`에 helper + 메인 함수 확장:

```python
import re


_TOKEN_RE = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9_\.]*")


def _significant_tokens(text: str) -> set[str]:
    """3글자 이상 영문/한글 토큰 추출 (조사·짧은 단어 제외)."""
    return {tok for tok in _TOKEN_RE.findall(text) if len(tok) >= 3}


def _enforce_partial_prefix(
    prior_resolved: list[str],
    finding_texts: list[str],
) -> list[str]:
    """prior_resolved 항목의 주제 토큰이 다른 finding에 등장하면 (부분) prefix 강제.
    이미 prefix 있으면 중복 추가하지 않음.
    """
    all_finding_tokens: set[str] = set()
    for t in finding_texts:
        all_finding_tokens.update(_significant_tokens(t))

    out: list[str] = []
    for item in prior_resolved:
        stripped = item.lstrip()
        if stripped.startswith("(부분)"):
            out.append(item)
            continue
        item_tokens = _significant_tokens(item)
        # 최소 2개 토큰 일치 (단발 매칭 잡음 회피)
        overlap = item_tokens & all_finding_tokens
        if len(overlap) >= 2:
            out.append(f"(부분) {item}")
        else:
            out.append(item)
    return out


def postprocess(result: ReviewResult, threshold: int = 70) -> ReviewResult:
    kept_mismatches = [m for m in result.mismatches if m.confidence >= threshold]

    mismatch_locations: set[tuple[str | None, int | None]] = {
        (m.file, m.line) for m in kept_mismatches
    }
    kept_quality = [
        q for q in result.quality_findings
        if q.confidence >= threshold and (q.file, q.line) not in mismatch_locations
    ]

    new_aligned = result.aligned
    if result.spec_status == SpecStatus.PRESENT:
        new_aligned = len(kept_mismatches) == 0

    finding_texts = [m.description for m in kept_mismatches]
    finding_texts += [q.description for q in kept_quality]
    if result.architecture_concern:
        finding_texts.append(result.architecture_concern)

    new_prior_resolved = _enforce_partial_prefix(result.prior_resolved, finding_texts)

    return result.model_copy(update={
        "mismatches": kept_mismatches,
        "quality_findings": kept_quality,
        "aligned": new_aligned,
        "prior_resolved": new_prior_resolved,
    })
```

- [ ] **Step 4: Verify pass**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_postprocess.py -v`
Expected: PASS — 10 테스트 모두

Full suite: `.venv/bin/pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add src/review/postprocess.py tests/test_postprocess.py
git commit -m "feat: postprocess auto-applies (부분) prefix when prior_resolved topic remains in findings"
```

---

### Task G5: engine wiring + config

**Files:**
- Modify: `src/models/config.py`
- Modify: `src/review/engine.py`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Add config field**

`src/models/config.py`의 `ReviewConfig`에 추가:

```python
    confidence_threshold: int = 70
```

- [ ] **Step 2: Write failing test**

`tests/test_engine.py` 추가:

```python
@pytest.mark.asyncio
async def test_review_pr_applies_postprocess_filter(context):
    """엔진이 LLM 응답에 postprocess를 적용해 저신뢰 finding을 제거."""
    result = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="혼합",
        mismatches=[
            Mismatch(file="a.py", line=1, description="확실", suggestion="s", confidence=85),
            Mismatch(file="b.py", line=2, description="약함", suggestion="s", confidence=40),
        ],
    )
    mock_github = _mock_github()
    mock_gpt = AsyncMock()
    mock_gpt.review.return_value = result

    with patch(
        "src.review.engine.load_repo_config",
        new_callable=AsyncMock,
        return_value=ReviewConfig(enable_judge=False, enable_tool_use=False, confidence_threshold=70),
    ), _NO_EXPAND:
        await review_pr(context=context, github_client=mock_github, gpt_client=mock_gpt)

    body = mock_github.post.call_args.kwargs["json_data"]["body"]
    assert "확실" in body
    assert "약함" not in body
```

- [ ] **Step 3: Verify fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_engine.py -k postprocess -v`
Expected: FAIL — postprocess 미연결, "약함" 본문에 노출됨

- [ ] **Step 4: Wire postprocess in engine**

`src/review/engine.py`:

```python
from src.review.postprocess import postprocess
```

`review_pr`의 LLM 호출 직후, judge 호출 직전에:

```python
result = await gpt_client.review(
    system_prompt, user_prompt,
    model=chosen_model,
    tool_executor=executor,
    max_tool_iterations=config.max_tool_iterations,
)
result = postprocess(result, threshold=config.confidence_threshold)
if config.enable_judge:
    result = await run_judge(gpt_client, result, model=chosen_model)
```

- [ ] **Step 5: Verify pass**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/review/engine.py src/models/config.py tests/test_engine.py
git commit -m "feat: engine applies postprocess (filter + dedup + prior prefix) after LLM"
```

---

### Task G6: 렌더러에 confidence 노출

**Files:**
- Modify: `src/github/reviewer.py`
- Modify: `tests/test_reviewer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_reviewer.py 추가
def test_mismatch_renders_with_confidence_tag():
    from src.github.reviewer import format_review_body
    from src.models.review import Mismatch, ReviewResult, SpecStatus
    r = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=False, summary="s",
        mismatches=[
            Mismatch(file="a.py", line=10, description="d", suggestion="s", confidence=85),
        ],
    )
    body = format_review_body(r)
    assert "conf 85" in body


def test_quality_finding_renders_with_confidence_tag():
    from src.github.reviewer import format_review_body
    from src.models.review import FindingCategory, QualityFinding, ReviewResult, SpecStatus
    r = ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True, summary="s",
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="x.py", line=1,
                description="d", suggestion="s", confidence=72,
            ),
        ],
    )
    body = format_review_body(r)
    assert "conf 72" in body
```

- [ ] **Step 2: Verify fail**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_reviewer.py -k confidence_tag -v`
Expected: FAIL

- [ ] **Step 3: Update renderer**

`src/github/reviewer.py`:

mismatches 테이블 헤더에 conf 컬럼 추가:

```python
"| # | 항목 | 위치 | conf | 제안 |",
"|---|------|------|------|------|",
```

루프 안:

```python
lines.append(f"| {idx} | {desc} | {loc} | conf {m.confidence} | {sugg} |")
```

quality_findings 테이블도 동일하게:

```python
lines.append("| # | 분류 | 항목 | 위치 | conf | 제안 |")
lines.append("|---|------|------|------|------|------|")
for idx, f in enumerate(result.quality_findings, 1):
    ...
    lines.append(f"| {idx} | {cat} | {desc} | {loc} | conf {f.confidence} | {sugg} |")
```

- [ ] **Step 4: Verify pass**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/github/reviewer.py tests/test_reviewer.py
git commit -m "feat: render confidence tag per finding in review body"
```

---

### Task G7: Config YAML 키 노출

**Files:**
- Modify: `src/review/config_loader.py`
- Modify: `tests/test_config_loader.py`

- [ ] **Step 1: Inspect loader**

Run: `grep -n "confidence_threshold\|enable_tool_use" /Users/kyungjuchoi/Projects/syscon-review-bot/src/review/config_loader.py`

기존 키 매핑 방식 확인. 동일 패턴으로 `confidence_threshold` 추가.

- [ ] **Step 2: Write failing test**

```python
# tests/test_config_loader.py 추가
def test_loads_confidence_threshold_key():
    yaml_text = """
confidence_threshold: 80
"""
    cfg = load_config_from_yaml(yaml_text)
    assert cfg.confidence_threshold == 80
```

- [ ] **Step 3: Run test**

Run: `cd /Users/kyungjuchoi/Projects/syscon-review-bot && .venv/bin/pytest tests/test_config_loader.py -k confidence -v`
필요 시 loader에 키 추가.

- [ ] **Step 4: Full suite + commit**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS

```bash
git add src/review/config_loader.py tests/test_config_loader.py
git commit -m "feat: expose confidence_threshold via repo config"
```

---

### Task F4: PR #650 3회 분산 검증 (수동)

- [ ] **Step 1: Run script**

```bash
cd /Users/kyungjuchoi/Projects/syscon-review-bot
unset GITHUB_TOKEN; T=$(gh auth token); set -a && source .env && set +a && export GITHUB_TOKEN=$T
.venv/bin/python <<'EOF'
import asyncio, os
from src.github.client import GitHubClient
from src.github.pr import get_pr_diff, get_pr_info, get_pr_reviews, get_pr_issue_comments, get_pr_review_comments
from src.github.reviewer import filter_bot_reviews, format_review_body
from src.review.diff_parser import parse_diff, filter_files
from src.review.prompt_builder import build_system_prompt, build_user_prompt
from src.review.engine import _build_conversation_history, _expand_files
from src.review.compressor import compress_files
from src.review.gpt_client import GPTClient
from src.review.tool_executor import GitHubToolExecutor
from src.review.postprocess import postprocess
from src.models.config import ReviewConfig

async def main():
    gh = GitHubClient(token=os.environ['GITHUB_TOKEN'])
    repo = 'sr-amr-acs-dev/sarics_nx'
    pr_num = 650
    pr_info = await get_pr_info(gh, repo, pr_num)
    diff_text = await get_pr_diff(gh, repo, pr_num)
    cfg = ReviewConfig(enable_tool_use=True, enable_judge=False, max_tool_iterations=15)
    files = parse_diff(diff_text)
    filtered = filter_files(files, cfg.ignore)
    head_sha = pr_info['head']['sha']
    filtered = await _expand_files(gh, repo, head_sha, filtered, cfg.max_expand_lines)
    filtered, dropped = compress_files(filtered, cfg.token_budget)
    raw = await get_pr_reviews(gh, repo, pr_num)
    br = filter_bot_reviews(raw)
    bl = {(r.get('user') or {}).get('login') for r in br if (r.get('user') or {}).get('login')}
    ic = await get_pr_issue_comments(gh, repo, pr_num)
    rc = await get_pr_review_comments(gh, repo, pr_num)
    conv = _build_conversation_history(br, ic, rc, bl)
    sp = build_system_prompt()
    up = build_user_prompt(files=filtered, pr_title=pr_info['title'], pr_body=pr_info.get('body') or '',
        base_branch=pr_info['base']['ref'], head_branch=pr_info['head']['ref'],
        conversation_history=conv, dropped_paths=dropped)
    gpt = GPTClient(api_key=os.environ['OPENAI_API_KEY'])
    executor = GitHubToolExecutor(gh, repo, head_sha)
    for i in range(3):
        r = await gpt.review(sp, up, tool_executor=executor, max_tool_iterations=cfg.max_tool_iterations)
        r = postprocess(r, threshold=cfg.confidence_threshold)
        print(f'=== RUN {i+1} ===')
        print(f'mismatches={len(r.mismatches)}, quality={len(r.quality_findings)}, prior_resolved={len(r.prior_resolved)}')
        for m in r.mismatches:
            print(f'  m {m.file}:{m.line} conf={m.confidence}')
        for q in r.quality_findings:
            print(f'  q {q.file}:{q.line} conf={q.confidence}')
        for p in r.prior_resolved:
            print(f'  p {p[:80]}')
    await gh.close()

asyncio.run(main())
EOF
```

- [ ] **Step 2: Verify expected behavior**

기대:
- mismatches와 quality_findings에 같은 (file, line) 중복 없음 (postprocess dedup)
- confidence < 70 finding 자동 drop
- prior_resolved의 부분 해결 항목에 `(부분)` prefix 자동 부착
- 3회 결과 일관성 향상 (이전 1단계 대비)

- [ ] **Step 3: 사용자에게 결과 보고**

---

## Self-Review Notes

- G1: `extra="forbid"`라 기존 테스트가 `Mismatch(...)` 호출 시 `confidence` 없이 호출해도 default 70으로 OK. 기존 테스트 호환.
- G2: LLM이 confidence 안 채우면 Pydantic이 default 70 사용 → 기본적으로 threshold 70과 동일 → 통과. LLM이 낮은 값 명시할 때만 drop 발동.
- G3: dedup 키는 (file, line). 같은 파일·라인의 mismatch와 quality는 같은 이슈로 간주. 다른 라인이거나 file=None이면 별개로 본다 — 보수적.
- G4: 토큰 매칭 임계 2개. 단발 우연 매칭 회피. "그룹 패널" / "패널" 같은 짧은 단어 잡음 가능성은 `len >= 3` 필터로 줄임. 완벽하지 않지만 휴리스틱.
- G5: engine 흐름 = LLM → postprocess → (옵션) judge. postprocess가 judge 앞이라 judge가 정리된 결과를 받음 (judge 켜진 경우).
- G6: 표 컬럼 추가는 기존 렌더 테스트 깨질 수 있음 — `| # | 항목 | 위치 | 제안 |` 형식 검사 테스트가 있으면 수정 필요. 발견 시 surgical update.
- G7: loader 패턴 확인 후 추가.
- F4 검증 결과 따라 threshold 조정 (60 또는 80) 가능.
