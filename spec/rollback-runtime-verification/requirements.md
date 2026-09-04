# 롤백 런타임 검증 요구사항

## 배경

리뷰봇 운영 버전을 롤백한 뒤 실제 GitHub Actions와 OpenAI 연동이 정상인지 확인한다.

## 요구사항

- 검증 Pull Request 발생 시, 시스템은 변경 내용을 분석하고 GitHub 리뷰를 게시해야 한다.
- OpenAI 호출이 실패하면, 시스템은 GitHub Actions check를 실패로 표시해야 한다.
- 비용 상한 내에서 리뷰가 실행되면, 시스템은 고정 요청 횟수 제한 없이 최종 리뷰를 게시해야 한다.

## 성공 기준

- GitHub Actions의 `review` check가 성공한다.
- Pull Request에 `github-actions[bot]` 리뷰가 게시된다.
- 개선된 리뷰 실행이 선택한 route와 계산된 비용을 반환한다.
