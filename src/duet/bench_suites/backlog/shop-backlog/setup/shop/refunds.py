"""환불 금액 계산.

- 부분 환불: items = {SKU: 수량}. 각 수량은 그 줄에서 아직 환불하지 않은 수량 이하(넘으면 ValidationError).
  줄마다 환불 순액은 단가 x 수량, 세금은 그 순액에 줄의 세율을 곱해 센트로 반올림한다.
- 전액 환불(items=None): 남은 것 전부. 주문 순액·세금에서 이미 환불한 몫을 뺀 나머지와 배송비(+ 배송비 세금).
- 배송비는 전액 환불에서만 돌려준다. 부분 환불로 모든 수량을 돌려줘도 배송비는 돌려주지 않는다.
- 이 모듈은 계산만 한다. 상태 변경·재고·기록은 Shop.refund 가 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .errors import ValidationError
from .money import ZERO, total
from .orders import Order, Refund


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


def compute_refund(order: Order, items: dict[str, int] | None, prior: list[Refund]) -> RefundCalc:
    """prior: 이 주문에 이미 있는 환불들."""
    left = remaining_qty(order, prior)
    if items is None:
        todo = {sku: q for sku, q in left.items() if q > 0}
        if not todo:
            raise ValidationError(f"주문 {order.id} 에 환불할 것이 없습니다")
        net = order.net - total(r.net for r in prior)
        tax = order.tax - total(r.tax for r in prior)
        return RefundCalc(todo, net, order.shipping, tax)

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
    net = ZERO
    tax = ZERO
    for sku, qty in todo.items():
        line = order.line(sku)
        part = line.unit_price * qty
        net += part
        tax += (part * line.tax_rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return RefundCalc(todo, net, ZERO, tax)
