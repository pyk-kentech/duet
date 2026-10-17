"""재고 장부: 품목, 창고, 입고·출고·조정·이동, 이동 기록."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from stock.errors import (
    DuplicateItem, DuplicateWarehouse, InsufficientStock, UnknownItem, UnknownWarehouse, WarehouseNotEmpty,
)
from stock.models import Item, Movement, Warehouse

SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")
WH_RE = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")
MAIN = "MAIN"


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} 는 1 이상의 정수여야 합니다: {value!r}")
    return value


class Inventory:
    def __init__(self, items=None, movements=None, clock=None, *, warehouses=None, stock=None):
        self._items: dict[str, Item] = {i.sku: i for i in (items or [])}
        self._movements: list[Movement] = list(movements or [])
        self.clock = clock or datetime.now
        self._warehouses: dict[str, Warehouse] = {MAIN: Warehouse(MAIN, "Main")}
        for w in warehouses or []:
            self._warehouses[w.code] = w
        self._stock: dict[str, dict[str, int]] = {}
        for item in self._items.values():
            given = (stock or {}).get(item.sku)
            self._stock[item.sku] = dict(given) if given is not None else {MAIN: item.on_hand}
            self._sync(item.sku)

    # ------------------------------------------------------------ 내부
    def _sync(self, sku):
        self._items[sku].on_hand = sum(self._stock[sku].values())

    def _set(self, sku, warehouse, qty):
        self._stock[sku][warehouse] = qty
        self._sync(sku)

    def _wh(self, code):
        if code not in self._warehouses:
            raise UnknownWarehouse(f"없는 창고: {code}")
        return code

    def _record(self, sku, kind, qty, note, warehouse, ts=None):
        self._movements.append(Movement(ts=ts or self.clock(), sku=sku, kind=kind, qty=qty, note=note,
                                        warehouse=warehouse))

    # ------------------------------------------------------------ 창고
    def add_warehouse(self, code, name):
        if not isinstance(code, str) or not WH_RE.match(code):
            raise ValueError(f"창고 코드 형식 오류: {code!r}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("창고 이름이 비어 있습니다")
        if code in self._warehouses:
            raise DuplicateWarehouse(f"이미 있는 창고: {code}")
        w = Warehouse(code, name.strip())
        self._warehouses[code] = w
        return w

    def warehouses(self):
        return [self._warehouses[k] for k in sorted(self._warehouses)]

    def remove_warehouse(self, code):
        self._wh(code)
        if code == MAIN:
            raise ValueError("MAIN 창고는 지울 수 없습니다")
        if any(s.get(code, 0) for s in self._stock.values()):
            raise WarehouseNotEmpty(f"재고가 남은 창고: {code}")
        del self._warehouses[code]
        for s in self._stock.values():
            s.pop(code, None)

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
        self._stock[sku] = {}
        return item

    def item(self, sku):
        try:
            return self._items[sku]
        except KeyError:
            raise UnknownItem(f"없는 품목: {sku}") from None

    def items(self):
        return [self._items[k] for k in sorted(self._items)]

    def on_hand(self, sku, warehouse=None):
        item = self.item(sku)
        if warehouse is None:
            return item.on_hand
        return self._stock[sku].get(self._wh(warehouse), 0)

    def stock_by_warehouse(self, sku):
        self.item(sku)
        return {w: self._stock[sku].get(w, 0) for w in sorted(self._warehouses)}

    # ------------------------------------------------------------ movements
    def receive(self, sku, qty, note="", warehouse=MAIN):
        self.item(sku)
        self._wh(warehouse)
        _positive_int(qty, "수량")
        self._set(sku, warehouse, self.on_hand(sku, warehouse) + qty)
        self._record(sku, "receive", qty, note, warehouse)

    def ship(self, sku, qty, note="", warehouse=MAIN):
        self.item(sku)
        self._wh(warehouse)
        _positive_int(qty, "수량")
        have = self.on_hand(sku, warehouse)
        if qty > have:
            raise InsufficientStock(f"{sku}@{warehouse}: 재고 {have}개, 요청 {qty}개")
        self._set(sku, warehouse, have - qty)
        self._record(sku, "ship", -qty, note, warehouse)

    def adjust(self, sku, delta, reason, warehouse=MAIN):
        """실사 등 물리적 보정. 사유가 필요하다."""
        self.item(sku)
        self._wh(warehouse)
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
            raise ValueError(f"조정량은 0 이 아닌 정수: {delta!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("조정 사유가 필요합니다")
        have = self.on_hand(sku, warehouse)
        if have + delta < 0:
            raise InsufficientStock(f"{sku}@{warehouse}: 재고가 음수가 됩니다 ({have} {delta:+d})")
        self._set(sku, warehouse, have + delta)
        self._record(sku, "adjust", delta, reason.strip(), warehouse)

    def transfer(self, sku, qty, src, dst, note=""):
        self.item(sku)
        self._wh(src)
        self._wh(dst)
        _positive_int(qty, "수량")
        if src == dst:
            raise ValueError("같은 창고로는 옮길 수 없습니다")
        have = self.on_hand(sku, src)
        if qty > have:
            raise InsufficientStock(f"{sku}@{src}: 재고 {have}개, 요청 {qty}개")
        self._set(sku, src, have - qty)
        self._set(sku, dst, self.on_hand(sku, dst) + qty)
        ts = self.clock()
        self._record(sku, "transfer-out", -qty, note, src, ts)
        self._record(sku, "transfer-in", qty, note, dst, ts)

    # ------------------------------------------------------------ reports
    def value(self):
        return sum((i.unit_cost * i.on_hand for i in self._items.values()), Decimal("0"))

    def low_stock(self, threshold):
        return [i for i in self.items() if i.on_hand <= threshold]

    def history(self, sku=None, warehouse=None):
        if sku is not None:
            self.item(sku)
        if warehouse is not None:
            self._wh(warehouse)
        return [m for m in self._movements
                if (sku is None or m.sku == sku) and (warehouse is None or m.warehouse == warehouse)]

    def stock_table(self):
        """storage 용: sku → 창고 → 수량 (0 제외)."""
        return {sku: {w: q for w, q in sorted(s.items()) if q} for sku, s in sorted(self._stock.items())}
