# Syscon Review Bot

PR이 열리거나 새 커밋이 푸시되면 OpenAI GPT로 자동 코드 리뷰. Python, TypeScript, C++, Java 등 다국어 지원.

## Quick Start

대상 레포에 `.github/workflows/review.yml` 추가:

```yaml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize]

concurrency:
  group: review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/create-github-app-token@v1
        id: app-token
        with:
          app-id: ${{ secrets.REVIEW_BOT_APP_ID }}
          private-key: ${{ secrets.REVIEW_BOT_APP_PRIVATE_KEY }}
      - uses: sr-ai-dev/syscon-review-bot@main
        with:
          openai-key: ${{ secrets.OPENAI_API_KEY }}
          github-token: ${{ steps.app-token.outputs.token }}
```

레포 (또는 조직) Secrets에 세 가지 추가:
- `OPENAI_API_KEY` — OpenAI API 키
- `REVIEW_BOT_APP_ID` — GitHub App ID (아래 "GitHub App 설정" 참조)
- `REVIEW_BOT_APP_PRIVATE_KEY` — GitHub App private key (PEM 전체)

> 기본 `GITHUB_TOKEN`은 GitHub 정책상 PR APPROVE가 불가능합니다. APPROVE 결정을 실제로 반영하려면 GitHub App 토큰을 사용해야 합니다.

## GitHub App 설정 (1회)

1. **App 등록**: https://github.com/settings/apps/new (조직 단위면 조직 Settings → Developer settings → GitHub Apps → New GitHub App)
   - Name: 예) `syscon-review-bot`
   - Homepage URL: 임의
   - Webhook: **Active 체크 해제** (액션에서 직접 호출하므로 불필요)
   - **Repository permissions**:
     - Contents: Read
     - Pull requests: **Read & write**
   - "Where can this GitHub App be installed?": Only on this account (조직 내부용)
2. 등록 후 **App ID** 확인 → `REVIEW_BOT_APP_ID` secret으로 저장
3. **Generate a private key** 클릭 → 다운로드된 `.pem` 파일 전체 내용을 `REVIEW_BOT_APP_PRIVATE_KEY` secret으로 저장
4. App 상세 페이지의 **Install App**에서 대상 레포(또는 조직 전체)에 설치

## Configuration (옵션)

레포 루트에 `.github/review-bot.yml` 생성:

```yaml
review:
  language: korean
  severity_threshold: medium
  model: gpt-5.4-mini       # 옵션 — 미설정 시 액션 input의 model 사용

rules:
  architecture: true
  type_safety: true
  code_quality: true
  test_coverage: true
  performance: true
  security: true
  error_handling: true
  refactoring: true
  documentation: true

custom_rules:
  - "C++ raw pointer 직접 사용 금지, 반드시 smart pointer 사용"
  - "Python에서 mutable default argument 사용 금지"

ignore:
  files: ["*.lock", "dist/**", "**/*.generated.*"]
  extensions: [".md", ".txt"]

approve_criteria:
  max_high_issues: 0       # critical 이슈 허용 개수
  max_medium_issues: 3     # warning 이슈 허용 개수
```

## Action Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `openai-key` | yes | — | OpenAI API key |
| `github-token` | no | `${{ github.token }}` | API 인증 토큰. APPROVE 동작이 필요하면 GitHub App installation token으로 덮어쓰기 |
| `model` | no | `''` | 모델 강제 지정 |
| `config-path` | no | `.github/review-bot.yml` | 설정 파일 경로 |

## Decision Logic

서버사이드로 결정 재계산:

- `score >= 8` AND `critical == 0` AND `warning <= max_medium_issues` → **APPROVE**
- `score < 7` OR `critical > max_high_issues` → **REQUEST_CHANGES**
- 그 외 → **COMMENT**

## License

내부용.
