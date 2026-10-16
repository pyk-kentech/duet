# textstats 설계

## 목표
`wc` 와 비슷한 작은 CLI. 표준 라이브러리만, Python 3.10+.

## 구조
- `textstats/__init__.py`: `Counts`(불변 dataclass, `+` 로 합산)와 `count(data: bytes) -> Counts`. 계산만 하고 입출력은 하지 않는다.
- `textstats/cli.py`: argparse 로 옵션을 읽고 입력마다 한 줄 출력, 2개 이상이면 합계.
- `textstats/__main__.py`: `python -m textstats` 진입점.

## 규칙
- 출력은 값 사이 공백 하나, 폭 맞춤 없음. 열 순서는 FIELDS 에 고정.
- 열 수 없는 파일은 `textstats: <이름>: <이유>` 를 표준 오류에 쓰고 계속, 종료 코드 1.
- 글자 수는 `decode("utf-8", errors="replace")` 기준.
