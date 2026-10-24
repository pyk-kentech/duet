"""환불 금액 계산.

- 부분 환불: items = {SKU: 수량}. 각 수량은 그 줄에서 아직 환불하지 않은 수량 이하(넘으면 ValidationError).
  줄의 순액 N(= 단가 x 수량 - 할인)과 세금 T 를 수량 비례로 나눈다. 그 줄에서 이미 r 개를 환불했고 이번에
  q 개를 환불하면 순액 = round(N(r+q)/수량) - round(Nr/수량), 세금 = round(T(r+q)/수량) - round(Tr/수량).
  그래서 한 줄을 여러 번 나눠 환불해도 합계가 정확히 N, T 다(`line_refund_share`).
- 전액 환불(items=None): 남은 수량 전부를 위 규칙으로 + 배송비(+ 배송비 세금).
- 배송비는 전액 환불에서만 돌려준다. 부분 환불로 모든 수량을 돌려줘도 배송비는 돌려주지 않는다.
- 이 모듈은 계산만 한다. 상태 변경·재고·기록은 Shop.refund 가 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .errors import ValidationError
from .money import ZERO, round_money
from .orders import Order, OrderLine, Refund


@dataclass
class RefundCalc:
    items: dict[str, int]
    net: Decimal
    shipping: Decimal
    tax: Decimal

    @property
    def amount(self) -> Decimal:
        return self.net + self.shipping + self.tax


def refunded_qty(refunds: list[Refund]) -> dict[str, int]:
    done: dict[str, int] = {}
    for r in refunds:
        for sku, q in r.items.items():
            done[sku] = done.get(sku, 0) + q
    return done


def remaining_qty(order: Order, refunds: list[Refund]) -> dict[str, int]:
    """줄마다 아직 환불하지 않은 수량. refunds 는 이 주문의 환불들."""
    done = refunded_qty(refunds)
    return {line.sku: line.qty - done.get(line.sku, 0) for line in order.lines}


def line_refund_share(line: OrderLine, refunded: int) -> tuple[Decimal, Decimal]:
    """그 줄에서 모두 refunded 개를 환불했을 때까지 돌려준 (순액, 세금)의 합."""
    if refunded >= line.qty:
        return line.net, line.tax
    return round_money(line.net * refunded / line.qty), round_money(line.tax * refunded / line.qty)


def _shares(order: Order, todo: dict[str, int], done: dict[str, int]) -> tuple[Decimal, Decimal]:
    net = ZERO
    tax = ZERO
    for sku, qty in todo.items():
        line = order.line(sku)
        before = done.get(sku, 0)
        n0, t0 = line_refund_share(line, before)
        n1, t1 = line_refund_share(line, before + qty)
        net += n1 - n0
        tax += t1 - t0
    return net, tax


def compute_refund(order: Order, items: dict[str, int] | None, prior: list[Refund]) -> RefundCalc:
    """prior: 이 주문에 이미 있는 환불들."""
    done = refunded_qty(prior)
    left = {line.sku: line.qty - done.get(line.sku, 0) for line in order.lines}
    if items is None:
        todo = {sku: q for sku, q in left.items() if q > 0}
        if not todo:
            raise ValidationError(f"주문 {order.id} 에 환불할 것이 없습니다")
        net, tax = _shares(order, todo, done)
        return RefundCalc(todo, net, order.shipping, tax + order.shipping_tax)

    if not items:
        raise ValidationError("환불할 상품을 주어야 합니다")
    todo = {}
    for sku, qty in items.items():
        order.line(sku)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValidationError(f"환불 수량은 양의 정수여야 합니다: {sku} {qty!r}")
        if qty > left[sku]:
            raise ValidationError(f"{sku}: 환불할 수 있는 수량은 {left[sku]}개입니다")
        todo[sku] = qty
    net, tax = _shares(order, todo, done)
    return RefundCalc(todo, net, ZERO, tax)
