할 일을 JSON 파일에 저장하는 Python 패키지 `todo` 를 만든다.

- 패키지는 작업 폴더 최상위의 `todo/` 에 둔다 (src 레이아웃을 쓰지 말 것). 표준 라이브러리만 쓴다.
- 한 사람이 자기 터미널에서 쓰는 작은 도구다. 여러 프로세스가 같은 파일을 동시에 쓰는 경우는 고려하지 않는다.
- 아래 이름과 동작을 정확히 지킨다. 다른 사람이 이 인터페이스로 테스트한다.

## `todo.TodoStore(path)`

- `path`: JSON 파일 경로(`str` 또는 `pathlib.Path`). 파일이 없으면 빈 목록으로 시작하고, 처음 저장할 때 만든다.
- `add(title) -> int`: 앞뒤 공백을 뺀 제목이 비어 있으면 `ValueError`. 새 항목의 id 를 돌려준다. id 는 1 부터 시작하고, 지금까지 쓴 가장 큰 id 보다 1 크다(지운 id 는 다시 쓰지 않는다). 제목은 앞뒤 공백을 뺀 값으로 저장한다.
- `done(id) -> None`: 그 항목을 완료로 표시한다. 없는 id 면 `KeyError`.
- `remove(id) -> None`: 그 항목을 지운다. 없는 id 면 `KeyError`.
- `items(include_done=True) -> list[dict]`: `{"id": int, "title": str, "done": bool}` 목록을 id 순서로. `include_done=False` 면 완료되지 않은 것만.
- `add`·`done`·`remove` 는 부를 때마다 바로 파일에 저장한다.
- 파일 형식: `{"next_id": int, "items": [{"id": int, "title": str, "done": bool}, ...]}`, UTF-8, 한글 등은 이스케이프하지 않는다.
- 파일이 올바른 JSON 이 아니거나 위 형식이 아니면 생성자에서 `todo.StoreError` 를 낸다(`Exception` 의 하위 클래스).

## 명령줄: `python -m todo [--file PATH] <명령> ...`

- `--file` 을 주지 않으면 현재 폴더의 `todo.json` 을 쓴다.
- `add <제목 단어...>`: 단어들을 공백 하나로 이어 제목으로 삼는다. 표준 출력에 `added <id>`.
- `list [--all]`: 완료되지 않은 항목만(`--all` 이면 전부) 한 줄에 하나씩 `<id>. [ ] <제목>`, 완료된 항목은 `<id>. [x] <제목>`.
- `done <id>`, `rm <id>`: 성공하면 아무것도 출력하지 않는다.
- 오류: 없는 id 면 표준 오류에 메시지를 쓰고 종료 코드 1. 빈 제목이면 종료 코드 2. 파일이 깨졌으면(StoreError) 종료 코드 3.
