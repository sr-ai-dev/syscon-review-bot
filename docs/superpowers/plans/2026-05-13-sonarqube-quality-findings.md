# SonarQube 스타일 코드 품질 검사 추가 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR 리뷰 봇이 스펙 정합성 검토와 함께 SonarQube 주요 항목(버그·취약점·보안 핫스팟·코드 스멜·복잡도)을 한 번의 LLM 호출로 검토하고, 발견사항을 별도 `quality_findings` 필드로 리뷰 본문에 노출한다.

**Architecture:** 기존 `ReviewResult` 모델에 `QualityFinding` 리스트 필드 1개 추가. 시스템 프롬프트에 검사 섹션과 JSON 스키마 항목 추가. `compute_decision`은 bug/vulnerability 발견 시 REQUEST_CHANGES, 그 외 발견 시 COMMENT로 격하. `format_review_body`에 "코드 품질 검사" 섹션 렌더링. 구조 변경 최소 — 새 모델 1개, 필드 1개.

**Tech Stack:** Python, Pydantic v2, pytest

---

## File Structure

- `src/models/review.py` — `FindingCategory` enum + `QualityFinding` 모델 추가, `ReviewResult.quality_findings` 필드 추가
- `src/review/prompt_builder.py` — `SYSTEM_PROMPT`에 SonarQube 검사 섹션 + JSON 스키마 항목 추가
- `src/review/decision.py` — `compute_decision`에 quality_findings 기반 규칙 추가
- `src/github/reviewer.py` — `format_review_body`에 "코드 품질 검사" 섹션, `_format_location` 일반화
- `tests/test_models.py`, `tests/test_decision.py`, `tests/test_prompt_builder.py`, `tests/test_reviewer.py` — 테스트 추가

---

## Task 1: QualityFinding 모델 + ReviewResult 필드

**Files:**
- Modify: `src/models/review.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_models.py` 상단 import를 수정하고 (`QualityFinding`, `FindingCategory` 추가), 새 테스트 클래스 추가:

```python
# import 라인 변경:
from src.models.review import (
    Mismatch, ReviewResult, SpecStatus, Decision,
    QualityFinding, FindingCategory,
)
```

```python
class TestQualityFinding:
    def test_create_with_category_and_location(self):
        f = QualityFinding(
            category=FindingCategory.BUG,
            file="src/api/auth.py",
            line=42,
            description="None일 수 있는 user를 검사 없이 역참조",
            suggestion="None 체크 추가",
        )
        assert f.category == FindingCategory.BUG
        assert f.file == "src/api/auth.py"
        assert f.line == 42

    def test_create_without_location(self):
        f = QualityFinding(
            category=FindingCategory.SMELL,
            file=None, line=None,
            description="중복 코드 블록",
            suggestion="공통 함수로 추출",
        )
        assert f.file is None and f.line is None

    def test_category_values(self):
        assert {c.value for c in FindingCategory} == {
            "bug", "vulnerability", "security", "smell", "complexity",
        }

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            QualityFinding(
                category=FindingCategory.BUG,
                description="d", suggestion="s",
                severity="critical",  # 허용 안 됨
            )


class TestReviewResultQualityFindings:
    def test_quality_findings_default_empty(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert result.quality_findings == []

    def test_quality_findings_accepted(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[
                QualityFinding(
                    category=FindingCategory.VULNERABILITY,
                    file="src/db.py", line=10,
                    description="문자열 포매팅으로 SQL 구성",
                    suggestion="파라미터 바인딩 사용",
                ),
            ],
        )
        assert len(result.quality_findings) == 1
        assert result.quality_findings[0].category == FindingCategory.VULNERABILITY
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_models.py::TestQualityFinding tests/test_models.py::TestReviewResultQualityFindings -v`
Expected: FAIL — `ImportError: cannot import name 'QualityFinding'`

- [ ] **Step 3: 모델 구현**

`src/models/review.py` 수정. `Mismatch` 클래스 뒤, `ReviewResult` 앞에 추가:

```python
class FindingCategory(str, Enum):
    BUG = "bug"
    VULNERABILITY = "vulnerability"
    SECURITY = "security"
    SMELL = "smell"
    COMPLEXITY = "complexity"


class QualityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FindingCategory
    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str
```

`ReviewResult`에 필드 추가 (`architecture_concern` 다음 줄):

```python
    quality_findings: list[QualityFinding] = Field(default_factory=list)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_models.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/models/review.py tests/test_models.py
git commit -m "feat: add QualityFinding model and quality_findings field"
```

---

## Task 2: 시스템 프롬프트에 SonarQube 검사 섹션 추가

**Files:**
- Modify: `src/review/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_prompt_builder.py`의 `TestBuildSystemPrompt`에 추가:

```python
    def test_includes_quality_findings_schema(self):
        prompt = build_system_prompt()
        assert "quality_findings" in prompt

    def test_includes_sonarqube_categories(self):
        prompt = build_system_prompt()
        for cat in ("bug", "vulnerability", "security", "smell", "complexity"):
            assert cat in prompt

    def test_quality_check_section_present(self):
        prompt = build_system_prompt()
        # 코드 품질 검사를 별도로 한다는 안내가 있어야
        assert ("코드 품질" in prompt or "SonarQube" in prompt)
```

주의: 기존 `test_states_role_is_spec_alignment_only` 가 `"critical"`, `"warning"`, `"minor"`, `"score"`, `"점수"` 단어가 프롬프트에 **없을 것**을 검사한다. 새 섹션에 그 단어들을 쓰지 말 것.

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_prompt_builder.py::TestBuildSystemPrompt -v`
Expected: FAIL — `test_includes_quality_findings_schema` 등에서 `assert "quality_findings" in prompt`

- [ ] **Step 3: 프롬프트 수정**

`src/review/prompt_builder.py`의 `SYSTEM_PROMPT` 문자열을 수정한다.

(a) `## 검토 순서`의 4번 항목(아키텍처) 다음, `## 출력 형식` 앞에 새 섹션 추가:

```
5. 모든 PR에 대해 SonarQube 스타일 코드 품질 검사를 수행한다. 발견사항을 quality_findings에 등록한다.
   - bug: null 참조, 리소스 누수, 잘못된 조건문, API 오용
   - vulnerability: SQL Injection, XSS, 하드코딩된 비밀번호, 안전하지 않은 암호화
   - security: 랜덤 함수 오용, 권한 검사 누락, 안전하지 않은 HTTP 헤더 등 (취약점 단정은 아니나 검토 필요)
   - smell: 중복 코드, 너무 긴 메서드, 죽은 코드, 나쁜 네이밍
   - complexity: 순환 복잡도·인지 복잡도 과다
   각 항목은 category, file, line, description, suggestion으로 기록한다. 발견사항이 없으면 quality_findings는 빈 배열로 둔다.
```

(b) `## 출력 형식`의 JSON 블록에 `architecture_concern` 뒤 필드 추가:

```json
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_prompt_builder.py -v`
Expected: PASS (전체 통과 — 기존 `test_states_role_is_spec_alignment_only` 포함)

- [ ] **Step 5: 커밋**

```bash
git add src/review/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat: add sonarqube-style quality check section to system prompt"
```

---

## Task 3: 결정 로직에 quality_findings 규칙 추가

**Files:**
- Modify: `src/review/decision.py`
- Test: `tests/test_decision.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_decision.py` import 라인 수정 후 테스트 추가:

```python
# import 라인 변경:
from src.models.review import (
    ReviewResult, SpecStatus, Mismatch, Decision,
    QualityFinding, FindingCategory,
)
```

```python
def _finding(category):
    return QualityFinding(
        category=category, file="x.py", line=1, description="d", suggestion="s",
    )


class TestComputeDecisionQualityFindings:
    def test_bug_finding_requests_changes(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[_finding(FindingCategory.BUG)],
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES

    def test_vulnerability_finding_requests_changes(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[_finding(FindingCategory.VULNERABILITY)],
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES

    def test_smell_only_downgrades_to_comment(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[_finding(FindingCategory.SMELL)],
        )
        assert compute_decision(result) == Decision.COMMENT

    def test_security_and_complexity_only_is_comment(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
            quality_findings=[
                _finding(FindingCategory.SECURITY),
                _finding(FindingCategory.COMPLEXITY),
            ],
        )
        assert compute_decision(result) == Decision.COMMENT

    def test_no_findings_keeps_approve(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="ok",
        )
        assert compute_decision(result) == Decision.APPROVE

    def test_spec_missing_still_request_changes_despite_smell(self):
        """기존 REQUEST_CHANGES 조건이 우선."""
        result = ReviewResult(
            spec_status=SpecStatus.MISSING, aligned=False, summary="no spec",
            quality_findings=[_finding(FindingCategory.SMELL)],
        )
        assert compute_decision(result) == Decision.REQUEST_CHANGES
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_decision.py::TestComputeDecisionQualityFindings -v`
Expected: FAIL — `test_bug_finding_requests_changes` 등에서 `APPROVE != REQUEST_CHANGES`

- [ ] **Step 3: 결정 로직 구현**

`src/review/decision.py` 전체를 다음으로 교체:

```python
from src.models.review import Decision, FindingCategory, ReviewResult, SpecStatus


_BLOCKING_CATEGORIES = {FindingCategory.BUG, FindingCategory.VULNERABILITY}


def compute_decision(result: ReviewResult) -> Decision:
    if result.spec_status == SpecStatus.MISSING:
        return Decision.REQUEST_CHANGES
    if not result.aligned:
        return Decision.REQUEST_CHANGES
    if result.architecture_concern:
        return Decision.REQUEST_CHANGES
    if any(f.category in _BLOCKING_CATEGORIES for f in result.quality_findings):
        return Decision.REQUEST_CHANGES
    if result.quality_findings:
        return Decision.COMMENT
    return Decision.APPROVE
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_decision.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/review/decision.py tests/test_decision.py
git commit -m "feat: factor quality findings into review decision"
```

---

## Task 4: 리뷰 본문에 "코드 품질 검사" 섹션 렌더링

**Files:**
- Modify: `src/github/reviewer.py`
- Test: `tests/test_reviewer.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_reviewer.py` import 라인 수정 후 테스트 추가:

```python
# import 라인 변경:
from src.models.review import (
    Decision, Mismatch, ReviewResult, SpecStatus,
    QualityFinding, FindingCategory,
)
```

```python
def _result_with_quality_findings():
    return ReviewResult(
        spec_status=SpecStatus.PRESENT, aligned=True,
        summary="스펙 부합하나 코드 품질 이슈 있음",
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="src/svc.py", line=12,
                description="None 가능 값을 검사 없이 사용", suggestion="None 체크 추가",
            ),
            QualityFinding(
                category=FindingCategory.SMELL, file=None, line=None,
                description="중복 코드 블록", suggestion="공통 함수 추출",
            ),
        ],
    )


class TestFormatReviewBodyQuality:
    def test_quality_section_lists_findings(self):
        body = format_review_body(_result_with_quality_findings())
        assert "코드 품질" in body
        assert "None 가능 값을 검사 없이 사용" in body
        assert "src/svc.py:12" in body
        assert "중복 코드 블록" in body
        # 한글 카테고리 라벨
        assert "버그" in body
        assert "코드 스멜" in body
        # bug 있으므로 판정은 Request Changes
        assert "Request Changes" in body

    def test_quality_section_shows_ok_when_empty(self):
        body = format_review_body(_result_aligned())
        assert "코드 품질" in body
        # 아키텍처와 코드 품질 둘 다 "이상 없음" 노출
        assert body.count("이상 없음") >= 2

    def test_quality_pipe_escaped(self):
        result = ReviewResult(
            spec_status=SpecStatus.PRESENT, aligned=True, summary="s",
            quality_findings=[
                QualityFinding(
                    category=FindingCategory.SMELL, file="x.py", line=1,
                    description="Use `a | b`", suggestion="Replace `|`",
                ),
            ],
        )
        body = format_review_body(result)
        assert r"a \| b" in body
```

추가로 기존 `test_no_score_no_severity_tiers` 가 `"warning"`, `"minor"`, `"critical"` 단어가 본문에 없을 것을 검사하므로, 카테고리 한글 라벨은 그 영어 단어를 쓰지 않는다 (버그/취약점/보안/코드 스멜/복잡도).

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_reviewer.py::TestFormatReviewBodyQuality -v`
Expected: FAIL — `assert "코드 품질" in body`

- [ ] **Step 3: reviewer 구현**

`src/github/reviewer.py` 수정.

(a) import에 추가:

```python
from src.models.review import Decision, FindingCategory, Mismatch, QualityFinding, ReviewResult, SpecStatus
```

(b) `_format_location` 의 시그니처를 일반화 (Mismatch와 QualityFinding 둘 다 `.file`/`.line` 보유):

```python
def _format_location(item: Mismatch | QualityFinding) -> str:
    if item.file is None:
        return "_전체 PR_"
    safe = _escape_table_cell(item.file)
    if item.line:
        return f"`{safe}:{item.line}`"
    return f"`{safe}`"
```

(c) 카테고리 한글 라벨 매핑을 `_VERDICT_LABEL` 근처에 추가:

```python
_CATEGORY_LABEL = {
    FindingCategory.BUG: "버그",
    FindingCategory.VULNERABILITY: "취약점",
    FindingCategory.SECURITY: "보안",
    FindingCategory.SMELL: "코드 스멜",
    FindingCategory.COMPLEXITY: "복잡도",
}
```

(d) `format_review_body` 의 "아키텍처 검토" 섹션 블록 다음, `### 판정` 추가 전에 코드 품질 섹션 추가:

```python
    lines.append("")
    lines.append("### 코드 품질 검사")
    if result.quality_findings:
        lines.append("| # | 분류 | 항목 | 위치 | 제안 |")
        lines.append("|---|------|------|------|------|")
        for idx, f in enumerate(result.quality_findings, 1):
            cat = _CATEGORY_LABEL[f.category]
            desc = _escape_table_cell(f.description)
            sugg = _escape_table_cell(f.suggestion)
            loc = _format_location(f)
            lines.append(f"| {idx} | {cat} | {desc} | {loc} | {sugg} |")
    else:
        lines.append("> 이상 없음")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_reviewer.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/github/reviewer.py tests/test_reviewer.py
git commit -m "feat: render code quality findings section in review body"
```

---

## Task 5: 전체 테스트 + 문서 갱신

**Files:**
- Modify: `README.md` (리뷰 항목 설명이 있으면 코드 품질 검사 추가 언급)
- Modify: `examples/review-bot.yml` 등 (필요 시 — 실제 변경 없으면 스킵)

- [ ] **Step 1: 전체 테스트 실행**

Run: `pytest -v`
Expected: PASS (전체 통과)

- [ ] **Step 2: README 확인 및 갱신**

`README.md`를 읽고, 봇이 검토하는 항목을 설명하는 문단이 있으면 "스펙 정합성 + SonarQube 스타일 코드 품질(버그·취약점·보안·코드 스멜·복잡도)" 취지로 한 줄 추가. 설명 문단이 없으면 변경 없음.

- [ ] **Step 3: 커밋 (변경 있을 때만)**

```bash
git add README.md
git commit -m "docs: mention code quality checks in README"
```

---

## Self-Review 체크

- 스펙 커버리지: 모델(Task 1) / 프롬프트(Task 2) / 결정(Task 3) / 본문 렌더링(Task 4) / 테스트·문서(Task 5) — 설계의 5개 변경 항목 모두 태스크 존재. ✅
- 플레이스홀더: 없음 — 모든 코드 블록 실제 내용. ✅
- 타입 일관성: `QualityFinding`, `FindingCategory`(BUG/VULNERABILITY/SECURITY/SMELL/COMPLEXITY), `quality_findings` 필드명 — 전 태스크 동일. `_CATEGORY_LABEL`, `_BLOCKING_CATEGORIES` 명칭 일관. ✅
- 기존 테스트 회귀 주의: `test_states_role_is_spec_alignment_only` / `test_no_score_no_severity_tiers` 가 "critical/warning/minor/score/점수" 단어를 금지 — 새 프롬프트·본문에서 회피하도록 명시. ✅
