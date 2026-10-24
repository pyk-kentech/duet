# booking 설계 메모

2024년에 회의실 예약 스크립트로 시작해 책상·반복 예약·대기열·청구서가 차례로 붙었다. 모듈 경계는
대체로 아래와 같지만, 기능이 붙은 순서대로 쓰여서 같은 검사가 여러 곳에 따로 들어가 있는 부분이 있다
(정리는 아직 못 했다).

## 모듈

| 모듈 | 하는 일 |
|---|---|
| `models.py` | dataclass 들. 검사는 하지 않는다 |
| `errors.py` | 오류 계층 |
| `timeutil.py` | 슬롯 맞추기, 구간 겹침, 시각·월 문자열 |
| `hours.py` | 영업시간 문자열 ↔ 사전, 영업 구간 판정 |
| `resources.py`, `members.py` | 자원·회원 만들기와 검사, 플랜 표 |
| `credits.py` | 예약 비용, 원장(청구·환불), 잔액 계산 |
| `cancellation.py` | 취소 수수료 표 |
| `policy.py` | 사전 예약 한도 |
| `space.py` | `Space`: 모든 상태를 들고 있는 장부. 단건 예약·취소·변경·대기 등록·빈 시각 |
| `recurrence.py` | 반복 예약 펼치기·검사, 여러 발생 취소 |
| `waitlist.py` | 대기열과 승격 |
| `notify.py` | 알림함 |
| `reports.py`, `invoices.py`, `export.py` | 읽기 전용 출력 |
| `importer.py`, `admin.py` | CSV 일괄 예약, 운영 작업 |
| `storage.py` | JSON 읽기·쓰기 (버전 1·2·3) |
| `cli.py` | argparse 하위 명령 |

## 상태

`Space` 가 모든 상태를 사전으로 들고 있다: `_resources`, `_members`, `_bookings`(id → Booking),
`_teams`, `_series`, `_waitlist`, `_ledger`, `_outbox`, 다음 번호(`_next_booking`, `_next_series`).
storage·importer·admin 은 속도와 편의를 위해 이 내부 사전을 직접 읽고 쓴다.

색인(1.5.0): 활성 예약을 `(자원, 날짜) → [Booking]` 으로 들고 있다(`_by_day`). 예약이 생기거나(`_create`),
취소되거나(`_mark_cancelled`), 시각이 바뀌면(`move`) 함께 고친다. `_bookings` 를 직접 바꾸는 곳은
`_reindex()` 를 부른다(storage 의 load, importer 의 되돌리기). 원장은 `(계정, 달)` 별 순사용량을 함께 더해 두고,
`entries` 를 통째로 바꾸거나 `truncate()` 하면 다시 센다. 대기열은 자원별 사전도 둔다.

## 약속

- 시각은 `Space.clock()` 으로만 얻는다.
- 예약을 만드는 곳은 `Space._create` 하나다(청구까지 함께 한다). 반복 예약과 대기자 승격도 이걸 부른다.
- 충돌(버퍼 포함) 판정은 `Space._find_conflict`, 영업시간 판정은 `Space._check_hours`(→ `hours.within`),
  취소 하나(수수료·환불·승격·면제·알림)는 `Space._cancel_one` 한 곳에서 한다. 반복 예약 모듈도 이것들을 부른다.
- 청구 계정은 `Space._account_for(member)` 로 정하고 `Booking.account` 에 남긴다. 정산은 늘 그 계정으로.
- 검사 순서: 자원 → 회원 → 시각 값 → 사전 예약 한도 → 인원 → 영업시간 → 충돌 → 크레딧. 실패하면 상태를 바꾸지 않는다.
- 크레딧 월은 예약 시작 시각의 달. 환불도 그 달.
- 출력 형식(CLI·청구서·iCalendar)은 다른 스크립트가 읽으므로 바꾸지 않는다.
