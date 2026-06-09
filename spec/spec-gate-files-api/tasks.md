# Spec Gate Files API 작업 목록

## 완료

- [x] `require_spec_files`가 활성화된 경우 spec gate가 GitHub PR files API의 `filename` 값을 사용하도록 수정했다.
- [x] 406 fallback 경로에서 이미 가져온 PR files API 응답을 재사용하도록 했다.
- [x] 테스트용 GitHub mock이 실제 PR 파일 메타데이터를 제공하도록 보강했다.
- [x] spec 문서 규칙에서 `tasks.md` 필수 조건을 제거하고, `requirements.md` 또는 `design.md` 중 1개 이상 조건만 유지했다.
- [x] raw diff header에 escaped 한글 spec 경로가 포함되는 회귀 테스트를 추가했다.
- [x] PR #265의 실제 파일 목록이 `check_spec_files()`를 통과하는지 확인했다.
- [x] raw diff 파서는 해당 escaped spec 경로를 여전히 놓치며, 회귀 테스트가 원래 실패 지점을 덮는지 확인했다.

## 검증

- [x] `.venv/bin/python -m pytest tests/test_engine.py tests/test_spec_check.py`
- [x] `.venv/bin/python -m pytest`

## 비고

- PR #265에는 `spec/260521-기능통합/requirements.md`가 있으므로 현재 spec gate 규칙을 만족한다.
- PR #265의 `spec/260521-기능통합/disign.md`는 오타가 있지만, `requirements.md`가 보조 문서 요건을 만족하므로 gate는 통과한다.
