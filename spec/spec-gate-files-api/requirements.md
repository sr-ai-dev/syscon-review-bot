# Spec Gate Files API 요구사항

## 배경

리뷰 봇은 GitHub raw diff에서 한글 같은 비 ASCII 파일 경로를 quoted/escaped 형태로 받을 수 있다. 이 경우 로컬 raw diff 파서가 `spec/260521-기능통합/requirements.md` 같은 경로를 복원하지 못할 수 있다.

spec gate가 raw diff 파서 결과에 의존하면, PR에 유효한 spec 문서가 이미 포함되어 있어도 "spec 문서 변경이 없습니다"로 잘못 차단될 수 있다.

## 요구사항

- `require_spec_files`가 활성화된 경우, spec gate는 변경 파일명 기준으로 GitHub PR files API 결과를 사용해야 한다.
- 유효한 spec 파일이 하나도 없는 PR은 계속 차단해야 한다.
- spec 디렉터리에 `task.md` 또는 `tasks.md`만 있고 `requirements.md`와 `design.md`가 모두 없으면 차단해야 한다.
- 단일 `spec/<기능명>/` 디렉터리에 다음 중 1개 이상이 있으면 통과해야 한다.
  - `requirements.md`
  - `design.md`
- 기존 406 대형 diff fallback에서 이미 가져온 files API 응답은 재사용해야 한다.
- prompt, 모델 리뷰, 필터링, 리뷰 렌더링 동작은 변경하지 않아야 한다.

## 회귀 케이스

다음 파일을 포함한 PR은 raw diff header가 quoted octal escape sequence로 경로를 표현하더라도 spec gate를 통과해야 한다.

- `spec/260521-기능통합/requirements.md`
