"""재고 장부: 품목, 입고·출고·조정, 이동 기록, 예약."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from stock.errors import DuplicateItem, DuplicateReservation, InsufficientStock, ReservationNotFound, UnknownItem
from stock.models import Item, Movement, Reservation

SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} 는 1 이상의 정수여야 합니다: {value!r}")
    return value


class Inventory:
    def __init__(self, items=None, movements=None, clock=None, reservations=None):
        self._items: dict[str, Item] = {i.sku: i for i in (items or [])}
        self._movements: list[Movement] = list(movements or [])
        self._reservations: list[Reservation] = list(reservations or [])
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

    # ------------------------------------------------------------ reservations
    def _active(self):
        now = self.clock()
        return [r for r in self._reservations if r.expires_at > now]

    def _find(self, order_id):
        for r in self._active():
            if r.order_id == order_id:
                return r
        raise ReservationNotFound(f"유효한 예약이 없습니다: {order_id}")

    def available(self, sku):
        item = self.item(sku)
        return item.on_hand - sum(r.qty for r in self._active() if r.sku == sku)

    def reserve(self, sku, qty, order_id, expires_at):
        self.item(sku)
        _positive_int(qty, "수량")
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("주문 번호가 비어 있습니다")
        now = self.clock()
        if not expires_at > now:
            raise ValueError("만료 시각은 지금보다 뒤여야 합니다")
        active = self._active()
        if any(r.order_id == order_id for r in active):
            raise DuplicateReservation(f"이미 예약된 주문: {order_id}")
        if qty > self.available(sku):
            raise InsufficientStock(f"{sku}: 예약 가능 {self.available(sku)}개, 요청 {qty}개")
        self._reservations = active + [Reservation(order_id, sku, qty, expires_at)]

    def release(self, order_id):
        r = self._find(order_id)
        self._reservations.remove(r)

    def fulfill(self, order_id):
        r = self._find(order_id)
        item = self.item(r.sku)
        self._reservations.remove(r)
        item.on_hand -= r.qty
        self._record(r.sku, "ship", -r.qty, f"order {order_id}")

    def reservations(self, sku=None):
        rs = [r for r in self._active() if sku is None or r.sku == sku]
        return sorted(rs, key=lambda r: (r.expires_at, r.order_id))

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
        avail = self.available(sku)
        if qty > avail:
            raise InsufficientStock(f"{sku}: 출고 가능 {avail}개, 요청 {qty}개")
        item.on_hand -= qty
        self._record(sku, "ship", -qty, note)

    def adjust(self, sku, delta, reason):
        """실사 등 물리적 보정. 사유가 필요하다. 예약 때문에 막지 않는다."""
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
