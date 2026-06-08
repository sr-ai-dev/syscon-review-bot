# Agent 작업 지침

이 파일은 이 저장소에서 작업하는 Codex, Claude, 기타 agent의 공통 지침이다. 하위 디렉터리에 더 구체적인 `AGENTS.md`가 있으면 그 파일이 해당 범위에서 우선한다.

## 브랜치 전략

### 주요 브랜치

| 브랜치 | 역할 | 비고 |
| --- | --- | --- |
| `develop` | 통합 중심. 모든 로봇 공통 기능·알고리즘 집결 | 공통 기술 축 |
| `dev/<prj명>` | 프로젝트별 개발 | 프로젝트 전용 |
| `release/<prj명>` | 배포. 로봇 탑재 대상, 가장 안정적 | 검증 완료 코드만 머지 |
| `main` | CI·버전 자동화 호환 대상 | 명시 요청 없으면 작업/PR 기본 대상 아님 |

### 작업 브랜치

| 패턴 | 용도 | 생성 기준 브랜치 | PR 대상 | 후속 반영 |
| --- | --- | --- | --- | --- |
| `feature/develop/<name>` | `develop` 기준 신규 기능 | `develop` | `develop` | 없음 |
| `bugfix/develop/<name>` | `develop` 기준 버그 수정 | `develop` | `develop` | 없음 |
| `feature/<prj명>/<name>` | 프로젝트 전용 기능 | `dev/<prj명>` | `dev/<prj명>` | 없음 |
| `bugfix/<prj명>/<name>` | 프로젝트 전용 버그 수정 | `dev/<prj명>` | `dev/<prj명>` | 없음 |
| `hotfix/<prj명>/<name>` | 배포 후 긴급 현장 이슈 | `release/<prj명>` | `release/<prj명>` | `dev/<prj명>` 역반영, 공통 영향 시 `develop` 반영 |

- 브랜치 생성 네이밍은 GitHub ruleset이 강제한다.
- 작업 브랜치는 `feature/<prj명>/<name>`, `bugfix/<prj명>/<name>`, `hotfix/<prj명>/<name>` 형식만 허용된다.
- 하위 프로젝트가 별도 명시되지 않았거나 생성 기준 브랜치/PR 대상이 `develop`이면 `<prj명>`은 `develop`을 사용한다.
- 예: `feature/develop/<name>`, `bugfix/develop/<name>`.
- PR source/target 흐름은 위 표의 정책을 따른다.
- 현재 `.github/scripts/validate-pr-branch-flow.sh`는 rollout 전까지 항상 성공하도록 비활성화되어 있으므로 리뷰 시 PR source/target을 수동 확인한다.

## 개발 워크플로우

모든 개발 작업은 superpowers 기반 워크플로우를 따른다. Codex 세션에서도 Claude와 동일한 절차를 따른다. 동일 이름의 스킬이 직접 노출되지 않더라도 아래 순서를 기준으로 수행한다.

1. `brainstorming`: 요구사항 정리
2. `writing-plans`: 설계·구현 계획
3. `tasks`: 태스크 분해
4. `test-driven-development`: TDD 구현
5. PR 제출

코드만 바로 작성하지 않는다. 구현 전에 `tasks.md`와 `requirements.md` 또는 `design.md` 중 최소 1개를 먼저 산출한다.

### Spec 문서 생성 기준

- 기능 추가·버그 수정·동작 변경 시 `spec/<기능명>/requirements.md`를 작성한다.
- 구조 변경·다단계 구현·영향 범위가 큰 변경 시 `spec/<기능명>/design.md`를 작성한다.
- 모든 개발 작업에서 `spec/<기능명>/tasks.md`를 작성한다.
- PR 제출 전 `spec/<기능명>/tasks.md`가 포함됐고, `requirements.md`와 `design.md` 중 최소 1개 이상이 변경 사항에 포함됐는지 확인한다.

## 요구사항 수집 게이트

사용자가 기능 추가·버그 수정·동작 변경을 요청하면, 구현 전에 변경 사유와 기대 동작을 요구사항으로 확정한다.

- 요청에 문제 원인, 고객사·작업자 요청 배경, 기대 동작이 포함된 경우, 그 내용을 바탕으로 `spec/<기능명>/requirements.md`를 작성한다.
- 요청에 변경 사유나 기대 동작이 부족한 경우, 바로 구현하지 않고 다음을 먼저 질문한다.
  - 현재 무엇이 잘못됐는지
  - 어떻게 바뀌어야 하는지
  - 누가/왜 요청했는지
- 질문으로 확보한 답변은 대화에만 남기지 않고 `requirements.md`에 요구사항·배경·성공 기준으로 기록한다.
- 구현은 `tasks.md`가 작성되고, `requirements.md`와 `design.md` 중 1개 이상이 작성된 뒤 시작한다.

## 요구사항 작성: EARS notation

`requirements.md` 작성 시 EARS(Easy Approach to Requirements Syntax) 패턴을 사용한다.

- Ubiquitous: `시스템은 [행위]해야 한다`
- Event-driven: `[이벤트] 발생 시, 시스템은 [행위]해야 한다`
- State-driven: `[상태]인 동안, 시스템은 [행위]해야 한다`
- Unwanted behavior: `[조건] 발생하면, 시스템은 [행위]해야 한다`
- Optional: `[기능]이 활성화된 경우, 시스템은 [행위]해야 한다`

각 요구사항은 하나의 EARS 문장으로 표현한다. `적절히`, `빠르게` 같은 모호한 서술은 금지한다.

## 개발 원칙 체크리스트

작업 시작 전 아래 원칙을 기준으로 삼는다.

### DDD(도메인 주도 설계)

- 도메인 모델 중심으로 설계한다.
- 의존성은 `domain` → `application` → `infrastructure` 단방향으로 유지한다.
- 유비쿼터스 언어를 사용한다.
- 도메인 로직은 엔티티와 도메인 서비스에 집중한다.

### TDD(테스트 주도 개발)

- 비즈니스 로직 변경 시 테스트를 먼저 작성한 뒤 구현하고 리팩토링한다.
- 새 기능 추가 시 테스트 코드를 선행한다.
- 버그 수정 시 재현 테스트를 먼저 작성한다.
- 프레젠테이션 레이어, UI, 스타일링 변경만 있는 경우 TDD는 생략할 수 있다.

### No Fallback

- 요청하지 않은 fallback 또는 폴백 로직을 추가하지 않는다.
- 기본값 대체, 조건부 우회, silent fail 같은 임의 안전장치를 추가하지 않는다.
- 실패해야 하는 상황은 실패로 명확히 드러나게 한다.

### Graceful 예외처리

- 모든 예외는 명시적으로 처리한다.
- 예외를 무시하거나 삼키지 않는다.
- 에러 메시지에는 원인과 컨텍스트를 포함한다.
- `try-catch` 사용 시 적절히 로깅하고 재throw하거나 사용자 피드백을 제공한다.

### 문서화

- 새 기능 또는 기능 변경 시 요구사항 문서를 추가하거나 갱신한다.
- 아키텍처 또는 도메인 구조 변경 시 아키텍처 문서를 추가하거나 갱신한다.
- 문서와 구현은 항상 일치해야 한다.
- 문서와 구현 불일치는 결함으로 취급한다.
- UI, 스타일, 단순 리팩토링은 문서 갱신을 생략할 수 있다.

### 절대 금지 사항

- 설계 내용을 임의 변경하지 않고 승인된 plan 그대로 구현한다.
- thin wrapper, 어댑터, 역호환 레이어를 임의로 추가하지 않는다.
- 임시·점진적 변경을 임의로 만들지 않는다.
- plan을 임의 변경하지 않는다.
