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
      - uses: sr-ai-dev/syscon-review-bot@main
        with:
          openai-key: ${{ secrets.OPENAI_API_KEY }}
```

레포 (또는 조직) Secrets에 `OPENAI_API_KEY` 추가하면 끝.

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
| `github-token` | no | `${{ github.token }}` | Posting 권한 (자동) |
| `model` | no | `''` | 모델 강제 지정 |
| `config-path` | no | `.github/review-bot.yml` | 설정 파일 경로 |

## Decision Logic

서버사이드로 결정 재계산:

- `score >= 9` AND `critical == 0` AND `warning <= max_medium_issues` → **APPROVE**
- `score < 7` OR `critical > max_high_issues` → **REQUEST_CHANGES**
- 그 외 → **COMMENT**

## License

내부용.
