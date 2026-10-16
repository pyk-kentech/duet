이 작업 폴더의 기존 프로젝트 `textstats`(wc 비슷한 CLI)에 가장 긴 줄의 길이를 세는 기능을 추가한다.
기존 동작은 하나도 바꾸지 않는다. 기존 테스트는 계속 통과해야 한다.

## 추가할 것

- `Counts` 에 정수 속성 `max_line_length` 를 추가한다.
  - `data.decode("utf-8", errors="replace")` 를 `"\n"` 으로 나눈 각 조각의 글자 수 중 최댓값. `"\n"` 자체는 세지 않는다.
  - 탭과 `"\r"` 도 한 글자로 센다. 빈 입력이면 0.
  - 예: `b"ab\nabcd\n"` → 4, `b"abc"` → 3, `"한글\n".encode()` → 2.
- CLI 에 `-L` 과 `--max-line-length` 옵션을 추가한다.
  - 출력 열 순서는 lines, words, chars, bytes, max_line_length 중 고른 것만 (옵션 순서와 상관없이).
  - 옵션이 하나도 없을 때의 기본 출력(`-l -w -c`)은 그대로다.
  - 합계 줄의 max_line_length 는 더하지 않고 입력들 중 **최댓값**이다.
- README 의 옵션 설명을 갱신한다.
