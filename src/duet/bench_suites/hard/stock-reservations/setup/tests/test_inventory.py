from datetime import datetime
from decimal import Decimal

import pytest

from stock import DuplicateItem, InsufficientStock, Inventory, UnknownItem


def inv():
    i = Inventory(clock=lambda: datetime(2026, 1, 1, 9, 0))
    i.add_item("A-1", "Apple", "0.50")
    i.add_item("B-2", "Banana", "0.25")
    return i


def test_receive_ship_adjust():
    i = inv()
    i.receive("A-1", 10)
    i.ship("A-1", 3)
    i.adjust("A-1", -2, "broken")
    assert i.item("A-1").on_hand == 5
    assert [m.qty for m in i.history("A-1")] == [10, -3, -2]


def test_ship_more_than_on_hand():
    i = inv()
    i.receive("A-1", 2)
    with pytest.raises(InsufficientStock):
        i.ship("A-1", 3)


def test_value_and_low_stock():
    i = inv()
    i.receive("A-1", 4)
    i.receive("B-2", 1)
    assert i.value() == Decimal("2.25")
    assert [x.sku for x in i.low_stock(1)] == ["B-2"]


def test_errors():
    i = inv()
    with pytest.raises(DuplicateItem):
        i.add_item("A-1", "again")
    with pytest.raises(UnknownItem):
        i.receive("Z", 1)
    with pytest.raises(ValueError):
        i.receive("A-1", 0)
    with pytest.raises(ValueError):
        i.add_item("bad sku", "x")
