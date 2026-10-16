정수 구간을 다루는 Python 패키지 `intervals` 를 만든다.

- 패키지는 작업 폴더 최상위의 `intervals/` 에 둔다 (src 레이아웃을 쓰지 말 것). 표준 라이브러리만 쓴다.
- 아래 이름과 동작을 정확히 지킨다. 다른 사람이 이 인터페이스로 테스트한다.

## 규칙

- 구간은 정수 쌍 `(start, end)` 이고 **반열린 구간** `[start, end)` 이다. 입력은 튜플 또는 길이 2 리스트를 받는다.
- 출력은 항상 `start` 오름차순으로 정렬되고, 겹치거나 맞닿은 구간이 없는 **튜플의 리스트**다.
- 맞닿은 구간은 합친다: `(1, 3)` 과 `(3, 5)` → `(1, 5)`.
- 길이 0 인 구간(`start == end`)은 결과에 넣지 않는다.
- `start > end` 인 구간이 있으면 `ValueError`.
- 입력 리스트를 바꾸지 않는다.

## 인터페이스

- `intervals.merge(items) -> list[tuple[int, int]]`: 순서 상관없는 구간 목록을 병합한다. 빈 목록이면 빈 목록.
- `intervals.insert(items, new) -> list[tuple[int, int]]`: 구간 목록에 `new` 를 넣고 병합한 결과.
- `intervals.subtract(items, cut) -> list[tuple[int, int]]`: 구간 목록(병합 전이어도 됨)에서 `cut` 과 겹치는 부분을 뺀 결과. 예: `[(0, 10)]` 에서 `(3, 5)` 를 빼면 `[(0, 3), (5, 10)]`.
- `intervals.total_length(items) -> int`: 병합한 뒤 `end - start` 의 합.
