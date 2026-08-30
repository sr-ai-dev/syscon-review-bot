# Composite Action Dependency Pin Tasks

## Task 1: RED

- `action.yml`의 모든 external `uses:`가 full SHA인지 검사하는 manifest test를 추가한다.
- 현재 `actions/setup-python@v5` 때문에 test가 실패하는지 확인한다.

## Task 2: GREEN

- GitHub `actions/setup-python` v5 tag가 가리키는 commit SHA로 reference를 고정한다.
- focused manifest test를 다시 실행한다.

## Task 3: Regression

- 전체 pytest suite와 `git diff --check`를 실행한다.
- 변경이 manifest, spec, contract test로 제한되는지 검토한다.

## Task 4: Consumer 확인

- fix PR을 `main`에 병합한다.
- OpsTool workflow가 review bot의 새 merge SHA를 사용하도록 갱신한다.
- OpsTool PR의 required `review` check가 PASS하는지 확인한다.
