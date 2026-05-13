# SonarQube 스타일 코드 품질 검사 추가 — 설계

날짜: 2026-05-13

## 배경

현재 리뷰 봇은 **스펙 정합성만** 검토한다 (PR 명시 목적 vs 실제 코드 변경). 코드 스타일·리팩토링·성능·보안·테스트 커버리지는 명시적으로 검토 대상에서 제외돼 있다.

여기에 SonarQube 주요 검사 항목(버그, 취약점, 보안 핫스팟, 코드 스멜, 복잡도)을 추가해, 한 번의 LLM 호출로 스펙 정합성 + 코드 품질을 함께 검토한다.

## 범위

- LLM 한 번 호출로 둘 다 처리. 별도 리뷰 모드 만들지 않음.
- 코드 품질 발견사항은 기존 `mismatches`와 **별도 필드** `quality_findings`로 분리.
- 구조 변경 최소: 새 모델 1개, `ReviewResult` 필드 1개, 기존 패턴 유지.
- Coverage·Duplications·Technical Debt는 diff만으로 평가 곤란 → 제외.

## 변경 사항

### 1. `src/models/review.py`

```python
class FindingCategory(str, Enum):
    BUG = "bug"
    VULNERABILITY = "vulnerability"
    SECURITY = "security"        # 보안 핫스팟
    SMELL = "smell"              # 코드 스멜
    COMPLEXITY = "complexity"


class QualityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FindingCategory
    file: str | None = None
    line: int | None = None
    description: str
    suggestion: str
```

`ReviewResult`에 추가:

```python
quality_findings: list[QualityFinding] = Field(default_factory=list)
```

### 2. `src/review/prompt_builder.py`

`SYSTEM_PROMPT`에 검사 섹션 추가 (JSON 형식 설명 전):

```
## SonarQube 스타일 코드 품질 검사

스펙 정합성 검토와 별도로 아래 항목을 검사하여 quality_findings에 등록한다.

- bug: null 참조, 리소스 누수, 잘못된 조건문, API 오용
- vulnerability: SQL Injection, XSS, 하드코딩 비밀번호, 안전하지 않은 암호화
- security: 랜덤 함수 오용, 권한 검사 누락, 안전하지 않은 HTTP 헤더 (취약점 단정 아닌 검토 필요 항목)
- smell: 중복 코드, 너무 긴 메서드, 죽은 코드, 나쁜 네이밍
- complexity: 순환 복잡도·인지 복잡도 과다

발견사항 없으면 quality_findings는 빈 배열로 둔다.
```

JSON 출력 형식에 `quality_findings` 배열 추가:

```json
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

### 3. `src/review/decision.py`

`compute_decision`에 규칙 추가 (기존 스펙/아키텍처 검사 뒤):

- `quality_findings` 중 `category in {bug, vulnerability}` 존재 → `REQUEST_CHANGES`
- 그 외 `quality_findings` 존재 (security/smell/complexity만) + 스펙·아키텍처 통과 → `COMMENT`
- `quality_findings` 비어 있으면 → 기존 로직 그대로 (`APPROVE`)

우선순위: 기존 `REQUEST_CHANGES` 조건(spec missing / not aligned / architecture_concern)이 우선. quality로 인한 `COMMENT`는 그 조건들을 통과했을 때만 적용.

### 4. `src/github/reviewer.py`

`format_review_body`에 "코드 품질 검사" 섹션 추가 (아키텍처 검토 섹션 뒤, 판정 앞):

- `quality_findings` 있으면 테이블: `| # | 카테고리 | 항목 | 위치 | 제안 |`
  - 카테고리는 한글 라벨 매핑 (bug → 버그, vulnerability → 취약점, security → 보안, smell → 코드 스멜, complexity → 복잡도)
  - 위치 포맷은 기존 `_format_location` 재사용 (인자 타입을 `Mismatch | QualityFinding`로 일반화하거나 `.file`/`.line` 덕타이핑)
- 없으면 `> 이상 없음`

### 5. 테스트 (TDD — 비즈니스 로직 변경이므로 먼저 작성)

- `tests/test_models.py`: `QualityFinding` 필드 검증, `extra="forbid"`, `ReviewResult.quality_findings` 기본 빈 배열
- `tests/test_decision.py`:
  - bug finding 존재 → `REQUEST_CHANGES`
  - vulnerability finding 존재 → `REQUEST_CHANGES`
  - smell finding만 존재 + 스펙 통과 → `COMMENT`
  - quality_findings 비어있음 → 기존 동작 (`APPROVE`)
  - spec missing + smell finding → 여전히 `REQUEST_CHANGES` (기존 우선)
- `tests/test_prompt_builder.py`: `build_system_prompt()` 결과에 `quality_findings`, `bug`, `vulnerability` 키워드 포함
- `tests/test_reviewer.py`: `format_review_body`에 quality_findings 렌더링 (테이블 행, 카테고리 한글 라벨), 빈 경우 "이상 없음"

## 비범위 (YAGNI)

- 카테고리별 집계/메트릭
- severity 레벨 (blocker/critical/major/minor)
- Quality Gate 임계치 설정
- 언어별 룰 분기
