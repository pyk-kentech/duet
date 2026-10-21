"""매출 보고서.

## 공통 규칙
- 취소된(cancelled) 주문은 모든 보고서에서 빠진다. 결제 뒤 취소돼 환불 기록이 있어도 마찬가지다.
- 환불된 주문(refunded)과 부분 환불된 주문은 빠지지 않는다. 환불액을 뺀 순액으로 들어간다.
- 날짜는 주문을 만든 날(created) 기준이다. 환불도 환불한 날이 아니라 그 **주문의 날짜**로 잡힌다.
- 기간(start, end)은 양 끝을 포함한다.

## 보고서
- daily_sales(shop, day) -> DailySales(day, orders, gross, refunds, net, tax)
  orders: 주문 수, gross: 주문 합계(total)의 합, refunds: 그 주문들의 환불액(amount) 합,
  net = gross - refunds, tax: 주문 세금 합 - 그 주문들의 환불 세금 합.
- sales_by_category(shop, start, end) -> {카테고리: 순매출}
  줄 net(쿠폰 할인 뒤, 세금 제외)의 합에서 환불한 상품 순액을 뺀다. 배송비는 넣지 않는다.
  카테고리 이름 순. 환불로 0 이 된 카테고리도 남는다.
- top_products(shop, n=5, start=None, end=None) -> [(SKU, 이름, 수량)]
  판매 수량에서 환불 수량을 뺀 값. 수량 큰 순, 같으면 SKU 순. 0 이하는 빼고 앞에서 n 개.
  이름은 그 SKU 가 처음 나온 주문 줄의 이름.
- tax_report(shop, start, end) -> [(세율, 과세 순액, 세금)]
  세율별 과세 순액과 세금. 배송비와 배송비 세금은 기본 세율 칸에 들어간다. 환불분은 뺀다. 세율 순.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .money import ZERO

REPORTED_STATUSES = ("pending", "paid", "shipped", "refunded")


@dataclass
class DailySales:
    day: date
    orders: int = 0
    gross: Decimal = ZERO
    refunds: Decimal = ZERO
    net: Decimal = ZERO
    tax: Decimal = ZERO


def _countable(order) -> bool:
    """보고서에 넣는 주문인가 (취소 주문 제외)."""
    return order.status != "cancelled"


def daily_sales(shop, day: date) -> DailySales:
    result = DailySales(day=day)
    for order in shop.orders:
        if order.created.date() != day:
            continue
        if order.status == "cancelled":
            continue
        result.orders += 1
        result.gross += order.total
        result.tax += order.tax
        for refund in shop.refunds:
            if refund.order_id == order.id:
                result.refunds += refund.amount
                result.tax -= refund.tax
    result.net = result.gross - result.refunds
    return result


def sales_by_category(shop, start: date, end: date) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for order in shop.orders:
        if order.status in ("cancelled",):
            continue
        if not (start <= order.created.date() <= end):
            continue
        for line in order.lines:
            totals[line.category] = totals.get(line.category, ZERO) + line.net
    for refund in shop.refunds:
        order = shop.get_order(refund.order_id)
        if order.status == "cancelled" or not (start <= order.created.date() <= end):
            continue
        for sku, qty in refund.items.items():
            line = order.line(sku)
            totals[line.category] -= line.unit_price * qty
    return {k: totals[k] for k in sorted(totals)}


def top_products(shop, n: int = 5, start: date | None = None, end: date | None = None) -> list[tuple[str, str, int]]:
    sold: dict[str, int] = {}
    names: dict[str, str] = {}
    for order in shop.orders:
        if not _countable(order):
            continue
        d = order.created.date()
        if (start is not None and d < start) or (end is not None and d > end):
            continue
        for line in order.lines:
            sold[line.sku] = sold.get(line.sku, 0) + line.qty
            names.setdefault(line.sku, line.name)
        for refund in shop.refunds:
            if refund.order_id == order.id:
                for sku, qty in refund.items.items():
                    sold[sku] -= qty
    ranked = sorted(((sku, names[sku], q) for sku, q in sold.items() if q > 0), key=lambda t: (-t[2], t[0]))
    return ranked[:n]


def tax_report(shop, start: date, end: date) -> list[tuple[Decimal, Decimal, Decimal]]:
    rows: dict[Decimal, list[Decimal]] = {}
    ship_rate = shop.tax_table.shipping_rate

    def add(rate: Decimal, net: Decimal, tax: Decimal) -> None:
        row = rows.setdefault(rate, [ZERO, ZERO])
        row[0] += net
        row[1] += tax

    for order in shop.orders:
        if order.status not in REPORTED_STATUSES:
            continue
        if order.created.date() < start or order.created.date() > end:
            continue
        for line in order.lines:
            add(line.tax_rate, line.net, line.tax)
        if order.shipping:
            add(ship_rate, order.shipping, order.shipping_tax)
        for refund in shop.refunds:
            if refund.order_id != order.id:
                continue
            for sku, qty in refund.items.items():
                line = order.line(sku)
                part = line.unit_price * qty
                add(line.tax_rate, -part,
                    -(part * line.tax_rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if refund.shipping:
                add(ship_rate, -refund.shipping, -order.shipping_tax)
    return [(rate, rows[rate][0], rows[rate][1]) for rate in sorted(rows)]
