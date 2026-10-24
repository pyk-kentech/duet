"""주문과 환불 모델, 주문 상태 규칙.

## 주문 줄 (OrderLine)
- list_price: 정가(판매 단위 가격), unit_price: 수량 할인 뒤 단가, discount: 이 줄에 나뉜 쿠폰 할인액,
  tax_rate: 세율(%), tax: 이 줄의 세금.
- amount = unit_price x qty (쿠폰 전), net = amount - discount, gross = net + tax.

## 주문 (Order)
- subtotal = 줄 amount 합, discount = 줄 discount 합, net = subtotal - discount,
  tax = 줄 세금 합 + 배송비 세금, total = net + shipping + tax.
- 상태: pending(결제 전) -> paid -> shipped. pending·paid 는 cancelled 가 될 수 있다.
  paid·shipped 주문은 환불할 수 있고, 모든 수량을 환불하면 refunded 가 된다.

## 환불 (Refund)
- items: {SKU: 환불 수량}, net: 상품 순액(세금 제외), shipping: 환불한 배송비(세금 제외), tax: 환불한 세금
  (배송비 세금 포함), amount = net + shipping + tax. reason: "cancel" 이면 결제된 주문을 취소하며 생긴 환불.
- 환불 기록은 가게 전체 목록(Shop.refunds)에 order_id 와 함께 쌓인다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .errors import InvalidState, NotFound
from .money import ZERO, total

STATUSES = ("pending", "paid", "shipped", "cancelled", "refunded")
TRANSITIONS = {
    "pending": ("paid", "cancelled"),
    "paid": ("shipped", "cancelled", "refunded"),
    "shipped": ("refunded",),
    "cancelled": (),
    "refunded": (),
}


@dataclass
class OrderLine:
    sku: str
    name: str
    category: str
    qty: int
    list_price: Decimal
    unit_price: Decimal
    discount: Decimal
    tax_rate: Decimal
    tax: Decimal

    @property
    def amount(self) -> Decimal:
        return self.unit_price * self.qty

    @property
    def net(self) -> Decimal:
        return self.amount - self.discount

    @property
    def gross(self) -> Decimal:
        return self.net + self.tax


@dataclass
class Order:
    id: int
    created: datetime
    customer: str
    region: str
    lines: list[OrderLine]
    coupons: list[str] = field(default_factory=list)
    shipping: Decimal = ZERO
    shipping_tax: Decimal = ZERO
    status: str = "pending"
    paid_at: datetime | None = None
    shipped_at: datetime | None = None

    @property
    def subtotal(self) -> Decimal:
        return total(line.amount for line in self.lines)

    @property
    def discount(self) -> Decimal:
        return total(line.discount for line in self.lines)

    @property
    def net(self) -> Decimal:
        return self.subtotal - self.discount

    @property
    def tax(self) -> Decimal:
        return total(line.tax for line in self.lines) + self.shipping_tax

    @property
    def total(self) -> Decimal:
        return self.net + self.shipping + self.tax

    def line(self, sku: str) -> OrderLine:
        for line in self.lines:
            if line.sku == sku:
                return line
        raise NotFound(f"주문 {self.id} 에 없는 상품: {sku}")


@dataclass
class Refund:
    id: int
    order_id: int
    created: datetime
    items: dict[str, int]
    net: Decimal
    shipping: Decimal
    tax: Decimal
    reason: str = ""

    @property
    def amount(self) -> Decimal:
        return self.net + self.shipping + self.tax


@dataclass
class Event:
    """주문 이벤트 기록 한 줄. kind: created, paid, shipped, cancelled, refunded, repriced."""

    ts: datetime
    order_id: int
    kind: str
    detail: str = ""


def check_transition(order: Order, new_status: str) -> None:
    if new_status not in TRANSITIONS.get(order.status, ()):
        raise InvalidState(f"주문 {order.id} 은(는) {order.status} 상태라 {new_status} 로 바꿀 수 없습니다")


def set_status(order: Order, new_status: str) -> None:
    check_transition(order, new_status)
    order.status = new_status
