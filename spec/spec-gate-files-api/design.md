# Spec Gate Files API 설계

## 접근 방식

리뷰 엔진은 프롬프트 구성을 위해 기존처럼 PR diff를 가져온다. diff는 변경 patch와 리뷰 컨텍스트의 입력으로 계속 사용한다.

spec gate 판정에 한해서는 GitHub PR files API의 `filename` 값을 사용한다. GitHub는 이 API에서 디코딩된 저장소 경로를 반환하므로, 한글 spec 경로도 정상적인 `spec/<기능명>/...` 형태로 확인할 수 있다.

## 흐름

1. PR 메타데이터와 저장소 리뷰 설정을 로드한다.
2. raw PR diff를 가져와 `FileDiff` 목록으로 파싱한다.
3. raw diff가 너무 커서 GitHub가 406을 반환하면 PR files API를 가져와 `FileDiff` 목록을 구성한다.
4. `require_spec_files`가 꺼져 있으면 spec gate 검사를 건너뛴다.
5. `require_spec_files`가 켜져 있으면 다음 순서로 검사한다.
   - 406 fallback에서 이미 가져온 PR files API 응답이 있으면 재사용한다.
   - 없으면 PR files API를 새로 가져온다.
   - API의 `filename` 값으로 `check_spec_files()`를 실행한다.
6. gate가 실패하면 기존 spec gate 리뷰를 남기고 종료한다.
7. gate가 통과하면 필터링, hunk 확장, 프롬프트 구성, 모델 리뷰를 계속 진행한다.

## Spec 문서 규칙

각 `spec/<기능명>/` 디렉터리는 다음 조합을 만족해야 한다.

- `requirements.md` 또는 `design.md` 중 1개 이상이 필요하다.
- `task.md` 또는 `tasks.md`는 spec 디렉터리 변경으로 검사 대상에 포함되지만 필수는 아니다.

예시는 다음과 같다.

- `requirements.md`: 통과
- `design.md`: 통과
- `requirements.md` + `design.md`: 통과
- `task.md`만 있음: 실패
- `tasks.md`만 있음: 실패

## 비목표

- raw diff 파서가 모든 quoted Git path 형식을 디코딩하도록 확장하지 않는다.
- ignored file 필터링 정책은 변경하지 않는다.
- spec gate가 꺼져 있을 때 추가 GitHub API 호출을 만들지 않는다.

## 테스트 전략

- 기존 spec gate 차단/통과 테스트를 새 문서 규칙에 맞게 유지한다.
- raw diff에는 escaped 한글 spec 경로가 있고 files API에는 디코딩된 `spec/...` 경로가 있는 회귀 테스트를 추가한다.
- 회귀 테스트가 spec gate 차단 리뷰를 제출하지 않고 모델 리뷰 단계까지 진행하는지 검증한다.
