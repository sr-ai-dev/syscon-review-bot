# Agent Guidelines 요구사항

## 배경

프로젝트 공통 작업 규칙이 대화에만 남아 있으면 Codex, Claude, GitHub PR 리뷰 흐름에서 브랜치 전략과 superpowers 기반 개발 절차가 일관되게 적용되지 않는다. 루트 `AGENTS.md`에 공통 지침을 두어 모든 agent 세션이 같은 브랜치, spec, TDD, PR 기준을 따르도록 한다.

## 요구사항

- 시스템은 루트 `AGENTS.md`에서 주요 브랜치별 역할을 설명해야 한다.
- 시스템은 루트 `AGENTS.md`에서 작업 브랜치 패턴, 생성 기준 브랜치, PR 대상을 설명해야 한다.
- 프로젝트 하위명이 명시되지 않았거나 생성 기준 브랜치 또는 PR 대상이 `develop`인 경우, 시스템은 `<prj명>`을 `develop`으로 사용하도록 안내해야 한다.
- `hotfix/<prj명>/<name>` 작업이 완료된 경우, 시스템은 `release/<prj명>` 머지 후 `dev/<prj명>`으로 역반영하고 공통 영향이 있으면 `develop`에도 반영하도록 안내해야 한다.
- `.github/scripts/validate-pr-branch-flow.sh`가 rollout 전 비활성화된 동안, 시스템은 PR source/target 흐름을 리뷰에서 수동 확인하도록 안내해야 한다.
- 기능 추가, 버그 수정, 동작 변경 요청 발생 시, 시스템은 구현 전에 변경 사유, 기대 동작, 요청 배경을 요구사항으로 확정하도록 안내해야 한다.
- 변경 사유 또는 기대 동작이 부족한 경우, 시스템은 구현 전에 현재 문제, 변경 기대값, 요청자와 요청 배경을 질문하도록 안내해야 한다.
- 요구사항 답변을 확보한 경우, 시스템은 답변을 `spec/<기능명>/requirements.md`의 요구사항, 배경, 성공 기준에 기록하도록 안내해야 한다.
- 모든 개발 작업에서, 시스템은 구현 전에 `spec/<기능명>/tasks.md`를 작성하도록 안내해야 한다.
- 기능 추가, 버그 수정, 동작 변경 작업에서, 시스템은 구현 전에 `spec/<기능명>/requirements.md` 또는 `spec/<기능명>/design.md` 중 최소 1개를 작성하도록 안내해야 한다.
- `requirements.md` 작성 시, 시스템은 각 요구사항을 EARS 문장으로 표현하도록 안내해야 한다.
- 비즈니스 로직 변경 시, 시스템은 실패 테스트를 먼저 작성하고 구현 후 테스트를 통과시키도록 안내해야 한다.
- UI 또는 스타일만 변경하는 경우, 시스템은 TDD를 선택 사항으로 안내해야 한다.
- PR 생성 전, 시스템은 변경 사항에 `tasks.md`와 `requirements.md` 또는 `design.md` 중 최소 1개가 포함됐는지 확인하도록 안내해야 한다.
- 시스템은 루트 `AGENTS.md`에 DDD, TDD, No Fallback, Graceful 예외처리, 문서화, 절대 금지 사항을 직접 포함해야 한다.

## 성공 기준

- 루트 `AGENTS.md`가 브랜치 전략, 작업 브랜치 규칙, PR 흐름, superpowers 기반 개발 워크플로우, 요구사항 수집 게이트, EARS 요구사항 작성, 개발 원칙 본문을 포함한다.
- `spec/agent-guidelines/tasks.md`가 변경 작업을 추적한다.
- `spec/agent-guidelines/requirements.md`가 EARS 기반 요구사항을 포함한다.
