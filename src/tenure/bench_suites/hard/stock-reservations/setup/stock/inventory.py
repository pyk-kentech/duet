"""재고 장부: 품목, 입고·출고·조정, 이동 기록."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from stock.errors import DuplicateItem, InsufficientStock, UnknownItem
from stock.models import Item, Movement

SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} 는 1 이상의 정수여야 합니다: {value!r}")
    return value


class Inventory:
    def __init__(self, items=None, movements=None, clock=None):
        self._items: dict[str, Item] = {i.sku: i for i in (items or [])}
        self._movements: list[Movement] = list(movements or [])
        self.clock = clock or datetime.now

    # ------------------------------------------------------------ items
    def add_item(self, sku, name, unit_cost="0"):
        if not isinstance(sku, str) or not SKU_RE.match(sku):
            raise ValueError(f"SKU 형식 오류: {sku!r} (대문자·숫자·-, 32자 이하)")
        if sku in self._items:
            raise DuplicateItem(f"이미 있는 품목: {sku}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("이름이 비어 있습니다")
        try:
            cost = Decimal(str(unit_cost))
        except InvalidOperation as e:
            raise ValueError(f"단가 형식 오류: {unit_cost!r}") from e
        if cost < 0 or not cost.is_finite():
            raise ValueError(f"단가는 0 이상: {unit_cost!r}")
        item = Item(sku=sku, name=name.strip(), unit_cost=cost)
        self._items[sku] = item
        return item

    def item(self, sku):
        try:
            return self._items[sku]
        except KeyError:
            raise UnknownItem(f"없는 품목: {sku}") from None

    def items(self):
        return [self._items[k] for k in sorted(self._items)]

    # ------------------------------------------------------------ movements
    def _record(self, sku, kind, qty, note):
        self._movements.append(Movement(ts=self.clock(), sku=sku, kind=kind, qty=qty, note=note))

    def receive(self, sku, qty, note=""):
        item = self.item(sku)
        _positive_int(qty, "수량")
        item.on_hand += qty
        self._record(sku, "receive", qty, note)

    def ship(self, sku, qty, note=""):
        item = self.item(sku)
        _positive_int(qty, "수량")
        if qty > item.on_hand:
            raise InsufficientStock(f"{sku}: 재고 {item.on_hand}개, 요청 {qty}개")
        item.on_hand -= qty
        self._record(sku, "ship", -qty, note)

    def adjust(self, sku, delta, reason):
        """실사 등 물리적 보정. 사유가 필요하다."""
        item = self.item(sku)
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
            raise ValueError(f"조정량은 0 이 아닌 정수: {delta!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("조정 사유가 필요합니다")
        if item.on_hand + delta < 0:
            raise InsufficientStock(f"{sku}: 재고가 음수가 됩니다 ({item.on_hand} {delta:+d})")
        item.on_hand += delta
        self._record(sku, "adjust", delta, reason.strip())

    # ------------------------------------------------------------ reports
    def value(self):
        return sum((i.unit_cost * i.on_hand for i in self._items.values()), Decimal("0"))

    def low_stock(self, threshold):
        return [i for i in self.items() if i.on_hand <= threshold]

    def history(self, sku=None):
        if sku is not None:
            self.item(sku)
        return [m for m in self._movements if sku is None or m.sku == sku]
