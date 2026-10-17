# issuetrack 설계

과제(task)의 명세가 기준이다. 이 문서는 모듈 나누기와 모듈 사이 약속을 정한다.

## 모듈과 책임

| 파일 | 책임 | 다른 모듈에 주는 것 |
|---|---|---|
| `issuetrack/errors.py` | 오류 계층 | `IssueError`, `NotFound`, `InvalidTransition`, `QueryError`, `StorageError`, `CsvFormatError` |
| `issuetrack/models.py` | 자료형과 값 검사 | `STATUSES`, `TRANSITIONS`(dict[str, frozenset]), `Issue`·`Event` dataclass, 검사 함수 `check_title`, `check_priority`, `check_labels`, `check_assignee`, `check_due` (모두 정규화한 값을 돌려주고 잘못되면 ValueError) |
| `issuetrack/tracker.py` | `Tracker`: 이슈 생성·수정·전이·삭제, 이벤트 기록, `search` | `Tracker(clock)`, 저장·가져오기용 내부 진입점 `_restore(issues, events, next_id)`, `_add_imported(rows)` |
| `issuetrack/query.py` | 질의 문자열 → 질의 객체 | `parse(text) -> Query`; `Query.matches(issue, today) -> bool`, `Query.sort_key` |
| `issuetrack/storage.py` | JSON 저장·읽기, 버전 1 이전 | `save(tracker, path)`, `load(path, clock=None)` |
| `issuetrack/csvio.py` | CSV 내보내기·가져오기 | `export_csv(tracker, file)`, `import_csv(tracker, file)` |
| `issuetrack/reports.py` | 집계 | `summary`, `workload`, `cycle_time`, `throughput` |
| `issuetrack/cli.py`, `issuetrack/__main__.py` | argparse CLI | `main(argv=None) -> int` |
| `issuetrack/__init__.py` | 공개 API 다시 내보내기 | |

의존 방향: `errors` ← `models` ← `query` ← `tracker` ← (`storage`, `csvio`, `reports`) ← `cli`. 아래 모듈이 위 모듈을 import 하지 않는다.

## 자료 구조

- `Tracker` 는 `_issues: dict[int, Issue]`, `_events: list[Event]`(전체, 일어난 순), `_next_id: int` 를 가진다. 이슈는 가변 dataclass, 바깥에 돌려주는 것은 같은 객체여도 된다.
- 이벤트는 바뀐 필드마다 하나. 생성은 `field="created"`. 삭제하면 그 이슈의 이벤트를 `_events` 에서 뺀다.
- 시각은 `self.clock()` 한 곳에서만 얻는다(한 동작의 이벤트와 updated 는 같은 시각).

## 모듈 사이 약속

- **검사**: `tracker`·`csvio`·`storage` 는 값 검사를 직접 하지 않고 `models` 의 검사 함수를 쓴다. 가져오기의 줄 번호는 `csvio` 가 붙인다(검사 함수의 ValueError 를 잡아 `CsvFormatError(f"줄 {n}: {e}")`).
- **질의**: `query.parse` 는 문자열만 본다(Tracker 를 모른다). `Tracker.search` 가 `parse` → 필터 → 정렬을 한다. 오늘 날짜는 `search` 가 `clock().date()` 로 넘긴다.
- **저장**: `storage` 는 `Tracker._restore` 로 상태를 통째로 넣는다(이벤트를 다시 만들지 않는다). 버전 1 변환은 `storage` 안에서만 한다.
- **가져오기**: `csvio` 는 모든 줄을 먼저 검사해 값 목록을 만들고, 하나도 실패하지 않았을 때만 `Tracker._add_imported` 로 한꺼번에 넣는다.
- **CLI**: 출력 형식은 과제 명세 그대로. 바꾸는 명령만 `storage.save`.

## 테스트

- `tests/` 아래 pytest. 모듈마다 테스트 파일 하나 이상. 시각은 고정 clock 으로.
