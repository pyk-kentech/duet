"""고객별 요약 보고서 (`report customers`).

고객 이름은 대소문자와 공백을 무시하고 같은 사람으로 본다("kim  min", "Kim Min" 은 같은 고객).
보여 주는 이름은 그 고객의 **가장 먼저 만든 주문**에 적힌 이름이다(앞뒤 공백 제거, 가운데 공백은 그대로).

customer_summary(shop, start=None, end=None) -> [CustomerRow]
- orders: 주문 수, spent: 주문 합계(total)의 합에서 환불액을 뺀 값, refunded: 환불액 합,
  first_order / last_order: 가장 이른·늦은 주문 날짜.
- 결제 전(pending)·취소된 주문은 넣지 않는다. 환불된 주문은 넣는다(reports 모듈의 공통 규칙과 같다).
- 기간은 주문 날짜 기준, 양 끝 포함.
- 정렬: spent 큰 순, 같으면 보여 주는 이름의 casefold 순.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .money import ZERO


@dataclass
class CustomerRow:
    customer: str
    orders: int
    spent: Decimal
    refunded: Decimal
    first_order: date
    last_order: date


def customer_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def customer_summary(shop, start: date | None = None, end: date | None = None) -> list[CustomerRow]:
    refunded_by_order: dict[int, Decimal] = {}
    for refund in shop.refunds:
        refunded_by_order[refund.order_id] = refunded_by_order.get(refund.order_id, ZERO) + refund.amount

    rows: dict[str, CustomerRow] = {}
    for order in sorted(shop.orders, key=lambda o: (o.created, o.id)):
        if order.status in ("pending", "cancelled"):
            continue
        day = order.created.date()
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            continue
        key = customer_key(order.customer)
        refunded = refunded_by_order.get(order.id, ZERO)
        row = rows.get(key)
        if row is None:
            rows[key] = CustomerRow(customer=order.customer.strip(), orders=1, spent=order.total - refunded,
                                    refunded=refunded, first_order=day, last_order=day)
            continue
        row.orders += 1
        row.spent += order.total - refunded
        row.refunded += refunded
        row.first_order = min(row.first_order, day)
        row.last_order = max(row.last_order, day)
    return sorted(rows.values(), key=lambda r: (-r.spent, r.customer.casefold()))
