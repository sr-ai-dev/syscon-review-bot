# task 문서 파일명 alias 지원 요구사항

## 배경

리뷰 봇의 spec gate는 task 문서 파일을 `tasks.md`로만 인식한다. 일부 PR은 단수형 `task.md`를 사용하거나 문서 본문에서 `task.md`와 `tasks.md`를 같은 의미로 함께 언급한다.

## 요구사항

- `spec/<기능명>/tasks.md`와 `spec/<기능명>/task.md`를 같은 task 문서로 인정한다.
- 단일 `spec/<기능명>/` 디렉터리에 `task.md` 또는 `tasks.md` 중 1개와 `requirements.md` 또는 `design.md` 중 1개 이상이 있으면 spec gate를 통과해야 한다.
- `task.md`/`tasks.md`가 모두 없으면 spec gate는 계속 실패해야 한다.
- AI 리뷰 프롬프트는 `task.md`와 `tasks.md`를 허용 alias로 설명해 단수/복수 파일명 차이만으로 문서 결함을 만들지 않아야 한다.
- 사용자 안내 문구는 두 파일명 중 하나가 필요하다는 규칙을 표시해야 한다.
