# AI Review Output Contract Hardening Summary

## 구현 결과

- Pydantic `ReviewResult`를 OpenAI strict JSON Schema response format으로 투영한다.
- 모든 object property를 required로 만들고 `additionalProperties=false`를 적용하며
  Pydantic default keyword를 API schema에서 제거한다.
- transport/API, refusal/incomplete, response schema 오류를 각각 typed infra category로
  구분한다.
- CLI는 infra failure를 `REVIEW_INFRA_ERROR`로 표시하고 코드 finding을 만들지 않은 채
  exit `1`로 종료한다.
- invalid response 원문과 credential은 exception message 및 Step Summary에 기록하지 않는다.
- 기존 `prior_resolved` display-object normalization은 유지한다.

## 생산성·비용 경계

- 정상 no-tool primary completion: 1회
- formatting repair LLM call: 0회
- parser-triggered full review retry: 0회
- transport retry: 기존 bounded retry 유지
- blocker/advisory prompt와 일반 `REQUEST_CHANGES` exit 의미: 변경 없음

## Evidence

```text
targeted pytest: 34 passed
full pytest: 277 passed in 0.96s
git diff --check: PASS
```

## 미검증 경계

- 실제 OpenAI credential을 사용하는 live API call은 수행하지 않았다.
- GitHub-hosted Action runtime과 실제 PR comment 제출은 consumer pin/bump PR run 전까지
  `NOT_EVALUATED`다.
- 오탐률·미탐률 개선은 이 변경의 검증 대상이 아니다.
