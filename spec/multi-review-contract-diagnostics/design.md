# 설계

## 범위

확인된 프롬프트/스키마 충돌과 진단 누락을 수정한다. 기존 파일 소유권 검증, 병합 불변식, 비용 정책과 도구 반복 정책은 유지한다.

## 프롬프트

- 검토 기준과 출력 계약을 명시적으로 구성하여 단일 리뷰에는 ReviewResult, 분할 분석에는 ReviewPartial을 사용한다.
- ReviewPartial의 findings/category 표현에 맞춰 분석 프롬프트를 구성한다. 최종 결과 배열에 쓰라는 상충 지시를 남기지 않는다.
- shard와 global 모두 같은 분석 출력 계약을 사용한다. 참고 파일은 담당 파일과 구분하며 기존 범위 검증과 일치시킨다.
- 프롬프트를 임의 문자열 자르기나 실패 시 대체로 변환하지 않는다.

## 오류 진단

- ReviewInfraError에 선택적인 stage와 unit_id 문맥을 추가한다. 기존 category와 safe_message는 유지한다.
- pipeline의 single, analysis, synthesis 경계에서 ReviewInfraError에 문맥을 붙이고 재전파한다. analysis의 unit_id는 응답 값이 아닌 실행 계획 값을 사용한다.
- CLI는 category와 reason/stage/unit_id 진단을 기록한다. 진단은 줄바꿈을 이스케이프한 JSON으로 로그에 표시하고 HTML 이스케이프하여 Actions 요약에 표시한다.
- 예외 체인과 응답 원문은 출력하지 않는다. 실패 종료와 병렬 작업 취소 및 비용 예약 정리를 유지한다.

## 검증

- 프롬프트 및 실제 pipeline 요청을 검사하는 회귀 테스트.
- 기존 오류 객체와 새 문맥 진단의 CLI 회귀 테스트.
- 파싱 실패, 잘못된 unit/coverage/scope 및 synthesis 불변식 실패의 문맥 전파 테스트.
- 모의 응답을 사용하는 로컬 테스트이며 유료 AI 요청이나 GitHub 리뷰 게시를 수행하지 않는다.
