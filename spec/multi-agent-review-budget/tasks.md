# 대형 PR 분할 리뷰 및 비용 제어 작업 계획

## 1. 크기 측정과 분할 요청

- [x] `ReviewSizeMetrics`, route, reason code 모델 테스트를 작성한다.
- [x] 가중 line/file/raw token 계산기를 구현한다.
- [x] inventory와 patch coverage 검사를 구현한다.
- [x] 결정론적 shard packing 테스트를 작성한다.
- [x] component grouping과 stable packing을 구현한다.
- [x] split-request formatter와 단일 POST 테스트를 작성한다.
- [x] size/cost 초과 시 LLM 호출 없이 분할 요청을 게시한다.

## 2. 비용 원장

- [x] 가격 계산과 `CostPolicy` validation 테스트를 작성한다.
- [x] versioned Terra nano-USD 가격표를 구현한다.
- [x] conservative preflight estimator 테스트를 작성한다.
- [x] output/tool/history 상한을 포함한 실행 plan estimator를 구현한다.
- [x] 병렬 reservation 경쟁 테스트를 작성한다.
- [x] 공유 `CostLedger`의 reserve/reconcile을 구현한다.
- [x] usage 누락, retry, 실제 비용 초과 처리를 구현한다.
- [x] PR 설정이 trusted 비용 정책을 완화하지 못하는 테스트를 작성한다.

## 3. 병렬 리뷰와 통합

- [x] `ReviewPlan`, `ReviewUnit`, `ReviewPartial` schema 테스트를 작성한다.
- [x] shard/global reviewer prompt를 구현한다.
- [x] required unit 병렬 실행과 실패 전파를 구현한다.
- [x] 결정론적 dedup, conflict, sort reducer 테스트를 작성한다.
- [x] partial 결과를 최종 `ReviewResult` 하나로 통합한다.
- [x] judge 이후 postprocess 순서를 보장한다.

## 4. 외부 계약과 운영

- [x] `engine.py`의 GitHub publish 지점을 하나로 통합한다.
- [x] SINGLE/MULTI가 같은 formatter와 판정을 사용하는 계약 테스트를 작성한다.
- [x] Action input 기반 trusted policy를 추가한다.
- [x] 비용·routing Step Summary와 구조화 로그를 추가한다.
- [x] 민감한 prompt/diff/tool/model 원문이 로그에 없는지 검증한다.
- [x] 전체 테스트를 실행한다.
- [ ] shadow mode로 2주간 metrics를 수집한 뒤 threshold를 보정한다.

## 5. 심층 리뷰 보완

- [x] base SHA 설정 고정과 GitHub 설정 조회 fail-closed를 구현한다.
- [x] inventory 대비 patch 줄 수를 검증하고 binary 제외와 rename coverage를 구현한다.
- [x] reviewer별 전체 manifest와 비용에 반영된 shared context를 제공한다.
- [x] tool 비활성 전역 검토에도 bounded patch 근거를 제공한다.
- [x] finding severity와 합성 결과의 모든 의미 필드를 검증한다.
- [x] review `commit_id`, bot 작성자 검증, 동일 SHA 중복 방지를 구현한다.
- [x] 심층 리뷰 회귀 테스트와 전체 테스트를 실행한다.
