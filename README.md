# Syscon Review Bot

PR의 **스펙 문서 품질**, **스펙·요구사항과 실제 코드 변경의 정합성**을 자동 검토하는 GitHub Action. 더불어 아키텍처 리스크와 SonarQube 스타일 코드 품질 검사(버그·취약점·보안·코드 스멜·복잡도)도 함께 수행한다.

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

> 봇은 항상 **COMMENT 이벤트**로 리뷰를 남깁니다. 판정(✅ Approved / ❌ 수정 필요)은 리뷰 본문 하단 라벨로 표시. 기본 `GITHUB_TOKEN`이 GitHub 정책상 PR APPROVE를 못 하기 때문입니다. CI 실패는 spec 문서 요건 미충족에만 사용하고, 일반 리뷰 판정(❌ 수정 필요)은 merge 차단용 exit code로 쓰지 않습니다.

## 리뷰 동작

봇은 PR마다 다음 순서로 동작합니다:

1. **스펙·요구사항을 두 위치에서 식별**:
   - PR 본문 (제목·설명에 인라인으로 작성된 요구사항)
   - PR diff에 포함된 문서 파일 (예: `spec/<기능명>/*.md`, `docs/specs/*.md`)
2. 스펙이 **없으면** → 정합성 검토와 스펙 문서 검토는 생략하고 아키텍처·코드 품질 위주로 검토
3. 스펙이 **있으면 먼저 스펙 문서 자체를 검토**:
   - 완결성: 요구사항·수용 기준·설계·작업 분해가 구현자가 판단 가능할 만큼 충분한지
   - 일관성: `requirements.md`, `design.md`, `tasks.md`/`task.md` 사이 범위·용어·동작 충돌이 없는지 (`tasks.md`와 `task.md`는 같은 task 문서 alias)
   - 검증 가능성: 테스트나 리뷰로 확인 가능한 성공/실패 조건, 예외·경계 조건이 있는지
   - 범위 명확성: 이번 PR의 적용 범위·제외 범위·후속 작업 범위가 구분되는지
   - 추적성: task가 어떤 requirement/design 항목을 구현하는지 연결 가능한지
   - 리스크 명시: 보안·권한·데이터 무결성·마이그레이션·호환성·장애/롤백 리스크가 필요한 경우 드러나는지
   - 문서 결함 1건+ → `❌ Request Changes` + `스펙 문서 검토` 섹션에 표시
4. **코드 정합성 검토**: 각 요구사항이 코드에 반영되었는지, 스펙 범위 밖 변경이 섞였는지 대조
   - 불일치 0건 → `✅ 스펙 부합` 후보
   - 불일치 1건+ → `❌ Request Changes` + 불일치 항목 표
5. **아키텍처 검토** (항상 수행): 레이어 역참조·도메인 무결성 훼손 등 명백한 구조 문제 점검.
   - 우려 0 → 본문에 "이상 없음" 표기
   - 우려 1건+ → 결정이 `❌ Request Changes`로 전환
6. **코드 품질 검사** (항상 수행, SonarQube 스타일): `bug`·`vulnerability`·`security`·`smell`·`complexity` 항목 점검.
   - 발견 0 → 본문에 "이상 없음" 표기
   - `bug`/`vulnerability` 발견 → 결정이 `❌ Request Changes`로 전환
   - 그 외(`security`/`smell`/`complexity`)만 발견 → `✅ Approved` 유지, 본문에 참고 지적으로 표시
7. **이전 봇 리뷰·사람 코멘트 참고**: 이전 커밋에서 봇이 남긴 리뷰는 재출력하지 않도록 신규/변경분만 보고하며, 마지막 봇 리뷰 이후 작성된 사람 코멘트(일반·라인)를 함께 읽어 "의도/거부" 등 의사를 반영합니다.

변경량이 1,200 가중 라인·40파일·40k tokens 중 하나를 넘으면 내부 병렬 리뷰로 전환합니다. 2,500 가중 라인·80파일·100k tokens 중 하나를 넘거나 전체 patch를 확보하지 못하면 코드 리뷰 대신 PR 분할 요청 하나를 남깁니다. 단일·병렬 방식 모두 최종 GitHub 리뷰는 하나만 게시합니다.

리뷰 본문은 `스펙 문서 검토`를 가장 먼저 표시하고, 각 finding의 `신뢰도`는 항목 마지막 줄에 함께 표시합니다.

스펙 파일 변경을 PR 리뷰 실행 조건으로 강제하려면 `.github/review-bot.yml`에서 `require_spec_files: true`를 설정합니다. 기본값은 `false`입니다.

## Configuration (옵션)

소비자 레포 루트에 `.github/review-bot.yml` 추가. 전부 선택사항:

```yaml
review:
  model: gpt-5.4-mini   # 옵션 — 미설정 시 액션 input → GPTClient 기본값 순으로 사용

# 기본값: repository tools 활성, 별도 reasoning effort 없음.
# reasoning_effort: high # 설정하면 현재 Chat Completions 경로에서 repository tools가 비활성화됨

require_spec_files: false # 옵션 — true면 spec/<기능명>/ 문서 요건 미충족 시 리뷰 차단

# Action의 trusted 비용 상한보다 낮추는 것만 가능. 높은 값은 적용되지 않음.
# reviewer/tool 호출 횟수는 고정 제한하지 않으며, 매 호출 전 누적 비용을 검사함.
cost_control:
  hard_limit_usd: "0.50"
  max_completion_tokens_per_call: 2048
  max_tool_result_tokens_per_call: 2048
  max_history_tokens: 6000

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
| `model` | no | `''` | 모델 강제 지정 (기본 trusted allowlist는 `gpt-5.4-mini`) |
| `config-path` | no | `.github/review-bot.yml` | 설정 파일 경로 |
| `max-review-cost-usd` | no | `1.00` | PR당 비용 hard cap (`1.00` 이하) |
| `max-completion-tokens` | no | `4096` | 요청당 출력 토큰 상한 |

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
