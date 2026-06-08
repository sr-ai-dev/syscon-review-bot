# Self Review Workflow 요구사항

## 배경

`syscon-review-bot` 저장소는 다른 소비자 저장소처럼 PR 생성 시 AI 리뷰가 실행되어야 한다.

현재 저장소에는 PR 이벤트용 GitHub Actions workflow가 없어, PR을 올려도 리뷰 봇이 자동 실행되지 않는다.

## 요구사항

- PR 이벤트에서 `sr-ai-dev/syscon-review-bot@main` 액션을 실행해야 한다.
- 새 PR, 변경 push, 재오픈, draft 해제 시 리뷰가 실행되어야 한다.
- 동일 PR의 이전 리뷰 run은 새 변경이 들어오면 취소되어야 한다.
- workflow는 PR diff와 리뷰 제출에 필요한 최소 권한을 가져야 한다.
  - `contents: read`
  - `pull-requests: write`
- OpenAI API 키는 `secrets.OPENAI_API_KEY`에서 받아야 한다.
- 액션의 기본 `github-token`과 `config-path` 입력은 그대로 사용해야 한다.

## 비목표

- 리뷰 봇 액션 구현 코드는 변경하지 않는다.
- 리뷰 설정 파일 기본값은 변경하지 않는다.
