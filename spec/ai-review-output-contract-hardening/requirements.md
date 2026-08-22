# AI Review Output Contract Hardening Requirements

## 배경

AI review는 PR workflow에서 실행되지만, 현재 GPT 응답은 `json_object`와 수동 parsing에
의존한다. schema 오류는 코드 finding과 구분되지 않은 일반 exception으로 끝나며,
formatting repair나 전체 review 재실행을 추가하면 PR당 비용과 지연이 증가할 수 있다.

이번 변경은 정상 review의 LLM 호출 수를 늘리지 않고 출력 계약과 infra 오류 식별만
강화한다.

## 요구사항

- AIO-REQ-01: 시스템은 GPT 최종 응답에 Pydantic `ReviewResult`에서 생성한 strict
  JSON Schema response format을 사용해야 한다.
- AIO-REQ-02: 정상 PR 한 건의 primary AI review는 기존과 동일하게 최종 review
  generation 1회로 끝나야 한다.
- AIO-REQ-03: 시스템은 schema 복구를 위한 formatting LLM call과 parser-triggered
  full review retry를 수행하지 않아야 한다.
- AIO-REQ-04: OpenAI transport/API 오류, refusal/incomplete 응답, response schema
  오류를 typed infra category로 구분해야 한다.
- AIO-REQ-05: infra 오류가 발생하면 시스템은 코드 finding을 생성하지 않고
  `REVIEW_INFRA_ERROR`를 기록하며 non-zero로 종료해야 한다.
- AIO-REQ-06: 일반 AI `REQUEST_CHANGES`는 기존대로 review comment 판단이며 spec gate가
  통과하면 Action exit code를 실패시키지 않아야 한다.
- AIO-REQ-07: `prior_resolved`의 알려진 display-only object 변형 normalization은
  유지하되 semantic finding field를 임의 coercion하지 않아야 한다.
- AIO-REQ-08: infra 오류 메시지와 GitHub Step Summary에는 model response 원문,
  PR diff, credential을 포함하지 않아야 한다.
- AIO-REQ-09: 기존 OpenAI transport 오류 bounded retry 정책은 유지하고 schema 오류에는
  적용하지 않아야 한다.
- AIO-REQ-10: blocker/advisory 분류와 AI finding의 merge-blocking 의미는 이번 변경에서
  바꾸지 않아야 한다.

## Acceptance Criteria

- AIO-AC-01: OpenAI request의 `response_format.type`은 `json_schema`이고 `strict=true`다.
- AIO-AC-02: generated schema의 모든 object는 `additionalProperties=false`이고 모든
  property가 required이며 unsupported `default` keyword가 제거된다.
- AIO-AC-03: 정상 응답은 기존 `ReviewResult`와 동일하게 parsing된다.
- AIO-AC-04: invalid JSON/Pydantic mismatch는 `RESPONSE_SCHEMA_ERROR` category의
  `ReviewInfraError`를 발생시킨다.
- AIO-AC-05: refusal, length/content-filter incomplete, max tool iteration 소진은
  `OPENAI_RESPONSE_INCOMPLETE`로 구분된다.
- AIO-AC-06: retry 후에도 실패한 OpenAI transport/API 오류는
  `OPENAI_TRANSPORT_ERROR`로 구분된다.
- AIO-AC-07: CLI는 typed infra 오류에 대해 exit `1`과 안전한
  `REVIEW_INFRA_ERROR` summary를 남긴다.
- AIO-AC-08: 기존 일반 `REQUEST_CHANGES` exit `0`, spec gate failure exit `1` 계약이
  회귀하지 않는다.
- AIO-AC-09: targeted tests와 전체 pytest suite가 PASS한다.

## 제외 범위

- formatting repair LLM
- parser 오류로 인한 전체 review 자동 retry
- AI finding의 required merge blocker 승격
- 대규모 golden-set 평가 플랫폼
- model 변경
- Responses API migration
