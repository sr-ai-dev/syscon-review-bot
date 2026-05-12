# Syscon Review Bot

PR이 명시한 **스펙·요구사항**과 실제 코드 변경의 정합성을 자동 검토하는 GitHub Action. 코드 스타일·리팩토링·성능 등은 검토 대상이 아니다.

## Quick Start

대상 레포에 `.github/workflows/review.yml` 추가:

```yaml
name: Spec Alignment Review

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

> 봇은 항상 **COMMENT 이벤트**로 리뷰를 남깁니다. 판정(✅ 스펙 부합 / ❌ 수정 필요)은 리뷰 본문 하단 라벨로 표시. 기본 `GITHUB_TOKEN`이 GitHub 정책상 PR APPROVE를 못 하기 때문이며, 실제 머지 차단/승인은 사람이 보고 결정.

## 정합성 검토 동작

봇은 PR마다 다음 순서로 동작합니다:

1. **스펙·요구사항을 두 위치에서 식별**:
   - PR 본문 (제목·설명에 인라인으로 작성된 요구사항)
   - PR diff에 포함된 문서 파일 (예: `docs/specs/*.md`)
2. 스펙이 **없으면** → `❌ Request Changes`, 본문에 "스펙 첨부 필수" 안내
3. 스펙이 **있으면** → 각 요구사항이 코드에 반영되었는지, 스펙 범위 밖 변경이 섞였는지 대조
   - 불일치 0건 → `✅ 스펙 부합` 후보
   - 불일치 1건+ → `❌ Request Changes` + 불일치 항목 표
4. **아키텍처 검토** (항상 수행): 레이어 역참조·도메인 무결성 훼손 등 명백한 구조 문제 점검.
   - 우려 0 → 본문에 "이상 없음" 표기
   - 우려 1건+ → 결정이 `❌ Request Changes`로 전환

## Configuration (옵션)

소비자 레포 루트에 `.github/review-bot.yml` 추가. 전부 선택사항:

```yaml
review:
  model: gpt-5.4-mini    # 옵션 — 미설정 시 액션 input의 model 사용

ignore:                  # 정합성 검토 대상에서 제외할 파일
  files: ["*.lock", "dist/**", "**/*.generated.*"]
  # extensions에 `.md`는 넣지 말 것 — 스펙 문서가 .md인 경우 봇이 읽지 못함
  extensions: [".txt"]
```

## Action Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `openai-key` | yes | — | OpenAI API key |
| `github-token` | no | `${{ github.token }}` | API 인증 토큰 (자동) |
| `model` | no | `''` | 모델 강제 지정 |
| `config-path` | no | `.github/review-bot.yml` | 설정 파일 경로 |

## 로컬 디버깅 (Dry Run)

GPT/submit 호출 없이 봇이 GPT에 보낼 프롬프트만 stdout으로 덤프:

```bash
cp .env.example .env  # 값 채우기 (PR payload는 gh로 받아 파일로 저장)
set -a; source .env; set +a
REVIEW_DRY_RUN=1 .venv/bin/python -m src.cli
```

프롬프트 조립 로직 변경 시 실제로 GPT가 받을 입력이 의도대로 들어가는지 확인할 때 사용.

## License

내부용.
