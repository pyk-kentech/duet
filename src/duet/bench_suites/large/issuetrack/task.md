작업 폴더 최상위에 파이썬 패키지 `issuetrack`(표준 라이브러리만, Python 3.11 이상)을 만든다. 작은 이슈 트래커 라이브러리와 CLI 다. 패키지는 작업 폴더 바로 아래 `issuetrack/` 에 둔다(src 레이아웃 아님). 아래의 이름·시그니처·출력 형식은 그대로 지킨다. 테스트도 함께 작성한다.

## 공개 API (`issuetrack` 에서 import)

`Tracker`, `Issue`, `Event`, `STATUSES`, 오류 `IssueError`(공통 부모, `Exception` 하위)와 그 하위 `NotFound`, `InvalidTransition`, `QueryError`, `StorageError`, `CsvFormatError`. 값 검사 실패는 `ValueError`(IssueError 아님).

## 이슈 (`Tracker`)

- `STATUSES = ("open", "doing", "review", "done", "closed")`.
- `Issue` 속성: `id`(int), `title`(str), `status`(str), `priority`(int), `labels`(정렬된 `tuple[str, ...]`), `assignee`(str 또는 None), `due`(`date` 또는 None), `created`, `updated`(datetime).
- `Event` 속성: `at`(datetime), `issue_id`(int), `field`(str), `old`, `new`.
- `Tracker(clock=None)`: `clock` 은 datetime 을 돌려주는 함수(없으면 `datetime.now`). 시각은 `clock` 으로만 얻는다. "오늘"은 `clock().date()`.
- `create(title, *, priority=3, labels=(), assignee=None, due=None) -> Issue`
  - id 는 1부터 차례로 준다. **지운 이슈의 id 는 다시 쓰지 않는다**(저장했다 읽은 뒤에도).
  - `title`: 앞뒤 공백을 뗀 뒤 1~120자. 아니면 ValueError.
  - `priority`: 1~4 정수(1이 가장 높음). bool 은 안 된다. 아니면 ValueError.
  - `labels`: 각 라벨을 소문자로 바꾼 뒤 `[a-z0-9-]{1,20}` 이어야 한다(아니면 ValueError). 중복은 하나로, 정렬해서 저장.
  - `assignee`: None 또는 앞뒤 공백을 뗀 비어 있지 않은 문자열(저장도 뗀 값). 빈 문자열·공백만이면 ValueError.
  - `due`: None 또는 `date`. **`datetime` 은 ValueError**(datetime 은 date 의 하위 클래스다).
  - 상태 `"open"`, `created = updated = 지금`. 이벤트 `field="created", old=None, new="open"` 하나를 남긴다.
- `get(id) -> Issue`(없으면 NotFound), `issues() -> list[Issue]`(id 순).
- `update(id, **fields)`: `title`, `priority`, `assignee`, `due` 만(그 밖의 키는 ValueError). 검사는 create 와 같고 `assignee=None`·`due=None` 은 비우기다. **값이 실제로 바뀐 필드마다** 이벤트(필드 이름, 이전 값, 새 값)를 남기고 updated 를 지금으로 바꾼다. 아무것도 안 바뀌면 이벤트도 updated 변화도 없다.
- `label(id, add=(), remove=())`: add 를 먼저, remove 를 나중에 적용(라벨 검사는 create 와 같음). 없는 라벨의 remove 는 무시. 라벨이 실제로 바뀌었을 때만 이벤트 `field="labels"`(이전 tuple, 새 tuple)와 updated 갱신.
- `move(id, status)`: 아래 전이만 허용. 없는 상태 이름은 ValueError, 같은 상태이거나 허용되지 않은 전이는 InvalidTransition. **`doing` 으로 가려면 담당자가 있어야 한다**(없으면 InvalidTransition). 이벤트 `field="status"`, updated 갱신.

  | 지금 | 갈 수 있는 곳 |
  |---|---|
  | open | doing, closed |
  | doing | open, review |
  | review | doing, done |
  | done | doing, closed |
  | closed | open |

- `delete(id)`: 지운다(없으면 NotFound). 그 이슈의 이벤트도 함께 사라진다.
- `history(id) -> list[Event]`: 그 이슈의 이벤트, 일어난 순(없는 이슈는 NotFound).
- `search(query: str) -> list[Issue]`: 아래 질의 언어.

## 질의 언어 (`issuetrack.query`, `Tracker.search`)

- 잘못된 질의는 `QueryError`.
- 공백으로 나뉜 항. 한 그룹의 항은 모두 만족해야 한다(AND). 따옴표 밖의 대문자 단어 `OR` 가 그룹을 나눈다(그룹 중 하나라도 만족). `OR` 가 맨 앞·맨 뒤에 있거나 연달아 있으면 QueryError. 괄호는 없다. 조건이 없는 그룹(예: 정렬 항만 있는 그룹)은 모든 이슈를 만족한다.
- 항 앞의 `-` 는 부정이다(`-label:bug`). `-` 만 있으면 QueryError.
- 큰따옴표로 감싼 구절(`"two words"`, `-"two words"`)은 한 항이며 제목 부분 문자열이다. 닫히지 않은 따옴표는 QueryError.
- `이름` 바로 뒤에 `:`, `=`, `<`, `<=`, `>`, `>=` 중 하나가 오면 필드 항이다(이름은 영문자). 필드 이름은 소문자만 쓴다: 아래에 없는 이름(대문자가 섞인 것 포함)이나 빈 값은 QueryError.
  - `status:V[,V...]`: 그중 하나. 값은 STATUSES 중 하나(아니면 QueryError). `status` 는 `:` 만 쓴다.
  - `label:L`: 그 라벨이 있음(소문자로 비교).
  - `assignee:NAME`: 담당자가 같음(대소문자 무시). `assignee:none` 은 담당자 없음.
  - `priority`: `priority:2`(같음), `priority=2`, `priority<2`, `priority<=2`, `priority>2`, `priority>=2`. 값은 1~4 정수.
  - `due`: `priority` 와 같은 연산자, 값은 `YYYY-MM-DD`. `due:none` 은 기한 없음. **기한 없는 이슈는 비교·같음 항에서 늘 거짓**(부정하면 참).
  - `is:open`(done·closed 가 아님), `is:overdue`(기한이 오늘보다 앞이고 done·closed 가 아님).
  - `sort:KEY`, `sort:-KEY`(KEY 는 priority, id, due, updated, `-` 는 내림차순). 조건이 아니며 질의 어디에 있어도 된다. 둘 이상이거나 부정(`-sort:...`)이면 QueryError.
- 필드 항이 아닌 단어는 제목 부분 문자열(대소문자 무시).
- 결과 순서: 기본은 priority 오름차순, 같으면 id 오름차순. `sort` 가 있으면 그 키, 같으면 id 오름차순. `sort:due`·`sort:-due` 는 **기한 없는 이슈를 방향과 상관없이 맨 뒤에** 둔다. 빈 질의(공백만)는 모든 이슈.

## 저장 (`issuetrack.storage`)

- `save(tracker, path)`: JSON, 최상위 `"version": 2`. 임시 파일에 쓰고 `os.replace` 로 바꾼다. 세부 키는 자유지만 `load(save(x))` 가 같아야 한다(이슈, 이벤트, 다음 id). 이벤트의 old·new 도 원래 형식으로 복원한다(날짜는 date, 라벨은 tuple).
- `load(path, clock=None) -> Tracker`: 파일이 없으면 빈 Tracker.
- **버전 1 파일도 읽는다**: `{"version": 1, "issues": [{"id", "title", "status", "labels", "assignee", "due", "created"}]}`. `labels` 는 쉼표로 이은 문자열(공백 무시, 빈 문자열이면 없음, 소문자로), `priority` 키가 없으면 3, `due` 는 `YYYY-MM-DD` 또는 null, `created` 는 isoformat, `updated` 는 created 와 같게, 이벤트 없음, 다음 id 는 가장 큰 id + 1.
- 그 밖의 버전, JSON 이 아님, 필드 형식 오류는 `StorageError`.

## CSV (`issuetrack.csvio`)

- `export_csv(tracker, file)`: `file` 은 쓰기용 텍스트 파일 객체. 헤더 `id,title,status,priority,labels,assignee,due` 와 이슈마다 한 줄(id 순). labels 는 `;` 로 잇고, 값이 없으면 빈 칸, due 는 `YYYY-MM-DD`. `csv` 모듈 기본 방언(줄 끝 `\r\n`).
- `import_csv(tracker, file) -> list[int]`: 헤더가 있어야 한다. 열 순서는 자유, `title` 열은 필수, 나머지 열은 선택, 모르는 열은 CsvFormatError. `id` 열은 무시하고 새 id 를 받는다. `status` 는 STATUSES 중 하나(빈 칸이면 open)이며 전이 규칙 없이 그 상태로 만든다. `priority` 빈 칸은 3, `labels` 는 `;` 로 나눔. 이벤트는 `created`(old None, new 그 상태) 하나.
  - **전부 아니면 전무**: 한 줄이라도 잘못되면 아무 이슈도 만들지 않고 CsvFormatError. 메시지에 `줄 N` 을 넣는다(N 은 헤더를 1로 센 파일 줄 번호).
  - 만든 id 목록을 돌려준다.

## 보고서 (`issuetrack.reports`)

- `summary(tracker) -> dict[str, int]`: STATUSES 순서로 모든 상태와 개수(0 포함).
- `workload(tracker) -> list[tuple[str, int]]`: 담당자별 열린 이슈 수(열림 = done·closed 아님). 개수 내림차순, 같으면 이름 오름차순. 담당자 없는 열린 이슈는 `"(none)"` 으로 묶어 **개수와 상관없이 맨 끝**. 열린 이슈가 없는 담당자는 뺀다.
- `cycle_time(tracker, id) -> timedelta | None`: 처음 doing 에 들어간 시각부터 처음 done 에 들어간 시각까지. 둘 중 하나라도 없으면 None.
- `throughput(tracker, start, end) -> dict[date, int]`: start~end(포함)의 모든 날짜를 키로, 그날 done 으로 간 이벤트 수(같은 이슈가 두 번 가면 2).

## CLI (`python -m issuetrack`)

- 전역 옵션 `--file PATH`(기본 `issues.json`). 데이터를 바꾸는 명령만 저장한다.
- `new TITLE [--priority N] [--label L]... [--assignee A] [--due YYYY-MM-DD]` → 새 id 한 줄.
- `show ID` → 7줄 `key: value`: id, title, status, priority, labels(쉼표로, 없으면 `-`), assignee(없으면 `-`), due(없으면 `-`).
- `move ID STATUS`, `assign ID NAME`(`assign ID -` 는 비우기), `label ID [+L | -L]...`, `delete ID`.
- `list [QUERY...]` → 인자를 공백으로 이은 질의의 결과, 한 줄에 `ID<TAB>STATUS<TAB>P<priority><TAB>TITLE`.
- `export [FILE]`(없으면 표준 출력), `import FILE` → `imported N`.
- `summary` → STATUSES 순으로 `STATUS<TAB>COUNT`.
- 오류(IssueError, ValueError, 잘못된 날짜)는 표준 오류에 `오류: ...` 한 줄, 종료 코드 1, 파일은 바꾸지 않는다. argparse 사용법 오류는 argparse 기본(종료 코드 2).
