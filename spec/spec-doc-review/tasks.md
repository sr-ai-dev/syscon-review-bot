# Spec Document Review 작업 목록

## 완료

- [x] `SpecDocFinding` 모델을 추가했다.
- [x] `ReviewResult`에 `spec_doc_findings` 기본 빈 배열 필드를 추가했다.
- [x] 시스템 프롬프트에 스펙 문서 검토 순서와 기준을 추가했다.
- [x] 출력 JSON 스키마에 `spec_doc_findings`를 추가했다.
- [x] `compute_decision()`이 스펙 문서 finding 존재 시 `REQUEST_CHANGES`를 반환하도록 했다.
- [x] 리뷰 본문에서 `스펙 문서 검토` 섹션을 가장 먼저 표시하도록 했다.
- [x] finding 표에서 `conf` 컬럼을 제거하고 항목 마지막 줄에 `신뢰도: <값>`을 표시하도록 했다.
- [x] postprocess가 스펙 문서 finding의 confidence threshold와 이전 리뷰 부분 해결 판정에 참여하도록 했다.
- [x] judge 프롬프트가 `spec_doc_findings`를 prior_resolved 일관성 대상에 포함하도록 했다.
- [x] README에 스펙 문서 검토 기준과 표시 방식을 문서화했다.
- [x] 모델, 판정, 후처리, 프롬프트, 렌더링 테스트를 추가했다.

## 검증

- [x] `env UV_CACHE_DIR=/private/tmp/uv-cache /opt/homebrew/bin/uv run python -m pytest`
- [x] `git diff --check`
