과제 명세가 기준이다. 이 절은 다중 창고 확장의 모듈 나누기와 약속을 정한다.

### 모듈별 변경

| 파일 | 바꾸는 것 |
|---|---|
| `stock/errors.py` | `UnknownWarehouse`, `DuplicateWarehouse`, `WarehouseNotEmpty` (모두 `StockError` 하위) |
| `stock/models.py` | `Warehouse`(code, name) dataclass. `Movement` 끝에 `warehouse: str = "MAIN"`(위치 인자 5개 호환) |
| `stock/inventory.py` | 창고 관리(`add_warehouse`, `remove_warehouse`, `warehouses`), 창고별 재고 `_stock: dict[str, dict[str, int]]`(sku → 창고 → 수량), `receive`·`ship`·`adjust` 의 `warehouse` 인자, `on_hand`, `stock_by_warehouse`, `transfer`, `history` 의 `warehouse` 인자 |
| `stock/reports.py` (새) | `low_stock_by_warehouse`, `movements_summary` — `Inventory` 의 공개 메서드만 쓴다 |
| `stock/storage.py` | 버전 2 쓰기, 버전 1·2 읽기 |
| `stock/cli.py` | `--wh`, `wh-add`, `wh-rm`, `warehouses`, `transfer`, `where`, `list --wh`, `history --wh` |
| `stock/__init__.py` | 새 오류·`Warehouse` 다시 내보내기 |

### 약속

- **합계 불변식**: 재고를 바꾸는 모든 경로(receive·ship·adjust·transfer·생성자·load)는 `_stock` 을 바꾼 뒤 `Item.on_hand` 를 그 품목의 창고 합계로 다시 맞춘다. 합계를 따로 더하고 빼지 않는다(어긋남 방지). 내부 함수 `_set(sku, warehouse, qty)` 하나로 모은다.
- **검사 순서**: 품목(`UnknownItem`) → 창고(`UnknownWarehouse`) → 값(ValueError) → 재고 한도(`InsufficientStock`). 실패하면 아무것도 바꾸지 않는다(이동은 두 창고를 모두 확인한 뒤에 바꾼다).
- **이동 기록**: `_record(sku, kind, qty, note, warehouse)` 한 곳에서 만든다. transfer 는 한 번 얻은 `clock()` 값으로 두 기록을 남긴다.
- **저장**: storage 는 `Inventory` 의 생성자 인자 `warehouses=`, `stock=` (내부용 키워드)로 상태를 넣는다. 버전 1 변환(on_hand → MAIN)은 storage 안에서만.
- **보고**: reports 는 `inv.warehouses()`, `inv.items()`, `inv.on_hand(...)`, `inv.history()` 만 쓴다.
- **CLI**: 기존 출력 형식은 바꾸지 않는다(`list`·`history` 는 옵션이 없으면 그대로).
