"""기존 동작 (주문 흐름·재고·환불·쿠폰 사용 횟수). 시작 코드와 바뀐 코드 모두에서 같아야 한다."""

from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from shop import InsufficientStock, InvalidState, NotFound, Shop, ValidationError

T0 = datetime(2026, 3, 1, 12, 0)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def make_shop(clock=None):
    s = Shop(clock=clock or Clock())
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("NOVEL", "Novel", "books", "12.00", weight_g=300)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    s.add_product("TSHIRT", "T-Shirt", "apparel", "19.99", weight_g=200)
    s.add_variant("TSHIRT", "TSHIRT-M", attrs={"size": "M"})
    for sku in ("BOOK", "NOVEL", "MUG", "TSHIRT-M"):
        s.receive(sku, 500)
    s.add_coupon("SAVE10", "percent", "10")
    return s


def test_failed_checkout_changes_nothing():
    s = make_shop()
    with pytest.raises(InsufficientStock):
        s.checkout([("MUG", 1), ("BOOK", 501)], "Kim", coupons=["SAVE10"])
    assert s.coupon("SAVE10").uses == 0 and s.inventory.reserved == {} and s.next_order_id == 1001
    assert s.checkout([("MUG", 1)], "Kim").id == 1001


def test_full_refund_of_paid_order_keeps_coupon_use():
    s = make_shop()
    o = s.checkout([("BOOK", 1)], "Kim", coupons=["SAVE10"])
    s.pay(o.id)
    r = s.refund(o.id)
    assert o.status == "refunded" and r.amount == o.total
    assert s.coupon("SAVE10").uses == 1 and s.inventory.reserved == {}


def test_full_refund_of_shipped_order_keeps_coupon_use():
    s = make_shop()
    o = s.checkout([("BOOK", 1), ("MUG", 1)], "Kim", coupons=["SAVE10"])
    s.pay(o.id)
    s.ship(o.id)
    s.refund(o.id)
    assert o.status == "refunded" and s.coupon("SAVE10").uses == 1


def test_partial_refund_keeps_coupon_use():
    s = make_shop()
    o = s.checkout([("BOOK", 1), ("MUG", 2)], "Kim", coupons=["SAVE10"])
    s.pay(o.id)
    s.refund(o.id, {"MUG": 1})
    assert s.coupon("SAVE10").uses == 1 and s.inventory.reserved == {"BOOK": 1, "MUG": 1}


def test_partial_refunds_of_every_unit_do_not_refund_shipping():
    s = make_shop()
    o = s.checkout([("NOVEL", 2)], "Kim")
    s.pay(o.id)
    s.ship(o.id)
    amounts = [s.refund(o.id, {"NOVEL": 1}).amount for _ in range(2)]
    assert amounts == [D("12.84"), D("12.84")] and o.status == "refunded"
    assert all(r.shipping == 0 for r in s.refunds_for(o.id))
    with pytest.raises(InvalidState):
        s.refund(o.id)


def test_full_refund_after_partial_matches_total():
    s = make_shop()
    o = s.checkout([("NOVEL", 3)], "Kim", region="eu")
    assert o.total == D("50.30")
    s.pay(o.id)
    s.ship(o.id)
    first = s.refund(o.id, {"NOVEL": 1})
    rest = s.refund(o.id)
    assert first.amount == D("12.84") and rest.amount == D("37.46") and rest.shipping == D("9.90")
    assert rest.items == {"NOVEL": 2}


def test_refund_validation():
    s = make_shop()
    o = s.checkout([("MUG", 2)], "Kim")
    s.pay(o.id)
    with pytest.raises(ValidationError):
        s.refund(o.id, {"MUG": 3})
    with pytest.raises(ValidationError):
        s.refund(o.id, {"MUG": 0})
    with pytest.raises(NotFound):
        s.refund(o.id, {"BOOK": 1})
    assert s.refunds == []


def test_expire_pending_strictly_older_only():
    clock = Clock()
    s = make_shop(clock)
    a = s.checkout([("BOOK", 1)], "Kim")
    b = s.checkout([("MUG", 1)], "Lee")
    s.pay(b.id)
    clock.t = T0 + timedelta(hours=24)
    assert s.expire_pending(timedelta(hours=24)) == []
    clock.t += timedelta(minutes=1)
    c = s.checkout([("NOVEL", 1)], "Park")
    assert s.expire_pending(timedelta(hours=24)) == [a.id]
    assert (a.status, b.status, c.status) == ("cancelled", "paid", "pending")
    assert s.inventory.reserved == {"MUG": 1, "NOVEL": 1}


def test_cancel_paid_order():
    s = make_shop()
    o = s.checkout([("BOOK", 1), ("MUG", 1)], "Kim")
    s.pay(o.id)
    s.cancel(o.id)
    (r,) = s.refunds_for(o.id)
    assert (r.reason, r.amount, r.items) == ("cancel", o.total, {"BOOK": 1, "MUG": 1})
    assert s.inventory.reserved == {} and s.inventory.on_hand["BOOK"] == 500


def test_ids_are_sequential():
    s = make_shop()
    a = s.checkout([("MUG", 2)], "Kim")
    b = s.checkout([("MUG", 2)], "Lee")
    for o in (a, b):
        s.pay(o.id)
    r1 = s.refund(a.id, {"MUG": 1})
    r2 = s.refund(b.id, {"MUG": 1})
    assert (a.id, b.id, r1.id, r2.id) == (1001, 1002, 1, 2)


def test_restock_only_when_asked():
    s = make_shop()
    o = s.checkout([("MUG", 3)], "Kim")
    s.pay(o.id)
    s.ship(o.id)
    s.refund(o.id, {"MUG": 1})
    assert s.inventory.on_hand["MUG"] == 497
    s.refund(o.id, {"MUG": 1}, restock=True)
    assert s.inventory.on_hand["MUG"] == 498 and s.inventory.reserved == {}


def test_reprice_drops_removed_coupon_and_keeps_uses():
    s = make_shop()
    s.add_coupon("GONE", "percent", "10", stackable=True)
    s.add_coupon("KEEP", "fixed", "1", stackable=True)
    o = s.checkout([("BOOK", 1)], "Kim", coupons=["GONE", "KEEP"])
    assert o.discount == D("4.00")
    s.remove_coupon("GONE")
    s.reprice(o.id)
    assert o.coupons == ["KEEP"] and o.discount == D("1.00") and s.coupon("KEEP").uses == 1


def test_event_history():
    clock = Clock()
    s = make_shop(clock)
    o = s.checkout([("MUG", 2)], "Kim")
    s.pay(o.id)
    s.ship(o.id)
    s.refund(o.id, {"MUG": 1})
    old = s.checkout([("BOOK", 1)], "Lee")
    clock.t += timedelta(days=2)
    s.expire_pending(timedelta(hours=1))
    assert [e.kind for e in s.history(o.id)] == ["created", "paid", "shipped", "refunded"]
    assert [(e.kind, e.detail) for e in s.history(old.id)][-1] == ("cancelled", "expired")


def test_receive_rules():
    s = make_shop()
    with pytest.raises(ValidationError):
        s.receive("TSHIRT", 1)
    with pytest.raises(NotFound):
        s.receive("NOPE", 1)
    s.catalog.set_active("MUG", False)
    assert s.receive("MUG", 5) == 505
