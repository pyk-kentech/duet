이 작업 폴더의 기존 프로젝트 `stock`(재고 관리 라이브러리 + CLI)을 **여러 창고**를 다루도록 확장한다. 아래에 적힌 것 말고는 기존 동작을 바꾸지 않는다(기존 사용법이 그대로 돌아야 한다). 기존 모듈 구조와 관례(DESIGN.md)를 따르고, 필요하면 모듈을 더한다. 테스트도 더한다.

## 창고

- 창고 코드: `^[A-Z][A-Z0-9]{0,7}$`. 이름: 앞뒤 공백을 뗀 비어 있지 않은 문자열.
- 기본 창고 `MAIN`(이름 `Main`)은 늘 있고 지울 수 없다.
- `Inventory.add_warehouse(code, name)`: 형식이 틀리면 ValueError, 이미 있으면 `DuplicateWarehouse`.
- `Inventory.warehouses() -> list`: 코드 순. 각 항목은 `code`, `name` 속성이 있다.
- `Inventory.remove_warehouse(code)`: 없으면 `UnknownWarehouse`, `MAIN` 이면 ValueError, 그 창고에 재고가 하나라도 남아 있으면 `WarehouseNotEmpty`. 지워도 그 창고의 이동 기록은 남는다.
- 새 오류 `UnknownWarehouse`, `DuplicateWarehouse`, `WarehouseNotEmpty` 는 `StockError` 하위이며 `stock` 패키지에서 import 할 수 있다.

## 창고별 재고

- `receive`, `ship`, `adjust` 에 키워드 인자 `warehouse="MAIN"` 을 더한다. 없는 창고면 `UnknownWarehouse`.
- **출고·조정의 한도는 그 창고의 재고 기준**이다: 그 창고 재고보다 많이 출고하면 `InsufficientStock`(다른 창고까지 합하면 충분해도), 조정으로 그 창고 재고가 음수가 되어도 `InsufficientStock`.
- `Item.on_hand` 는 **모든 창고의 합계**다. 그래서 `value()`, `low_stock()`, `list` 출력은 지금처럼 합계 기준이다.
- `Inventory.on_hand(sku, warehouse=None) -> int`: None 이면 합계, 아니면 그 창고의 재고(없는 품목은 `UnknownItem`, 없는 창고는 `UnknownWarehouse`).
- `Inventory.stock_by_warehouse(sku) -> dict[str, int]`: 모든 창고를 코드 순 키로(재고 0 포함).
- `Movement` 에 `warehouse` 속성(기본 `"MAIN"`)을 더한다. 기존처럼 위치 인자 5개(`ts, sku, kind, qty, note`)로도 만들 수 있어야 한다.
- `history(sku=None, warehouse=None)`: warehouse 를 주면 그 창고의 이동만(없는 창고는 `UnknownWarehouse`).
- 생성자 `Inventory(items=None, movements=None, clock=None)` 는 그대로 쓸 수 있다: 넘긴 `Item` 의 `on_hand` 는 `MAIN` 재고로 본다.

## 창고 간 이동

- `Inventory.transfer(sku, qty, src, dst, note="")`: `src` 에서 `dst` 로 옮긴다. qty 는 양의 정수(아니면 ValueError), `src == dst` 면 ValueError, 없는 창고는 `UnknownWarehouse`, `src` 재고보다 많으면 `InsufficientStock`. 합계와 `value()` 는 바뀌지 않는다.
- 같은 시각의 이동 기록 두 개를 이 순서로 남긴다: `src` 에 `kind="transfer-out"`, `qty=-qty`, `dst` 에 `kind="transfer-in"`, `qty=qty`, 메모는 둘 다 note.

## 보고 (`stock.reports`, 새 모듈)

- `low_stock_by_warehouse(inv, threshold) -> list[tuple[str, str, int]]`: 모든 창고 × 모든 품목 조합에서 그 창고 재고가 threshold 이하인 것을 `(창고 코드, SKU, 재고)` 로, 창고 코드 순 다음 SKU 순.
- `movements_summary(inv, start, end) -> dict[str, dict[str, int]]`: `start <= ts < end` 인 이동을 창고별·kind 별로 수량(부호 그대로)을 더한다. 이동이 없는 창고는 넣지 않는다. 바깥 키는 창고 코드 순, 안쪽 키는 kind 이름 순.

## 저장 (`stock.storage`)

- 형식 버전 2: 품목은 `on_hand` 대신 `"stock": {"창고 코드": 수량, ...}`(0 인 창고는 빼도 된다), 최상위에 `"warehouses": [{"code", "name"}, ...]`(MAIN 포함), 이동 기록마다 `"warehouse"`. `save` 는 늘 버전 2 로 쓴다.
- `load` 는 버전 1(지금 형식: 품목의 `on_hand` 는 MAIN 재고, 이동 기록은 MAIN)과 버전 2 를 모두 읽는다. 그 밖의 버전은 `StorageError`. 버전 2 에 없는 창고의 재고나 이동이 있으면 `StorageError`.

## CLI

- `receive`, `ship`, `adjust` 에 `--wh CODE`(기본 MAIN).
- `wh-add CODE NAME`, `wh-rm CODE`.
- `warehouses` → 코드 순으로 한 줄에 `CODE<TAB>NAME<TAB>그 창고의 모든 품목 재고 합`.
- `transfer SKU QTY FROM TO [--note 메모]`.
- `where SKU` → 코드 순으로 `CODE<TAB>QTY`(0 포함).
- `list --wh CODE` → `SKU<TAB>NAME<TAB>그 창고 재고`. `--wh` 가 없으면 지금 출력(합계) 그대로.
- `history [SKU] [--wh CODE]`: 출력 형식은 그대로(창고 열을 더하지 않는다), `--wh` 는 거르기만 한다.
- 오류는 지금처럼 표준 오류에 `오류: ...`, 종료 코드 1, 파일은 바꾸지 않는다.
- README 와 DESIGN.md 를 갱신한다.
