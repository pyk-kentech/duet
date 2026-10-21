"""가게(Shop): 상품·재고·쿠폰·주문·환불을 묶는 진입점.

시각은 생성자의 clock(datetime 을 돌려주는 함수)으로만 얻는다. 주문 번호는 1001 부터, 환불 번호는 1 부터
차례로 붙는다.

## 주문 흐름
- checkout: 가격 계산 -> 쿠폰 확인 -> 세금·배송비 -> 재고 예약 -> 쿠폰 uses +1 -> pending 주문.
  재고가 모자라거나 쿠폰을 쓸 수 없으면 아무것도 바뀌지 않는다.
- pay: pending -> paid.
- ship: paid -> shipped. 예약한 재고를 출고한다.
- cancel: pending·paid -> cancelled. 예약을 푼다. paid 였다면 전액 환불 기록(reason "cancel")을 남긴다.
- refund: paid·shipped 주문의 부분·전액 환불(금액 규칙은 refunds 모듈). 출고 전이면 환불한 수량만큼 예약을
  풀고, 출고 뒤면 restock=True 일 때만 재고를 되돌린다. 모든 수량을 환불하면 refunded.
  **환불은 쿠폰 사용 횟수를 돌려주지 않는다** (쿠폰은 쓴 것으로 본다).
- expire_pending(max_age): 만든 지 max_age 보다 오래된(같으면 아님) pending 주문을 취소한다.
- 주문의 상태 변화는 이벤트 기록(Shop.events)에 남는다: created, paid, shipped, cancelled(자동 취소는
  detail "expired"), refunded(detail "환불 R: 금액"), repriced. CLI `history ID` 로 본다.
- reprice: pending 주문의 줄 단가·할인·세금·배송비를 지금 상품 가격으로 다시 계산한다(가격을 고친 뒤
  결제 전 주문을 맞출 때). 수량·쿠폰 목록은 그대로이고 쿠폰 사용 횟수는 바꾸지 않는다. 쿠폰 조건
  (만료·최소 금액·사용 한도)은 다시 확인하지 않는다. 그 사이 삭제된 쿠폰은 빼고 계산한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Iterable

from .cart import Cart, Quote
from .catalog import Catalog, Product, Variant
from .errors import CouponError, InvalidState, NotFound, ValidationError
from .inventory import Inventory
from .money import ZERO, fmt, round_money, total
from .orders import STATUSES, Event, Order, OrderLine, Refund, check_transition, set_status
from .pricing import Coupon, PricedLine, apply_coupons, check_coupons, make_coupon, normalize_code, price_lines
from .refunds import compute_refund, remaining_qty
from .shipping import check_region, shipping_cost
from .tax import TaxTable, line_tax

SETTINGS_CHOICES = {"locale": ("default", "eu"), "tax_display": ("exclusive", "inclusive")}
FIRST_ORDER_ID = 1001


@dataclass
class Settings:
    """locale: default | eu (CSV 형식), tax_display: exclusive | inclusive (show·quote 줄 표시)."""

    locale: str = "default"
    tax_display: str = "exclusive"

    def set(self, key: str, value: str) -> None:
        if key not in SETTINGS_CHOICES:
            raise ValidationError(f"모르는 설정: {key} (가능: {', '.join(SETTINGS_CHOICES)})")
        if value not in SETTINGS_CHOICES[key]:
            raise ValidationError(f"{key} 값은 {', '.join(SETTINGS_CHOICES[key])} 중 하나입니다: {value}")
        setattr(self, key, value)


class Shop:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or datetime.now
        self.catalog = Catalog()
        self.inventory = Inventory()
        self.tax_table = TaxTable()
        self.settings = Settings()
        self.coupons: dict[str, Coupon] = {}
        self.orders: list[Order] = []
        self.refunds: list[Refund] = []
        self.events: list[Event] = []
        self.next_order_id = FIRST_ORDER_ID
        self.next_refund_id = 1

    # ------------------------------------------------------------------ 상품·재고
    def add_product(self, sku: str, name: str, category: str, price: object, **kw) -> Product:
        return self.catalog.add_product(sku, name, category, price, **kw)

    def add_variant(self, product_sku: str, sku: str, **kw) -> Variant:
        return self.catalog.add_variant(product_sku, sku, **kw)

    def receive(self, sku: str, qty: int) -> int:
        """입고. 판매 중지 상품도 입고할 수 있지만, 변형이 있는 상품 SKU 에는 못 한다."""
        if sku not in self.catalog:
            raise NotFound(f"없는 상품: {sku}")
        if self.catalog.has_variants(sku):
            raise ValidationError(f"변형 SKU 로 입고해야 합니다: {sku}")
        return self.inventory.receive(sku, qty)

    # ------------------------------------------------------------------ 쿠폰
    def add_coupon(self, code: str, kind: str, value: object = 0, **kw) -> Coupon:
        coupon = make_coupon(code, kind, value, **kw)
        if coupon.code in self.coupons:
            raise ValidationError(f"이미 있는 쿠폰: {coupon.code}")
        self.coupons[coupon.code] = coupon
        return coupon

    def remove_coupon(self, code: str) -> None:
        self.coupons.pop(self.coupon(code).code)

    def coupon(self, code: str) -> Coupon:
        c = (code or "").strip().upper()
        if c not in self.coupons:
            raise NotFound(f"없는 쿠폰: {code}")
        return self.coupons[c]

    def coupons_list(self) -> list[Coupon]:
        return [self.coupons[k] for k in sorted(self.coupons)]

    def _coupons_for(self, codes: Iterable[str]) -> list[Coupon]:
        out = []
        for code in codes:
            c = normalize_code(code)
            if c not in self.coupons:
                raise CouponError(f"없는 쿠폰: {code}")
            out.append(self.coupons[c])
        return out

    # ------------------------------------------------------------------ 견적·주문
    def quote(self, items: Iterable[tuple[str, int]], region: str = "domestic", coupons: Iterable[str] = ()) -> Quote:
        """주문 전 견적. 금액은 같은 조건의 checkout 과 같다. 재고·쿠폰 사용 횟수는 건드리지 않는다.

        쿠폰 조건(만료·한도·최소 금액·함께 쓰기)은 checkout 과 똑같이 확인해 CouponError 를 낸다.
        """
        cart = Cart(self.catalog)
        for sku, qty in items:
            cart.add(sku, qty)
        return cart.quote(region=region, coupons=self._coupons_for(coupons), tax_table=self.tax_table,
                          today=self.clock().date())

    def checkout(self, items: Iterable[tuple[str, int]], customer: str, region: str = "domestic",
                 coupons: Iterable[str] = ()) -> Order:
        """새 주문(pending)을 만든다.

        items: [(SKU, 수량), ...] — 같은 SKU 는 합친다. customer: 비어 있지 않은 이름(앞뒤 공백 제거).
        region: domestic | eu | world. coupons: 쿠폰 코드들(대소문자 무시).
        실패하면(ValidationError, NotFound, CouponError, InsufficientStock) 아무것도 바뀌지 않는다.
        """
        customer = (customer or "").strip()
        if not customer:
            raise ValidationError("고객 이름이 비었습니다")
        check_region(region)
        now = self.clock()
        priced = price_lines(self.catalog, items)
        used = self._coupons_for(coupons)
        subtotal = total(p.amount for p in priced)
        check_coupons(used, subtotal, now.date())
        discounts, free_shipping = apply_coupons(priced, used)
        lines = []
        for p, d in zip(priced, discounts):
            rate = self.tax_table.rate_for(p.category)
            lines.append(OrderLine(sku=p.sku, name=p.name, category=p.category, qty=p.qty, list_price=p.list_price,
                                   unit_price=p.unit_price, discount=d, tax_rate=rate,
                                   tax=line_tax(p.amount - d, rate)))
        weight = sum(p.weight_g * p.qty for p in priced)
        shipping = ZERO if free_shipping else shipping_cost(region, weight, subtotal)
        shipping_tax = line_tax(shipping, self.tax_table.shipping_rate)
        self.inventory.reserve([(p.sku, p.qty) for p in priced])
        for c in used:
            c.uses += 1
        order = Order(id=self.next_order_id, created=now, customer=customer, region=region, lines=lines,
                      coupons=[c.code for c in used], shipping=shipping, shipping_tax=shipping_tax)
        self.next_order_id += 1
        self.orders.append(order)
        self._log(order, "created", f"합계 {fmt(order.total)}")
        return order

    def reprice(self, order_id: int) -> Order:
        order = self.get_order(order_id)
        if order.status != "pending":
            raise InvalidState(f"주문 {order.id} 은(는) {order.status} 상태라 다시 계산할 수 없습니다")
        priced = []
        for line in order.lines:
            s = self.catalog.resolve(line.sku)
            pct = self.catalog.tier_percent(s.product_sku, line.qty)
            unit = round_money(s.price * (100 - pct) / 100)
            priced.append(PricedLine(sku=s.sku, product_sku=s.product_sku, name=s.name, category=s.category,
                                     qty=line.qty, list_price=s.price, unit_price=unit, weight_g=s.weight_g))
        used = [self.coupons[c] for c in order.coupons if c in self.coupons]
        discounts, free_shipping = apply_coupons(priced, used)
        order.lines = [OrderLine(sku=p.sku, name=p.name, category=p.category, qty=p.qty, list_price=p.list_price,
                                 unit_price=p.unit_price, discount=d, tax_rate=self.tax_table.rate_for(p.category),
                                 tax=line_tax(p.amount - d, self.tax_table.rate_for(p.category)))
                       for p, d in zip(priced, discounts)]
        weight = sum(p.weight_g * p.qty for p in priced)
        subtotal = total(p.amount for p in priced)
        order.shipping = ZERO if free_shipping else shipping_cost(order.region, weight, subtotal)
        order.shipping_tax = line_tax(order.shipping, self.tax_table.shipping_rate)
        order.coupons = [c.code for c in used]
        self._log(order, "repriced", f"합계 {fmt(order.total)}")
        return order

    def _log(self, order: Order, kind: str, detail: str = "") -> None:
        self.events.append(Event(ts=self.clock(), order_id=order.id, kind=kind, detail=detail))

    def history(self, order_id: int) -> list[Event]:
        """그 주문의 이벤트, 기록된 순서."""
        order = self.get_order(order_id)
        return [e for e in self.events if e.order_id == order.id]

    def status_summary(self) -> list[tuple[str, int, Decimal]]:
        """상태별 (상태, 주문 수, 합계 total) — 상태 순서는 STATUSES. 주문이 없는 상태도 0 으로 나온다.

        보고서가 아니라 운영 화면용이다: 미결제·취소 주문도 그대로 센다.
        """
        counts = {s: 0 for s in STATUSES}
        sums = {s: ZERO for s in STATUSES}
        for order in self.orders:
            counts[order.status] += 1
            sums[order.status] += order.total
        return [(s, counts[s], sums[s]) for s in STATUSES]

    def low_stock(self, threshold: int) -> list[tuple[str, int]]:
        """판매 중인 단위 중 available 이 threshold 이하인 것, SKU 순."""
        return [(s.sku, self.inventory.available(s.sku)) for s in self.catalog.sellables()
                if self.inventory.available(s.sku) <= threshold]

    def get_order(self, order_id: int) -> Order:
        for order in self.orders:
            if order.id == order_id:
                return order
        raise NotFound(f"없는 주문: {order_id}")

    def orders_list(self, status: str | None = None) -> list[Order]:
        """주문들, 번호 순. status 를 주면 그 상태만 (모르는 상태는 ValidationError)."""
        if status is not None and status not in STATUSES:
            raise ValidationError(f"모르는 주문 상태: {status}")
        found = [o for o in self.orders if status is None or o.status == status]
        return sorted(found, key=lambda o: o.id)

    def refunds_for(self, order_id: int) -> list[Refund]:
        """그 주문의 환불들, 만든 순서."""
        return [r for r in self.refunds if r.order_id == order_id]

    # ------------------------------------------------------------------ 상태 변경
    def pay(self, order_id: int) -> Order:
        """결제 완료 표시 (pending -> paid). 실제 결제 연동은 이 패키지 밖에서 한다."""
        order = self.get_order(order_id)
        set_status(order, "paid")
        order.paid_at = self.clock()
        self._log(order, "paid")
        return order

    def ship(self, order_id: int) -> Order:
        """출고 (paid -> shipped). 예약한 재고가 실제로 빠진다."""
        order = self.get_order(order_id)
        check_transition(order, "shipped")
        self.inventory.commit([(line.sku, line.qty) for line in order.lines])
        order.status = "shipped"
        order.shipped_at = self.clock()
        self._log(order, "shipped")
        return order

    def _release_stock(self, order: Order, items: dict[str, int] | None = None) -> None:
        """출고 전 주문의 예약을 푼다. items 가 없으면 남은 수량 전부."""
        if items is None:
            items = {sku: q for sku, q in remaining_qty(order, self.refunds_for(order.id)).items() if q > 0}
        self.inventory.release(items.items())

    def _record_refund(self, order: Order, items: dict[str, int] | None, reason: str) -> Refund:
        calc = compute_refund(order, items, self.refunds_for(order.id))
        refund = Refund(id=self.next_refund_id, order_id=order.id, created=self.clock(), items=calc.items,
                        net=calc.net, shipping=calc.shipping, tax=calc.tax, reason=reason)
        self.next_refund_id += 1
        self.refunds.append(refund)
        return refund

    def cancel(self, order_id: int) -> Order:
        """주문 취소 (pending·paid -> cancelled). 예약을 풀고, 결제된 주문이면 전액 환불 기록을 남긴다."""
        order = self.get_order(order_id)
        check_transition(order, "cancelled")
        self._release_stock(order)
        if order.status == "paid":
            self._record_refund(order, None, "cancel")
        order.status = "cancelled"
        self._log(order, "cancelled")
        return order

    def refund(self, order_id: int, items: dict[str, int] | None = None, *, restock: bool = False,
               reason: str = "") -> Refund:
        """환불. items 가 None 이면 전액(남은 것 전부 + 배송비). 금액 규칙은 refunds 모듈."""
        order = self.get_order(order_id)
        if order.status not in ("paid", "shipped"):
            raise InvalidState(f"주문 {order.id} 은(는) {order.status} 상태라 환불할 수 없습니다")
        refund = self._record_refund(order, items, reason)
        if order.status == "paid":
            self._release_stock(order, refund.items)
        elif restock:
            for sku, q in refund.items.items():
                self.inventory.restock(sku, q)
        if not any(q > 0 for q in remaining_qty(order, self.refunds_for(order.id)).values()):
            order.status = "refunded"
        self._log(order, "refunded", f"환불 {refund.id}: {fmt(refund.amount)}")
        return refund

    def expire_pending(self, max_age: timedelta) -> list[int]:
        """오래된 pending 주문을 취소하고 그 번호들을 돌려준다(번호 순)."""
        now = self.clock()
        expired = []
        for o in self.orders_list("pending"):
            if now - o.created > max_age:
                order = self.get_order(o.id)
                self.inventory.release([(line.sku, line.qty) for line in order.lines])
                order.status = "cancelled"
                self.events.append(Event(now, order.id, "cancelled", "expired"))
                expired.append(order.id)
        return expired
