"""재고.

판매 단위 SKU 마다 실제 재고(on_hand)와 주문이 잡아 둔 수량(reserved)을 센다.

- 주문(checkout)은 줄마다 수량을 예약한다. 하나라도 모자라면 아무것도 예약하지 않고 InsufficientStock.
- 출고(ship)는 예약을 확정한다: on_hand 와 reserved 가 함께 준다.
- 취소와 출고 전 환불은 예약을 푼다. 출고 후 환불은 restock 을 고른 경우에만 on_hand 를 되돌린다.
- available = on_hand - reserved.
"""

from __future__ import annotations

from typing import Iterable

from .errors import InsufficientStock, ValidationError


def _qty(qty: object) -> int:
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise ValidationError(f"수량은 양의 정수여야 합니다: {qty!r}")
    return qty


class Inventory:
    def __init__(self) -> None:
        self.on_hand: dict[str, int] = {}
        self.reserved: dict[str, int] = {}

    def receive(self, sku: str, qty: int) -> int:
        self.on_hand[sku] = self.on_hand.get(sku, 0) + _qty(qty)
        return self.on_hand[sku]

    def available(self, sku: str) -> int:
        return self.on_hand.get(sku, 0) - self.reserved.get(sku, 0)

    def reserve(self, items: Iterable[tuple[str, int]]) -> None:
        """모두 예약하거나 하나도 예약하지 않는다."""
        need: dict[str, int] = {}
        for sku, qty in items:
            need[sku] = need.get(sku, 0) + _qty(qty)
        short = [f"{sku}(필요 {q}, 가능 {self.available(sku)})" for sku, q in need.items() if q > self.available(sku)]
        if short:
            raise InsufficientStock("재고가 부족합니다: " + ", ".join(short))
        for sku, q in need.items():
            self.reserved[sku] = self.reserved.get(sku, 0) + q

    def release(self, items: Iterable[tuple[str, int]]) -> None:
        """예약을 푼다 (0 아래로는 내려가지 않는다)."""
        for sku, qty in items:
            left = self.reserved.get(sku, 0) - qty
            if left > 0:
                self.reserved[sku] = left
            else:
                self.reserved.pop(sku, None)

    def commit(self, items: Iterable[tuple[str, int]]) -> None:
        """예약한 수량을 출고한다."""
        for sku, qty in items:
            self.on_hand[sku] = self.on_hand.get(sku, 0) - qty
            left = self.reserved.get(sku, 0) - qty
            if left > 0:
                self.reserved[sku] = left
            else:
                self.reserved.pop(sku, None)

    def restock(self, sku: str, qty: int) -> None:
        self.on_hand[sku] = self.on_hand.get(sku, 0) + _qty(qty)

    def skus(self) -> list[str]:
        return sorted(set(self.on_hand) | set(self.reserved))
