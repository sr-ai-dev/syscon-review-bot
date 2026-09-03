# 대형 PR 분할 리뷰 및 비용 제어 작업 계획

## 1. 크기 측정과 분할 요청

- [ ] `ReviewSizeMetrics`, route, reason code 모델 테스트를 작성한다.
- [ ] 가중 line/file/raw token 계산기를 구현한다.
- [ ] inventory와 patch coverage 검사를 구현한다.
- [ ] 결정론적 shard packing 테스트를 작성한다.
- [ ] component grouping과 stable packing을 구현한다.
- [ ] split-request formatter와 단일 POST 테스트를 작성한다.
- [ ] size/cost 초과 시 LLM 호출 없이 분할 요청을 게시한다.

## 2. 비용 원장

- [ ] 가격 계산과 `CostPolicy` validation 테스트를 작성한다.
- [ ] versioned Terra nano-USD 가격표를 구현한다.
- [ ] conservative preflight estimator 테스트를 작성한다.
- [ ] output/tool/history 상한을 포함한 실행 plan estimator를 구현한다.
- [ ] 병렬 reservation 경쟁 테스트를 작성한다.
- [ ] 공유 `CostLedger`의 reserve/reconcile을 구현한다.
- [ ] usage 누락, retry, 실제 비용 초과 처리를 구현한다.
- [ ] PR 설정이 trusted 비용 정책을 완화하지 못하는 테스트를 작성한다.

## 3. 병렬 리뷰와 통합

- [ ] `ReviewPlan`, `ReviewUnit`, `ReviewPartial` schema 테스트를 작성한다.
- [ ] shard/global reviewer prompt를 구현한다.
- [ ] required unit 병렬 실행과 실패 전파를 구현한다.
- [ ] 결정론적 dedup, conflict, sort reducer 테스트를 작성한다.
- [ ] partial 결과를 최종 `ReviewResult` 하나로 통합한다.
- [ ] judge 이후 postprocess 순서를 보장한다.

## 4. 외부 계약과 운영

- [ ] `engine.py`의 GitHub publish 지점을 하나로 통합한다.
- [ ] SINGLE/MULTI가 같은 formatter와 판정을 사용하는 계약 테스트를 작성한다.
- [ ] Action input 기반 trusted policy를 추가한다.
- [ ] 비용·routing Step Summary와 구조화 로그를 추가한다.
- [ ] 민감한 prompt/diff/tool/model 원문이 로그에 없는지 검증한다.
- [ ] 전체 테스트를 실행한다.
- [ ] shadow mode로 2주간 metrics를 수집한 뒤 threshold를 보정한다.
