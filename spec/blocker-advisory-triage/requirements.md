# AI Review Blocker/Advisory Triage Requirements

## 배경

PR 재리뷰 과정에서 정상 workflow로는 생성되지 않는 malformed state, 조작된 timestamp/history 같은 가상 시나리오가 매번 `수정 필요`로 판정되었다. 이 finding을 모두 blocker로 처리하면서 보완 범위가 반복적으로 확대되었다.

## 요구사항

- REQ-01 (Ubiquitous): 시스템은 정상 workflow에서 재현되는 regression과 명시된 계약 위반만 blocker finding 목록에 기록해야 한다.
- REQ-02 (Unwanted behavior): finding이 인위적으로 변조된 state, malformed history 또는 조작된 timestamp에서만 발생하면, 시스템은 이를 advisory finding으로 기록해야 한다.
- REQ-03 (Ubiquitous): 시스템은 advisory finding만 존재하는 review를 `APPROVE`로 판정해야 한다.
- REQ-04 (Event-driven): 이전 review의 advisory가 해결되지 않은 채 재리뷰되면, 시스템은 정상 workflow의 blocker 근거가 새로 확인되지 않는 한 이를 blocker로 승격하지 않아야 한다.
- REQ-05 (Ubiquitous): 시스템은 review comment에서 blocker finding과 advisory finding을 구분해 표시해야 한다.
- REQ-06 (Ubiquitous): 시스템은 기존 mismatch, spec document, architecture, quality blocker 판정 계약을 유지해야 한다.

## Acceptance Criteria

- AC-01: `ReviewResult`가 `advisory_findings`를 허용하고 기본값은 빈 목록이다.
- AC-02: advisory만 포함한 `ReviewResult`의 `compute_decision()` 결과는 `Decision.APPROVE`다.
- AC-03: 기존 mismatch, spec document finding, architecture finding, bug와 vulnerability는 계속 `Decision.REQUEST_CHANGES`다.
- AC-04: system prompt가 정상 workflow 재현 가능성과 실제 계약 위반을 blocker 조건으로 명시한다.
- AC-05: system prompt가 malformed-state-only finding을 `advisory_findings`로 분류하고 재리뷰에서 자동 승격하지 않도록 명시한다.
- AC-06: formatted review body가 `참고 사항 (Advisory)` 섹션과 `✅ (Approved)` 판정을 함께 표시할 수 있다.
- AC-07: 전체 pytest suite가 통과한다.

## 제외 범위

- review 횟수를 GitHub Actions 수준에서 강제로 제한하는 기능
- confidence threshold 또는 model 변경
- 기존 review category 재설계
- SR-AMR repository의 human approval/ruleset 변경
