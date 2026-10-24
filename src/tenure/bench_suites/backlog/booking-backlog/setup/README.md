# booking

작은 코워킹 스페이스의 회의실·책상 예약 라이브러리와 CLI. 파이썬 3.11+, 표준 라이브러리만 쓴다.
데이터는 JSON 파일 하나에 저장한다.

```bash
python -m pytest -q          # 테스트
python -m booking --help     # CLI
```

## 라이브러리

```python
from datetime import datetime
from booking import Space

space = Space(clock=lambda: datetime(2026, 10, 19, 9, 0))   # '지금'은 clock 으로만 얻는다
space.add_resource("room-a", "Room A", capacity=6, credits_per_hour=4, buffer_minutes=15,
                   hours="mon-fri 08:00-20:00")
space.add_member("alice", "Alice", plan="basic")
b = space.book("room-a", "alice", datetime(2026, 10, 20, 10, 0), datetime(2026, 10, 20, 11, 30))
space.cancel(b.id)
```

### 공개 API

| 모듈 | 이름 |
|---|---|
| `booking` | `Space`, 모델(`Resource`, `Member`, `Plan`, `Booking`, `Series`, `WaitlistEntry`, `LedgerEntry`, `Cancellation`, `Notification`), 오류들, `PLANS`, `parse_hours`, `format_hours` |
| `booking.reports` | `utilization`, `credit_usage`, `agenda` |
| `booking.invoices` | `invoice`, `render_invoice` |
| `booking.export` | `export_ics` |
| `booking.storage` | `load(path, clock=None)`, `save(space, path)` |
| `booking.importer` | `import_bookings(space, text)`, `ImportError_` |
| `booking.admin` | `purge_cancelled`, `expire_waitlist`, `check_integrity` |
| `booking.credits` | `cost(resource, start, end)` |

`Space` 메서드: `add_resource`, `resource`, `resources`, `update_resource`, `add_member`, `member`, `members`,
`set_plan`, `plan_of`, `balance(member_id, month)`, `ledger(member_id=None)`, `notifications(member_id=None)`,
`book`, `booking`, `bookings(resource_id=None, member_id=None, start=None, end=None, include_cancelled=False)`,
`cancel`, `move`, `book_series`, `series`, `all_series`, `skip_occurrence`, `cancel_series`,
`join_waitlist`, `leave_waitlist`, `waitlist(resource_id=None)`, `free_slots(resource_id, day, minutes)`.

### 오류

모두 `BookingError` 하위: `NotFound`(`UnknownResource`, `UnknownMember`, `UnknownBooking`, `UnknownSeries`,
`UnknownEntry`), `AlreadyExists`, `Conflict`, `OutsideHours`, `CapacityExceeded`, `InsufficientCredits`,
`PolicyError`, `StorageError`, `ImportError_`. 입력 형식 오류(빈 이름, 잘못된 시각 등)는 `ValueError`.

## 규칙

### 시각
- 시간대 없는 현지 시각(naive datetime). 슬롯은 15분: 예약 시작은 **내림**, 끝은 **올림**한다
  (10:05~10:50 → 10:00~11:00, 초도 따진다).
- 예약은 최대 12시간. 끝이 시작보다 뒤여야 한다(ValueError).
- 지난 시각은 예약할 수 없다: 내림한 시작이 지금보다 앞이면 ValueError.

### 자원과 영업시간
- 자원 id·회원 id: 소문자로 시작, 소문자·숫자·`-`, 24자 이하.
- 종류 `room`/`desk`. 책상은 1인용(정원 1). 회의실 예약의 참석 인원은 정원 이하(`CapacityExceeded`).
- 영업시간 문자열: `"mon-fri 08:00-20:00; sat 10:00-14:00"`. 요일마다 구간 하나, 15분 단위,
  닫는 시각 > 여는 시각. 빈 문자열은 늘 닫힘. 기본값 `mon-fri 08:00-20:00`.
  `format_hours` 는 이어진 요일의 같은 구간을 묶은 표준 문자열을 만든다.
- 예약은 **시작하는 날의 영업 구간 안**에 있어야 한다(`OutsideHours`). 끝이 닫는 시각과 같아도 된다.
- `update_resource` 로 바꾼 값은 이후 요청부터 적용되고, 이미 있는 예약은 다시 검사하지 않는다.

### 충돌과 버퍼
- 같은 자원의 취소되지 않은 예약과 겹치면 `Conflict`. **한 예약이 끝나는 시각에 다른 예약이 시작하는 것은
  충돌이 아니다** — 단, 버퍼가 있는 자원은 예외다.
- 버퍼(`buffer_minutes`, 0~120, 15분 단위)가 있는 자원에서는 **다른 회원의** 예약과 버퍼 시간 이상
  떨어져야 한다(간격이 정확히 버퍼면 된다). **같은 회원**의 예약끼리는 버퍼가 필요 없다(겹치지만 않으면 된다).
- 버퍼는 예약끼리의 간격에만 적용된다. 영업 종료 시각까지 예약하는 것은 버퍼와 상관없이 된다.

### 크레딧
- 플랜: `basic` 월 40(초과 불가), `pro` 월 120(초과 크레딧당 2.00), `payg` 월 0(초과 크레딧당 3.00).
- 예약 비용 = 시간당 크레딧 × 분 / 60, **올림**. 시작 시각이 주말이거나 평일 18:00 이후·07:00 이전이면
  절반(할인한 뒤 올림). 할인 여부는 시작 시각으로만 정한다.
- 크레딧은 **예약 시작 시각이 속한 달**의 잔액에서 쓰고, 환불도 그 달로 돌아간다. 월 크레딧은 이월되지 않는다.
- 잔액 = 월 크레딧 − (그 달 청구 − 그 달 환불). 초과가 안 되는 플랜에서 비용이 잔액보다 크면
  `InsufficientCredits`. 플랜을 바꾸면 모든 달의 월 크레딧을 새 플랜으로 계산한다.
- 원장(`ledger`)은 청구(`charge`)·환불(`refund`) 항목만 기록한다(0 크레딧은 기록하지 않음).

### 사전 예약 한도
- `basic` 30일, `pro` 90일, `payg` 14일: 시작 − 지금이 한도를 넘으면 `PolicyError`.
- 단건 예약·대기 등록·예약 변경에 적용. 반복 예약은 첫 발생만 본다. 대기자 승격은 다시 보지 않는다.

### 취소
- 이미 시작한 예약(시작 ≤ 지금)이나 이미 취소된 예약은 취소할 수 없다(`BookingError`).
- 수수료: 알림 시간(시작 − 지금) 24시간 이상 0%, 2시간 이상 50%, 2시간 미만 100%.
  **수수료는 청구한 크레딧 기준이고 정수 크레딧으로 올림**한다(3 크레딧의 50% → 2). 환불 = 청구 − 수수료.
- 취소하면 회원에게 `cancelled` 알림이 생기고, 그 자원의 대기열을 승격한다.

### 예약 변경 (`move`)
- 취소되지 않았고 아직 시작하지 않은 예약만. 새 시각은 새 예약과 같은 규칙(슬롯, 영업시간, 충돌, 한도)으로 본다.
- **같은 예약 번호, 같은 생성 시각(`created_at`), 같은 반복 예약 소속을 유지한다.**
- 취소가 아니므로 수수료가 없고 `cancelled` 알림도 없다. 비게 된 원래 시간은 대기자에게 넘기지 않는다
  (알려진 제약: 대기열 승격은 취소 때만 일어난다).

### 반복 예약
- `book_series(resource_id, member_id, start, end, freq="weekly"|"biweekly", count=None, until=None,
  attendees=1, note="", skip_conflicts=False)`. `count`(1~104)와 `until`(날짜, 그날 시작하는 발생 포함) 중 정확히 하나.
- 모든 발생을 먼저 검사하고 하나라도 안 되면 아무것도 만들지 않는다(`OutsideHours`/`Conflict`).
  `skip_conflicts=True` 면 그런 발생만 건너뛰고 그 날짜를 `series.exceptions` 에 남긴다. 만들 발생이
  하나도 없으면 `BookingError`.
- 크레딧은 발생마다 그 달에서 청구한다. 모자라면 `skip_conflicts` 와 상관없이 `InsufficientCredits`(아무것도 안 만듦).
- 발생의 `created_at` 은 반복 예약을 만든 시각.
- `skip_occurrence(series_id, day)`: 그 날의 발생 하나를 취소(수수료 규칙은 일반 취소와 같음)하고 날짜를
  `exceptions` 에 더한다. `cancel_series(series_id, from_date=None)`: 시작이 지금보다 뒤인 발생을 모두
  (from_date 를 주면 그 날짜부터) 시작 순으로 취소한다. 둘 다 `Cancellation` 을 돌려준다(목록 / 하나).

### 대기열
- `join_waitlist(...)`: 지금 그 시간을 예약할 수 있으면 `BookingError`(대기 대신 예약하라). 같은 회원이
  같은 자원·시간에 두 번 등록하면 `AlreadyExists`. 슬롯·영업시간·인원·사전 예약 한도 검사는 예약과 같다.
- 승격: 그 자원의 예약이 취소될 때(단건 취소, 반복 예약 취소, 한 날짜 취소) 등록 순서대로 훑어서
  예약할 수 있는 항목을 예약으로 바꾼다. 시작이 지난 항목은 지우고, 아직 겹치면 남기고, 크레딧이 모자라면
  건너뛰고 남긴다. 승격된 예약은 `created_at` = 승격 시각, 메모 `"waitlist"`, 회원에게 `promoted` 알림.

### 빈 시각 (`free_slots`)
- 그 날의 영업 구간 안에서 `minutes` 분(15분 단위로 올림) 예약을 시작할 수 있는 시각들, 15분 간격,
  지난 시각은 뺀다.

## 보고서·청구서·내보내기

- `reports.utilization(space, start, end, resource_id=None)` → `UtilizationRow(resource_id, open_minutes,
  booked_minutes, percent)` 자원 id 순. 영업 시간·예약 시간은 기간 [start, end) 안에 들어가는 부분만 센다.
  percent 는 소수 첫째 자리 반올림(파이썬 `round`), 영업 시간 0 이면 0.0.
- `reports.credit_usage(space, month)` → `UsageRow(member_id, plan, allowance, used, balance)` 회원 id 순.
- `reports.agenda(space, day, resource_id=None)` → 그 날과 겹치는 예약.
- `invoices.invoice(space, member_id, month)` / `render_invoice(inv)`: 형식은 `invoices.py` 모듈 설명.
  줄 = 취소되지 않은 예약(청구 크레딧) + 수수료가 있는 취소 예약(`취소 수수료 ...`, 수수료).
- `export.export_ics(...)`: 형식은 `export.py` 모듈 설명.

## 저장

- `storage.save` 는 형식 버전 2 로 쓴다(임시 파일 후 바꿔치기). `storage.load` 는 버전 1·2 를 읽는다.
  그 밖의 버전이나 깨진 파일은 `StorageError`. 형식은 `storage.py` 모듈 설명.
- 대기열은 아직 파일에 저장하지 않는다.

## CLI

`python -m booking [--db booking.json] [--now YYYY-MM-DDTHH:MM] <명령>`. 시각 `YYYY-MM-DDTHH:MM`,
날짜 `YYYY-MM-DD`, 월 `YYYY-MM`. 바꾸는 명령만 저장한다. 오류는 표준 오류에 `오류: ...`, 종료 코드 1,
파일은 바뀌지 않는다.

| 명령 | 출력 (탭 구분) |
|---|---|
| `resource-add ID NAME [--kind] [--capacity] [--cph] [--buffer] [--hours]` | 없음 |
| `resource-set ID [--name] [--capacity] [--cph] [--buffer] [--hours]` | 없음 |
| `resources` | `ID KIND CAPACITY CPH BUFFER HOURS` |
| `member-add ID NAME [--plan]`, `plan MEMBER PLAN` | 없음 |
| `members` | `ID NAME PLAN` |
| `book RESOURCE MEMBER START END [--attendees N] [--note T]` | `ID START END CHARGED` |
| `series RESOURCE MEMBER START END (--count N \| --until DATE) [--freq] [--attendees] [--note] [--skip-conflicts]` | `series SID`, 발생마다 `ID START END CHARGED`, 건너뛴 날마다 `skipped DATE` |
| `cancel ID` / `skip SID DATE` | `ID FEE REFUND` |
| `cancel-series SID [--from DATE]` | 발생마다 `ID FEE REFUND` |
| `move ID START END` | `ID START END CHARGED` |
| `wait RESOURCE MEMBER START END [--attendees N]` | `ENTRY_ID` |
| `unwait ENTRY_ID` | 없음 |
| `waitlist [--resource R]` | `ENTRY_ID RESOURCE MEMBER START END` |
| `list [--resource] [--member] [--from] [--to] [--all]` | `ID RESOURCE MEMBER START END STATUS CHARGED` |
| `free RESOURCE DATE MINUTES` | 시작 시각 한 줄에 하나 (`YYYY-MM-DDTHH:MM`) |
| `balance MEMBER [--month M]` | `MEMBER MONTH ALLOWANCE USED BALANCE` |
| `usage MONTH` | `MEMBER PLAN ALLOWANCE USED BALANCE` |
| `invoice MEMBER MONTH` | `render_invoice` 형식 |
| `report FROM TO [--resource R]` | `RESOURCE OPEN BOOKED PERCENT` (FROM/TO 는 날짜 또는 시각, 날짜는 00:00) |
| `agenda DATE [--resource R]` | `RESOURCE START END MEMBER NOTE` |
| `notifications [--member M]` | `TS MEMBER KIND TEXT` |
| `import FILE` | 만든 예약마다 `ID START END CHARGED` |
| `purge --before DATE` | 지운 개수 |
| `check` | 문제 한 줄에 하나, 없으면 `ok` |
| `export [--resource] [--member]` | iCalendar 글 |
