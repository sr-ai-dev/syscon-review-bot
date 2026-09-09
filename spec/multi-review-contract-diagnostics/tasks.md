# 작업

- [x] 실패 실행 및 당시 코드 분석, 수정 범위 확정.
- [x] 요구사항·설계 작성.
- [x] 출력 계약 충돌을 드러내는 회귀 테스트 작성 및 실패 확인.
- [x] 단일/분할/병합 출력 계약 정렬 및 담당/참고 파일 지시 정리.
- [x] 오류 사유 누락을 드러내는 CLI 테스트 작성 및 실패 확인.
- [x] 안전한 사유·stage·unit 진단과 파이프라인 전파 구현.
- [x] 관련 테스트 및 전체 테스트 실행.
- [x] 변경 검토 및 결과 기록.

## 검증 기록

- 실행 당시 `638ea62`와 실제 PR diff를 조합한 오프라인 검사: analysis-1/2/3 모두 ReviewPartial 요청에 ReviewResult 시스템 출력 지시가 포함되어 계약 assertion 실패 확인. 과거 AI 응답 원문을 재생한 검사는 아니다.
- CLI 수정 전: `tests/test_cli.py` 6 failed, 10 passed. 기존 사유 누락 1건, 새 문맥 인자 미지원 4건, 요약 진단 미출력 1건 확인.
- CLI 수정 후: 같은 테스트 16 passed. 사유 및 문맥 출력, 예외 원문·테스트 credential 미출력, 요약 마크업 이스케이프 검증.
- 오류 객체 변경 후 기존 API 클라이언트 테스트: `tests/test_gpt_client.py tests/test_github_client.py` 42 passed.
- 1차 구현: 프롬프트/파이프라인 59 passed, 전체 409 passed. 통합 검토에서 공통 검토 지시의 결과 배열명과 담당/참고 문서 중복 지시를 추가 발견하여 보완했다.
- 실제 14-file diff 오프라인 통합 검사: 정상 경로(shard-1/shard-2/global 도구 호출과 최종 병합, 모의 API 7회), coverage 누락, 잘못된 JSON, 병합 상태 변경 네 시나리오 통과. 실제 GPTClient 파서와 비용 계산을 사용하며 네트워크 응답만 모의 처리한다.
- 최종 프롬프트/파이프라인: 60 passed. 전체: 410 passed. 최종 코드로 실제 diff 오프라인 통합 네 시나리오도 다시 통과했다.
- CLI/errors 집중 검토와 통합 변경 검토 완료. `git diff --check` 통과.

## 실행 명령

```sh
TIKTOKEN_CACHE_DIR=/private/tmp/review-tiktoken-cache .venv/bin/python -m pytest -q
```

## 검증 한계

로컬 변경과 모의 응답 검증 완료. 원격 봇 배포 및 GitHub Actions 재실행은 수행하지 않았다.
과거 실행의 실제 응답은 없으므로 그 실행의 정확한 실패 분기는 확정하지 않는다.
