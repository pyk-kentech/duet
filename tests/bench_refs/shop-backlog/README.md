# shop

작은 온라인 가게의 주문 관리 라이브러리와 CLI. 표준 라이브러리만 쓴다(Python 3.11+).
상품·변형, 재고, 장바구니 견적, 수량 할인, 쿠폰, 세금, 배송비, 주문·결제·출고·취소, 환불, 보고서,
CSV 내보내기·가져오기, JSON 데이터 파일을 다룬다. 금액은 모두 EUR, `Decimal`, 센트 단위(ROUND_HALF_UP).

```bash
python -m pytest -q        # 테스트
python -m shop --help
```

## 라이브러리

```python
from datetime import datetime
from shop import Shop
from shop import reports, storage, csvio

shop = Shop(clock=lambda: datetime(2026, 3, 1, 12, 0))
shop.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
shop.add_product("TSHIRT", "T-Shirt", "apparel", "19.99", weight_g=200, tiers="10:10")
shop.add_variant("TSHIRT", "TSHIRT-M", attrs={"size": "M"})
shop.receive("BOOK", 10)
shop.receive("TSHIRT-M", 50)
shop.add_coupon("SAVE10", "percent", "10")
order = shop.checkout([("BOOK", 1), ("TSHIRT-M", 2)], "Kim", region="domestic", coupons=["SAVE10"])
shop.pay(order.id)
shop.ship(order.id)
shop.refund(order.id, {"BOOK": 1})
storage.save(shop, "shop.json")
```

공개 API(`shop` 에서 import): `Shop`, `Catalog`, `Product`, `Variant`, `Sellable`, `Cart`, `Quote`, `QuoteLine`,
`Coupon`, `COUPON_KINDS`, `Order`, `OrderLine`, `Refund`, `STATUSES`, `Inventory`, `TaxTable`, `Settings`,
오류 `ShopError`, `ValidationError`, `NotFound`, `InsufficientStock`, `InvalidState`, `CouponError`, `StorageError`.
모듈 `shop.reports`, `shop.customers`, `shop.storage`, `shop.csvio`, `shop.money`.

## 규칙 요약

### 상품
- SKU: 대문자·숫자·`-`, 32자 이하. 카테고리: 소문자로 시작하는 `[a-z0-9_-]`.
- 변형이 있는 상품은 변형 SKU 로만 주문·입고한다. 변형 이름은 `상품 이름 (속성값, 속성값)`.
- 판매 중지(`active=False`) 상품은 주문할 수 없다.

### 가격
- 수량 할인 구간 `"10:5,50:10"` = 10개 이상 5%, 50개 이상 10%. **같은 상품에 속한 줄들(변형들)의 수량 합**으로
  구간을 고르고, 그 할인율을 상품의 모든 줄에 적용한다(견적·주문·reprice 모두).
- 할인율은 **단가에** 적용해 센트로 반올림한 뒤 수량을 곱한다(0.99 에 5% → 0.94, 10개 = 9.40).
- 같은 SKU 를 여러 번 주면 한 줄로 합친다.

### 쿠폰
- 종류: `percent`(주문 금액 %), `fixed`(금액), `category_percent`(그 카테고리 줄만 %), `free_shipping`(배송비 0),
  `bundle`(N+1: value = N, category 필수. 그 카테고리의 줄마다 `수량 // (N+1)` 개 무료, 줄마다 따로 셈).
- 코드는 대소문자를 가리지 않는다. 만료일 당일까지 쓸 수 있다. `max_uses` 에 닿으면 못 쓴다.
- `min_subtotal` 은 쿠폰 할인 전(수량 할인 뒤) 소계와 비교한다.
- 함께 쓰기: free_shipping 을 뺀 쿠폰이 둘 이상이면 모두 `stackable` 이어야 한다.
  **free_shipping 쿠폰은 stackable 과 상관없이 함께 쓸 수 있다.**
- 적용 순서: bundle → category_percent → percent → fixed. 각 쿠폰은 앞 쿠폰이 깎고 남은 금액에 적용한다.
  percent·fixed 의 할인액은 줄들의 남은 금액 비율로 나누고, 반올림으로 남는 센트는 가장 큰 줄에 몰아준다.
- 주문이 만들어지면 쓴 쿠폰의 `uses` 가 1 오른다. 주문이 취소되면(cancel, expire-pending) 1 내린다(0 아래로는
  안 내림, 삭제된 쿠폰은 무시). **환불은 쿠폰 사용 횟수를 돌려주지 않는다.**

### 세금·배송비
- 세율: 카테고리별, 기본 19%, books·food 7%. 세금은 줄마다 쿠폰 할인 뒤 금액에 매겨 센트로 반올림한다.
- 배송비: domestic 4.90 / eu 9.90 / world 19.90, 2kg 를 넘으면 시작된 1kg 마다 1.00 / 2.50 / 5.00.
- 국내는 상품 소계 50.00 이상이면 무료. 이 소계는 **쿠폰 할인 전** 금액이다.
- 배송비에는 기본 세율의 세금이 붙는다.
- `tax_display = inclusive` 면 show·quote 의 줄 단가·줄 금액만 세금 포함으로 보여 준다. 합계 부분은 같다.

### 주문
- 판매 채널 `channel`: `web`(기본), `store`, `phone`.
- 번호는 1001 부터. 상태: `pending` → `paid` → `shipped`, `pending`·`paid` → `cancelled`,
  `paid`·`shipped` → (모든 수량을 환불하면) `refunded`.
- 주문(checkout)은 재고를 예약한다(모자라면 전체 거절). 출고는 예약을 확정하고, 취소는 예약을 푼다.
- 결제된 주문을 취소하면 전액 환불 기록(reason `cancel`)이 남는다.
- `expire_pending(max_age)` / `expire-pending --hours H`: 만든 지 그 시간보다 오래된 미결제 주문을 취소한다.
- 상태 변화는 이벤트 기록(`Shop.history(id)`, CLI `history`)에 남는다.
- 견적(quote)은 같은 조건으로 주문했을 때와 **같은 금액**이다. 견적은 재고·쿠폰 사용 횟수를 건드리지 않는다.
- `reprice`: 미결제 주문을 지금 가격으로 다시 계산한다(수량·쿠폰 그대로, 쿠폰 사용 횟수·조건은 다시 보지 않음).

### 환불
- 부분 환불: `{SKU: 수량}`. 남은 수량을 넘으면 오류. 줄의 순액 N(쿠폰 할인 뒤)과 세금 T 를 수량 비례로 나눈다:
  이미 r 개, 이번에 q 개면 순액 round(N(r+q)/수량) − round(Nr/수량), 세금도 같은 식. 나눠 환불해도 합계는 N, T.
- 전액 환불(`items=None`, `--all`): 남은 것 전부 + 배송비.
- 배송비는 전액 환불에서만 돌려준다. 부분 환불로 모든 수량을 돌려주면 `refunded` 가 되지만 배송비는 남는다.
- 출고 전 환불은 예약을 풀고, 출고 뒤 환불은 `restock` 일 때만 재고를 되돌린다.

### 보고서 (`shop.reports`, `shop.customers`)
- **결제 전(pending)·취소된 주문은 빠지고, 환불된 주문은 환불액을 뺀 순액으로 들어간다.**
- `daily_sales`·`sales_by_category`·`top_products`·`tax_report` 는 `channel=` 로 판매 채널을 거를 수 있다.
- 날짜는 주문 날짜 기준이다. 환불도 그 주문의 날짜로 잡힌다. 기간은 양 끝 포함.
- `daily_sales`, `sales_by_category`(환불로 0 이 된 카테고리도 남음), `top_products`(수량 큰 순, 같으면 SKU 순),
  `tax_report`(배송비는 기본 세율 칸), `customers.customer_summary`(대소문자·공백을 무시하고 같은 고객으로 묶음).

### CSV
- 로캘 `default`: 구분자 `,` 소수점 `.` / **로캘 `eu`: 구분자 `;` 소수점 `,`**.
- 주문 내보내기: 주문 줄마다 한 행, 모든 상태(취소 포함). 열
  `order_id,date,customer,status,sku,name,qty,unit_price,discount,net,tax,channel`. **표시 모드와 상관없이 세금 제외 금액.**
- 상품 가져오기: 머리글 `sku,name,category,price,weight_g[,tiers]`(tiers 는 `10:5|50:10`). 전부 아니면 전무.

### 데이터 파일
- JSON, `version` 3 (Decimal 값은 문자열). 버전 1·2 파일도 읽는다. 형식은 DESIGN.md.

## CLI

`python -m shop [--data shop.json] <명령>`. 바꾸는 명령만 파일에 쓴다. 오류는 표준 오류에 `오류: ...`, 종료 코드 1
(파일은 그대로). 현재 시각은 환경 변수 `SHOP_NOW`(ISO 시각, 테스트용)가 있으면 그 값.

| 명령 | 출력 |
|---|---|
| `product-add SKU NAME CATEGORY PRICE [--weight G] [--tiers "10:5,50:10"] [--inactive]` | `상품 추가: SKU` |
| `variant-add PRODUCT SKU [--price P] [--weight G] [--attr K=V]...` | `변형 추가: SKU` |
| `products` | `SKU<TAB>NAME<TAB>CATEGORY<TAB>PRICE<TAB>AVAILABLE` (판매 단위, SKU 순) |
| `variants PRODUCT` | `SKU<TAB>NAME<TAB>PRICE<TAB>K=V,K=V` |
| `search TEXT` | `SKU<TAB>NAME<TAB>CATEGORY<TAB>PRICE` (이름·SKU·카테고리, 대소문자 무시) |
| `price-set SKU PRICE` | `가격: SKU PRICE` (이미 만든 주문은 그대로) |
| `activate SKU` / `deactivate SKU` | `판매 재개: SKU` / `판매 중지: SKU` |
| `receive SKU QTY` | `재고: SKU 실재고` |
| `stock` | `SKU<TAB>ON_HAND<TAB>RESERVED<TAB>AVAILABLE` |
| `low-stock N` | available 이 N 이하인 판매 단위 `SKU<TAB>AVAILABLE` |
| `tax-rate CATEGORY RATE` | `세율: CATEGORY RATE%` |
| `tax-rates` | `CATEGORY<TAB>RATE%` 줄들, 마지막 줄 `*<TAB>기본 세율%` |
| `coupon-add CODE KIND [VALUE] [--category C] [--min M] [--stackable] [--expires D] [--max-uses N]` | `쿠폰 추가: CODE` |
| `coupon-rm CODE` | `쿠폰 삭제: CODE` |
| `coupons` | `CODE<TAB>KIND<TAB>VALUE<TAB>USES/MAX` (VALUE: percent 류 `10%`, fixed `5.00`, bundle `2+1`, free_shipping `-`; MAX 없으면 `-`) |
| `quote ITEM... [--region R] [--coupon C]...` | 줄 + 합계 (아래 show 의 줄·합계 부분과 같은 형식) |
| `order ITEM... --customer NAME [--region R] [--coupon C]... [--channel C]` | `주문 1001 생성 (합계 81.20)` |
| `pay ID` / `ship ID` / `cancel ID` | `주문 ID: 새 상태` |
| `reprice ID` | `주문 ID 다시 계산 (합계 X)` |
| `refund ID [ITEM...] [--all] [--restock]` | `환불 R: 금액` |
| `expire-pending --hours H` | `취소: 1001, 1002` 또는 `취소할 주문 없음` |
| `show ID` | 아래 |
| `history ID` | 주문 이벤트 `YYYY-MM-DD HH:MM<TAB>KIND[<TAB>DETAIL]` |
| `orders [--status S] [--channel C]` | `ID<TAB>DATE<TAB>CUSTOMER<TAB>STATUS<TAB>TOTAL` |
| `summary` | 상태마다 `STATUS<TAB>주문 수<TAB>합계` (운영용, 보고서가 아님: 미결제·취소 주문도 센다) |
| `report daily DATE [--channel C]` | `date`, `orders`, `gross`, `refunds`, `net`, `tax` 각 줄 `키<TAB>값` |
| `report category FROM TO [--channel C]` | `CATEGORY<TAB>NET` |
| `report top [-n N] [--from D] [--to D] [--channel C]` | `SKU<TAB>NAME<TAB>QTY` |
| `report tax FROM TO [--channel C]` | `RATE%<TAB>NET<TAB>TAX` (세율은 `7%`, `19%`, `7.5%`) |
| `report customers [--from D] [--to D]` | `CUSTOMER<TAB>ORDERS<TAB>SPENT<TAB>REFUNDED` |
| `export orders FILE` / `export refunds FILE` / `export products FILE` | `내보냄: N줄` |
| `import products FILE` | `가져옴: N개` |
| `config [KEY [VALUE]]` | 설정 보기·바꾸기 (`locale`, `tax_display`) |

ITEM 은 `SKU:수량` 또는 `SKU`(1개).

`show` 출력 (대괄호 줄은 해당할 때만):

```
주문 1001 (shipped)
고객: Kim
날짜: 2026-03-01 12:00
지역: domestic
[채널: phone]          (web 이 아닐 때만)
[쿠폰: BOOKS20]
  BOOK  Python Book  1 x 30.00 = 30.00
  MUG  Mug  2 x 8.50 = 17.00
소계: 47.00
[할인: -6.00]
배송: 4.90
세금: 5.84
합계: 51.74
[환불: -10.12]
```
