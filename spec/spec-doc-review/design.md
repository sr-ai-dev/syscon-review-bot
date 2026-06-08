# Spec Document Review 설계

## 접근 방식

스펙 문서 검토를 기존 코드 정합성 mismatch와 분리한다. 코드가 스펙과 다른 문제는 `mismatches`에 유지하고, 스펙 문서 자체의 결함은 새 `spec_doc_findings` 필드에 담는다.

리뷰 본문은 사용자가 먼저 문서 문제를 확인할 수 있도록 `스펙 문서 검토` 섹션을 summary 바로 다음에 렌더링한다.

## 모델

`src/models/review.py`에 `SpecDocFinding` 모델을 추가한다.

- `file: str | None`
- `line: int | None`
- `description: str`
- `suggestion: str`
- `confidence: int`

`ReviewResult`에는 `spec_doc_findings: list[SpecDocFinding]`를 추가하고 기본값은 빈 배열로 둔다. 이렇게 하면 기존 LLM 응답에 새 필드가 없어도 파싱이 계속 동작한다.

## 프롬프트

시스템 프롬프트의 검토 순서는 다음 순서를 따른다.

1. 스펙·요구사항 식별
2. 스펙 문서 자체 검토
3. 코드 정합성 검토
4. 아키텍처 검토
5. 코드 품질 검사

스펙 문서 검토 기준은 다음과 같다.

- 완결성: 요구사항, 수용 기준, 설계, 작업 분해가 충분한가
- 일관성: requirements/design/tasks 사이 범위·용어·동작 충돌이 없는가
- 검증 가능성: 테스트나 리뷰로 확인 가능한 성공/실패 조건이 있는가
- 범위 명확성: 적용 범위, 제외 범위, 후속 작업 범위가 구분되는가
- 추적성: task가 requirement/design 항목과 연결되는가
- 리스크 명시: 필요한 보안·권한·데이터·마이그레이션·호환성·롤백 리스크가 드러나는가

## 판정

`compute_decision()`은 다음 조건 중 하나라도 만족하면 `REQUEST_CHANGES`를 반환한다.

- spec missing
- mismatch 존재
- spec_doc_findings 존재
- architecture finding 존재
- bug/vulnerability quality finding 존재

security/smell/complexity만 있는 기존 quality finding 정책은 유지한다.

## 리뷰 본문

`format_review_body()`는 다음 순서로 섹션을 렌더링한다.

1. `스펙 문서 검토`
2. `스펙과 불일치`
3. `이전 리뷰 상태`
4. `아키텍처 검토`
5. `코드 품질 검사`
6. `판정`

finding 표는 `conf` 컬럼을 별도로 만들지 않는다. 항목 셀 안에 다음 형태로 메타데이터를 함께 표시한다.

```md
설명<br>위치: `path:line`<br>신뢰도: 86
```

## 후처리와 judge

postprocess는 `spec_doc_findings`에도 confidence threshold를 적용한다. 이전 리뷰 항목과 현재 finding의 주제 중복을 판단할 때도 스펙 문서 finding 설명을 포함한다.

judge 프롬프트는 `prior_resolved` 일관성 확인 대상에 `spec_doc_findings`를 포함한다.

## 문서화

README의 리뷰 동작 설명에 스펙 문서 검토 기준, 표시 순서, 신뢰도 표시 방식을 추가한다.
