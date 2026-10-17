# stock 설계

## 모듈
- `stock/models.py`: `Item`(sku, name, on_hand, unit_cost: Decimal), `Movement`(ts, sku, kind, qty, note).
- `stock/errors.py`: `StockError` 와 하위 오류(`UnknownItem`, `DuplicateItem`, `InsufficientStock`, `StorageError`).
- `stock/inventory.py`: `Inventory` — 품목 관리, 입고(receive)·출고(ship)·조정(adjust), 보고(value, low_stock, history). 시각은 생성자의 `clock`(datetime 을 돌려주는 함수)으로만 얻는다.
- `stock/storage.py`: JSON 저장·읽기. 쓰기는 임시 파일 후 `os.replace`. 형식 버전은 `version` 필드.
- `stock/cli.py`: argparse 하위 명령. 바꾸는 명령만 저장한다.

## 규칙
- SKU: 대문자·숫자·`-`, 32자 이하. 수량은 양의 정수, 조정량은 0 이 아닌 정수.
- 출고는 재고(on_hand)를 넘을 수 없다. 조정은 물리적 보정이라 재고가 음수만 아니면 된다.
- 모든 재고 변화는 `Movement` 로 남긴다(출고는 음수).
- 저장 형식이 바뀌면 `version` 을 올리고 이전 버전 파일도 읽을 수 있게 한다.
