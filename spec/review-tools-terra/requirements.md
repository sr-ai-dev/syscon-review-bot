# 리뷰 도구 활성화 및 Terra 전환 요구사항

## 배경

기본 설정은 `enable_tool_use=true`와 `reasoning_effort=high`를 동시에 사용한다. Chat Completions 경로는 reasoning effort가 설정되면 저장소 조회 도구를 비활성화하므로, 리뷰가 관련 파일을 확인하지 못하고 오탐 또는 미탐을 만들 수 있다. 기본 모델도 `gpt-5.4-mini`에 고정되어 있다.

## 요구사항

- 시스템은 기본 리뷰 모델로 `gpt-5.6-terra`를 사용해야 한다.
- 저장소 도구 사용이 기본 활성화된 경우, 시스템은 기본 설정에서 `read_file`과 `grep` 도구 호출을 허용해야 한다.
- 사용자가 `reasoning_effort`를 명시한 경우, 시스템은 기존 Chat Completions 동작대로 reasoning 경로를 사용해야 한다.
- 사용자가 모델 또는 reasoning 설정을 명시한 경우, 시스템은 해당 설정을 기본값보다 우선해야 한다.
- 기본값 변경 시, 시스템은 README와 예제 설정에 동일한 모델 및 reasoning 동작을 표시해야 한다.

## 성공 기준

- 인자 없이 생성한 `GPTClient`가 `gpt-5.6-terra`를 호출한다.
- 기본 `ReviewConfig`가 tool-use 경로와 충돌하지 않는 reasoning 값을 제공한다.
- 명시적 `reasoning_effort=high` 동작의 기존 테스트는 유지된다.
- 전체 테스트가 통과한다.
