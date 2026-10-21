이 작업 폴더의 기존 프로젝트 `stock`(재고 관리 라이브러리 + CLI)에 **주문 예약** 기능을 추가한다.
기존 동작은 아래에 적힌 것 말고는 바꾸지 않는다. 기존 모듈 구조와 관례(DESIGN.md)를 따른다.

## 라이브러리 (`stock.Inventory`)

- 예약: 주문 하나가 품목 하나의 수량을 일정 시각까지 잡아 두는 것. 주문 번호(`order_id`, 비어 있지 않은 문자열), 품목(`sku`), 수량(`qty`, 양의 정수), 만료 시각(`expires_at`, datetime).
- 예약은 **만료 시각이 지금(`clock()`)보다 뒤일 때만 유효**하다. 지금이 만료 시각과 같거나 지났으면 그 예약은 없는 것으로 본다.
- `available(sku) -> int`: `on_hand` 에서 그 품목의 유효한 예약 수량 합을 뺀 값. 없는 품목이면 `UnknownItem`.
- `reserve(sku, qty, order_id, expires_at)`:
  - 없는 품목이면 `UnknownItem`, 수량이 양의 정수가 아니거나 `order_id` 가 비었거나 `expires_at` 이 지금보다 뒤가 아니면 `ValueError`.
  - 같은 `order_id` 의 유효한 예약이 이미 있으면 `DuplicateReservation`. (만료된 예약과 번호가 같은 것은 괜찮다.)
  - `qty` 가 `available(sku)` 보다 크면 `InsufficientStock`.
  - 예약은 이동 기록(`Movement`)을 남기지 않는다.
- `release(order_id)`: 유효한 예약을 지운다. 없으면 `ReservationNotFound`.
- `fulfill(order_id)`: 유효한 예약의 수량만큼 출고하고(재고 감소, 종류 `"ship"`, 메모 `"order <order_id>"` 인 이동 기록) 예약을 지운다. 없으면 `ReservationNotFound`.
- `reservations(sku=None) -> list`: 유효한 예약들(`order_id`, `sku`, `qty`, `expires_at` 속성이 있는 객체), 만료 시각 순, 같으면 `order_id` 순. `sku` 를 주면 그 품목만.
- **바뀌는 기존 동작**: `ship()` 은 이제 `on_hand` 가 아니라 `available` 을 넘을 수 없다(넘으면 `InsufficientStock`).
- **바뀌지 않는 기존 동작**: `adjust()` 는 물리적 보정이므로 예약 때문에 막지 않는다(재고가 음수만 아니면 된다. 그 결과 `available` 이 음수가 될 수 있다). `value()` 는 그대로 `on_hand` 기준.
- `DuplicateReservation`, `ReservationNotFound` 는 `StockError` 의 하위 클래스로, `stock` 패키지에서 import 할 수 있어야 한다.

## 저장 (`stock.storage`)

- 형식 버전 2: 기존 필드에 `"reservations": [{"order_id", "sku", "qty", "expires_at"(isoformat)}]` 추가. `save` 는 항상 버전 2 로 쓴다.
- `load` 는 버전 1 파일(예약 없음)과 버전 2 파일을 모두 읽는다. 그 밖의 버전은 `StorageError`.

## CLI

- `reserve SKU QTY ORDER_ID --expires ISO시각`, `release ORDER_ID`, `fulfill ORDER_ID`.
- `reservations [SKU]`: 한 줄에 하나씩 `ORDER_ID<TAB>SKU<TAB>QTY<TAB>만료시각(isoformat)`.
- `list` 와 `low` 의 출력 끝에 `AVAILABLE` 열을 붙인다: `SKU<TAB>NAME<TAB>ON_HAND<TAB>AVAILABLE`.
- 오류는 기존처럼 표준 오류에 `오류: ...`, 종료 코드 1. CLI 의 현재 시각은 실제 현재 시각.
- README 와 DESIGN.md 를 갱신한다.
