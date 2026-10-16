`wc` 비슷하게 줄·단어·글자·바이트 수를 세는 Python 패키지 `textstats` 를 만든다.

- 패키지는 작업 폴더 최상위의 `textstats/` 에 둔다 (src 레이아웃을 쓰지 말 것). 표준 라이브러리만 쓴다.
- 아래 이름과 동작을 정확히 지킨다. 다른 사람이 이 인터페이스로 테스트한다.

## `textstats.count(data: bytes) -> textstats.Counts`

`Counts` 는 `lines`, `words`, `chars`, `bytes` 정수 속성을 가진 객체다(dataclass, NamedTuple 등).
- `lines`: `b"\n"` 의 개수 (마지막 줄에 개행이 없으면 그 줄은 세지 않는다. `wc -l` 과 같음)
- `words`: 공백 문자(스페이스, `\t`, `\n`, `\r`, `\v`, `\f`)로 구분된, 비어 있지 않은 토막의 수
- `chars`: `data.decode("utf-8", errors="replace")` 의 길이
- `bytes`: `len(data)`

## CLI: `python -m textstats [-l] [-w] [-m] [-c] [FILE ...]`

- `-l` 줄, `-w` 단어, `-m` 글자, `-c` 바이트. 옵션을 여러 개 줄 수 있고(`-lw` 처럼 묶어도 된다), 하나도 없으면 `-l -w -c` 와 같다.
- 출력 열의 순서는 옵션 순서와 상관없이 항상 lines, words, chars, bytes 중 고른 것만.
- 입력마다 한 줄씩: 값들을 **공백 하나**로 구분한다(폭 맞춤 없음). 파일이면 끝에 공백 하나와 파일 이름(인자로 받은 그대로).
- FILE 이 없거나 `-` 면 표준 입력을 읽고, 이름 없이 값만 쓴다.
- FILE 인자가 2개 이상이면 마지막에 합계 줄을 쓴다: 값들 + ` total`. 합계는 읽은 입력만 더한다.
- 열 수 없는 파일은 표준 오류에 `textstats: <이름>: <이유>` 를 쓰고 나머지는 계속 처리한다. 하나라도 실패하면 종료 코드 1, 아니면 0.
- 잘못된 옵션이면 종료 코드 2.
