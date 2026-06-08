# Self Review Workflow 작업 목록

## 완료

- [x] `.github/workflows/review.yml`을 추가했다.
- [x] `pull_request` 이벤트에서 `opened`, `synchronize`, `reopened`, `ready_for_review` 타입을 처리하도록 했다.
- [x] PR별 concurrency group을 설정하고 `cancel-in-progress`를 활성화했다.
- [x] workflow 권한을 `contents: read`, `pull-requests: write`로 제한했다.
- [x] `sr-ai-dev/syscon-review-bot@main` 액션에 `secrets.OPENAI_API_KEY`를 전달했다.

## 검증

- [x] `.github/workflows/review.yml` YAML parse를 확인했다.
