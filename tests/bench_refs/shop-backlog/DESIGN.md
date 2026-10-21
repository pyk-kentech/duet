# shop 설계

오래 고쳐 온 코드라 비슷한 계산이 여러 곳에 있다. 고칠 때는 같은 규칙을 쓰는 다른 곳도 함께 본다.

## 모듈

| 모듈 | 하는 일 |
|---|---|
| `errors.py` | `ShopError` 와 하위 오류 |
| `money.py` | Decimal 금액 도우미: `round_money`, `fmt`, `percent_of`, `allocate`(비율 나누기) |
| `catalog.py` | `Product`, `Variant`, `Sellable`, `Catalog`(추가·조회·`resolve`·`tier_percent`) |
| `inventory.py` | `Inventory`: on_hand / reserved, 예약·해제·출고·재입고 |
| `tax.py` | `TaxTable`(카테고리 세율), `line_tax`, `gross`, `format_rate` |
| `shipping.py` | 지역별 배송비, 무게 할증, 국내 무료 배송 기준 |
| `pricing.py` | 줄 단가(수량 할인) `price_lines`, `Coupon`, `make_coupon`, `check_coupons`, `apply_coupons` |
| `cart.py` | `Cart` 와 견적 `Quote` (주문 전 금액) |
| `orders.py` | `Order`, `OrderLine`, `Refund` 모델과 상태 전이 규칙 |
| `refunds.py` | 환불 금액 계산 `compute_refund` |
| `store.py` | `Shop`: 위 모듈을 묶는 진입점(주문 흐름), `Settings` |
| `reports.py` | 일별·카테고리별·많이 팔린 상품·세금 보고서 (환불은 주문별로 한 번 모아 O(주문+환불)) |
| `customers.py` | 고객별 요약 보고서 |
| `csvio.py` | 주문·상품 CSV 내보내기, 상품 CSV 가져오기 |
| `storage.py` | JSON 데이터 파일 읽기·쓰기 (형식 버전 관리) |
| `cli.py` | argparse CLI, 출력 형식 |

## 데이터 모델 (`Shop`)
- `catalog: Catalog`, `inventory: Inventory`, `tax_table: TaxTable`, `settings: Settings`
- `coupons: dict[str, Coupon]` (코드 → 쿠폰)
- `orders: list[Order]` (만든 순서), `refunds: list[Refund]` (모든 주문의 환불, 만든 순서)
  - 번호 → 주문, 주문 → 환불 색인(dict)을 함께 둔다. 목록에 직접 더한 것은 길이가 달라지면 다시 색인한다.
- `next_order_id`, `next_refund_id`
- 시각은 `clock()` 으로만 얻는다.

## 금액 규칙
- 모든 금액은 `Decimal`. 계산 중간값은 반올림하지 않고, 정해진 지점(할인 단가, 쿠폰 할인액, 줄 세금, 환불 세금)에서만
  센트로 반올림한다(ROUND_HALF_UP).
- 주문 줄에는 계산 결과(단가·할인·세율·세금)를 그대로 저장한다. 나중에 상품 가격이나 세율이 바뀌어도
  이미 만든 주문·보고서는 바뀌지 않는다(`reprice` 를 부른 미결제 주문만 예외).

## 데이터 파일

최상위 `version` 으로 형식을 구분한다. 저장은 언제나 최신 버전으로 하고, 읽기는 이전 버전도 받는다.
모르는 버전은 `StorageError`.

### 버전 3 (지금)
버전 2 와 구조가 같다. 다른 점:
- Decimal 값은 모두 JSON 문자열이다. 금액(가격, 단가, 할인, 세금, 배송비, 환불 금액, 최소 주문 금액, fixed 쿠폰 값)은
  소수 둘째 자리(`"19.90"`), 비율(세율, 수량 할인율, percent·category_percent 쿠폰 값, bundle 의 N)은 뒤의 0 없는
  문자열(`"7"`, `"7.5"`).
- 주문마다 `"channel"`(`web` | `store` | `phone`). 버전 1·2 파일의 주문은 `web`.
- 쿠폰 `kind` 에 `bundle` 이 있을 수 있다.

### 버전 2
금액·세율은 JSON 숫자(float)다. 날짜·시각은 ISO 문자열.

```json
{
  "version": 2,
  "settings": {"locale": "default", "tax_display": "exclusive"},
  "tax": {"default": 19.0, "rates": {"books": 7.0, "food": 7.0}},
  "products": [{"sku": "TSHIRT", "name": "T-Shirt", "category": "apparel", "price": 19.99, "weight_g": 200,
                "tiers": [[10, 10.0]], "active": true}],
  "variants": [{"sku": "TSHIRT-M", "product_sku": "TSHIRT", "attrs": {"size": "M"}, "price": null, "weight_g": null}],
  "stock": {"on_hand": {"TSHIRT-M": 48}, "reserved": {"TSHIRT-M": 2}},
  "coupons": [{"code": "SAVE10", "kind": "percent", "value": 10.0, "category": null, "min_subtotal": 0.0,
               "stackable": false, "expires": "2026-12-31", "max_uses": null, "uses": 1}],
  "orders": [{"id": 1001, "created": "2026-03-01T12:00:00", "customer": "Kim", "region": "domestic",
              "status": "paid", "coupons": ["SAVE10"], "shipping": 4.9, "shipping_tax": 0.93,
              "paid_at": "2026-03-01T12:05:00", "shipped_at": null,
              "lines": [{"sku": "TSHIRT-M", "name": "T-Shirt (M)", "category": "apparel", "qty": 2,
                         "list_price": 19.99, "unit_price": 19.99, "discount": 4.0, "tax_rate": 19.0, "tax": 6.84}]}],
  "refunds": [{"id": 1, "order_id": 1001, "created": "2026-03-02T09:00:00", "items": {"TSHIRT-M": 1},
               "net": 19.99, "shipping": 0.0, "tax": 3.8, "reason": ""}],
  "next_order_id": 1002,
  "next_refund_id": 2
}
```

- `settings`, `tax`, `variants`, `stock`, `coupons`, `orders`, `refunds`, `next_*` 는 없어도 된다(기본값).
  `products` 는 있어야 한다.
- 쿠폰 `value`: percent 류는 백분율, fixed 는 금액, free_shipping 은 0.

### 버전 1 (0.5 이전)
금액은 정수 센트. 변형·수량 할인·배송 지역·쿠폰 함께 쓰기·사용 한도·표시 모드가 없던 때다.

```json
{
  "version": 1,
  "locale": "default",
  "products": [{"sku": "BOOK", "name": "Python Book", "category": "books", "price_cents": 3000, "weight_g": 800,
                "active": true}],
  "stock": {"BOOK": {"on_hand": 9, "reserved": 1}},
  "coupons": [{"code": "WELCOME", "kind": "fixed", "value": 500, "category": null, "min_cents": 2000,
               "expires": null, "uses": 3}],
  "orders": [{"id": 1001, "created": "2025-11-02T10:00:00", "customer": "Lee", "status": "shipped",
              "coupons": [], "shipping_cents": 490, "shipping_tax_cents": 93,
              "lines": [{"sku": "BOOK", "name": "Python Book", "category": "books", "qty": 1, "price_cents": 3000,
                         "discount_cents": 0, "tax_rate": 7, "tax_cents": 210}]}],
  "refunds": [{"id": 1, "order_id": 1001, "created": "2025-11-05T10:00:00", "items": {"BOOK": 1},
               "net_cents": 3000, "shipping_cents": 0, "tax_cents": 210}]
}
```

- 읽을 때: 줄의 `list_price` = `unit_price` = `price_cents`/100, 지역은 `domestic`, 쿠폰 `value` 는 fixed 면 센트,
  아니면 백분율, `stackable` 은 false, `max_uses` 는 없음, 세율 표와 표시 모드는 기본값, 다음 번호는 가장 큰 번호 + 1.
