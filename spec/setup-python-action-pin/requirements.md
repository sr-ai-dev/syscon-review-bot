# Composite Action Dependency Pin Requirements

## 배경

OpsTool은 GitHub Actions dependency를 full-length commit SHA로 제한한다. Review bot의
`action.yml`이 `actions/setup-python@v5` tag를 사용해 consumer PR의 AI review job이 실제
리뷰 전에 setup 단계에서 실패한다.

## 요구사항

- SAP-REQ-01: composite action이 외부 GitHub Action을 참조할 때 시스템은 full-length
  40자리 commit SHA를 사용해야 한다.
- SAP-REQ-02: `actions/setup-python`의 동작 version은 기존 v5 계열을 유지해야 한다.
- SAP-REQ-03: consumer repository의 SHA-only action policy에서 review job setup이
  dependency pin 위반으로 실패하지 않아야 한다.
- SAP-REQ-04: review bot의 Python version, dependency 설치, review 실행 계약은 변경하지
  않아야 한다.

## Acceptance Criteria

- `action.yml`의 모든 `uses:` dependency가 40자리 lowercase hexadecimal SHA를 사용한다.
- manifest contract test가 기존 tag reference에서 RED이고 pinned reference에서 GREEN이다.
- 전체 pytest suite와 `git diff --check`가 PASS한다.

## 제외 범위

- review 판단·prompt·output contract 변경
- Python 또는 dependency version 변경
- consumer repository ruleset 완화 또는 우회
