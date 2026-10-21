"""매출 보고서.

## 공통 규칙
- 결제 전(pending) 주문과 취소된(cancelled) 주문은 모든 보고서에서 빠진다. 결제 뒤 취소돼 환불 기록이 있어도
  마찬가지다. 미결제 주문은 결제되면 그때부터 (주문 날짜로) 들어간다.
- 환불된 주문(refunded)과 부분 환불된 주문은 빠지지 않는다. 환불액을 뺀 순액으로 들어간다.
- 날짜는 주문을 만든 날(created) 기준이다. 환불도 환불한 날이 아니라 그 **주문의 날짜**로 잡힌다.
- 기간(start, end)은 양 끝을 포함한다.
- channel 을 주면 그 판매 채널의 주문만 센다(None 이면 전부).
- 빠진 환불 금액은 실제 환불 금액과 같다: 줄에서 모두 R 개를 환불했으면 순액 round(N x R / 수량),
  세금 round(T x R / 수량) (refunds.line_refund_share).

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

모든 보고서는 주문·환불 수에 비례하는 시간에 끝난다(환불은 주문별로 한 번 모아 둔다).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .money import ZERO
from .refunds import line_refund_share

EXCLUDED_STATUSES = ("pending", "cancelled")


@dataclass
class DailySales:
    day: date
    orders: int = 0
    gross: Decimal = ZERO
    refunds: Decimal = ZERO
    net: Decimal = ZERO
    tax: Decimal = ZERO


def counted(order, channel: str | None = None) -> bool:
    """보고서에 넣는 주문인가 (결제 전·취소 주문 제외, 채널 거르기)."""
    if order.status in EXCLUDED_STATUSES:
        return False
    return channel is None or order.channel == channel


def _in_range(order, start: date | None, end: date | None) -> bool:
    d = order.created.date()
    return (start is None or d >= start) and (end is None or d <= end)


def refunds_by_order(shop) -> dict[int, list]:
    index: dict[int, list] = {}
    for refund in shop.refunds:
        index.setdefault(refund.order_id, []).append(refund)
    return index


def _refunded_qty(refunds) -> dict[str, int]:
    done: dict[str, int] = {}
    for refund in refunds:
        for sku, qty in refund.items.items():
            done[sku] = done.get(sku, 0) + qty
    return done


def daily_sales(shop, day: date, channel: str | None = None) -> DailySales:
    result = DailySales(day=day)
    by_order = refunds_by_order(shop)
    for order in shop.orders:
        if order.created.date() != day or not counted(order, channel):
            continue
        result.orders += 1
        result.gross += order.total
        result.tax += order.tax
        for refund in by_order.get(order.id, ()):
            result.refunds += refund.amount
            result.tax -= refund.tax
    result.net = result.gross - result.refunds
    return result


def sales_by_category(shop, start: date, end: date, channel: str | None = None) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    by_order = refunds_by_order(shop)
    for order in shop.orders:
        if not counted(order, channel) or not _in_range(order, start, end):
            continue
        for line in order.lines:
            totals[line.category] = totals.get(line.category, ZERO) + line.net
        refunds = by_order.get(order.id)
        if refunds:
            done = _refunded_qty(refunds)
            for line in order.lines:
                if done.get(line.sku):
                    net, _tax = line_refund_share(line, done[line.sku])
                    totals[line.category] -= net
    return {k: totals[k] for k in sorted(totals)}


def top_products(shop, n: int = 5, start: date | None = None, end: date | None = None,
                 channel: str | None = None) -> list[tuple[str, str, int]]:
    sold: dict[str, int] = {}
    names: dict[str, str] = {}
    by_order = refunds_by_order(shop)
    for order in shop.orders:
        if not counted(order, channel) or not _in_range(order, start, end):
            continue
        for line in order.lines:
            sold[line.sku] = sold.get(line.sku, 0) + line.qty
            names.setdefault(line.sku, line.name)
        for refund in by_order.get(order.id, ()):
            for sku, qty in refund.items.items():
                sold[sku] -= qty
    ranked = sorted(((sku, names[sku], q) for sku, q in sold.items() if q > 0), key=lambda t: (-t[2], t[0]))
    return ranked[:n]


def tax_report(shop, start: date, end: date, channel: str | None = None) -> list[tuple[Decimal, Decimal, Decimal]]:
    rows: dict[Decimal, list[Decimal]] = {}
    ship_rate = shop.tax_table.shipping_rate
    by_order = refunds_by_order(shop)

    def add(rate: Decimal, net: Decimal, tax: Decimal) -> None:
        row = rows.setdefault(rate, [ZERO, ZERO])
        row[0] += net
        row[1] += tax

    for order in shop.orders:
        if not counted(order, channel) or not _in_range(order, start, end):
            continue
        for line in order.lines:
            add(line.tax_rate, line.net, line.tax)
        if order.shipping:
            add(ship_rate, order.shipping, order.shipping_tax)
        refunds = by_order.get(order.id)
        if not refunds:
            continue
        done = _refunded_qty(refunds)
        for line in order.lines:
            if done.get(line.sku):
                net, tax = line_refund_share(line, done[line.sku])
                add(line.tax_rate, -net, -tax)
        for refund in refunds:
            if refund.shipping:
                add(ship_rate, -refund.shipping, -order.shipping_tax)
    return [(rate, rows[rate][0], rows[rate][1]) for rate in sorted(rows)]
