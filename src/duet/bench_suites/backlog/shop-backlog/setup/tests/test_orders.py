from datetime import timedelta
from decimal import Decimal as D

import pytest

from shop import InsufficientStock, InvalidState, NotFound, ValidationError


def test_checkout_reserves_stock(shop):
    o = shop.checkout([("BOOK", 2)], "Kim")
    assert o.id == 1001 and o.status == "pending"
    assert shop.inventory.reserved == {"BOOK": 2} and shop.inventory.available("BOOK") == 98


def test_insufficient_stock_rejects_whole_order(shop):
    with pytest.raises(InsufficientStock):
        shop.checkout([("MUG", 1), ("BOOK", 101)], "Kim")
    assert shop.inventory.reserved == {} and shop.orders == [] and shop.next_order_id == 1001


def test_customer_required(shop):
    with pytest.raises(ValidationError):
        shop.checkout([("BOOK", 1)], "  ")


def test_pay_and_ship(shop, clock):
    o = shop.checkout([("BOOK", 2)], "Kim")
    shop.pay(o.id)
    assert o.status == "paid" and o.paid_at == clock.t
    shop.ship(o.id)
    assert o.status == "shipped"
    assert shop.inventory.on_hand["BOOK"] == 98 and shop.inventory.reserved == {}


def test_invalid_transitions(shop):
    o = shop.checkout([("BOOK", 1)], "Kim")
    with pytest.raises(InvalidState):
        shop.ship(o.id)
    shop.pay(o.id)
    with pytest.raises(InvalidState):
        shop.pay(o.id)
    shop.ship(o.id)
    with pytest.raises(InvalidState):
        shop.cancel(o.id)
    with pytest.raises(NotFound):
        shop.pay(9999)


def test_cancel_pending_releases(shop):
    o = shop.checkout([("BOOK", 2)], "Kim")
    shop.cancel(o.id)
    assert o.status == "cancelled" and shop.inventory.reserved == {} and shop.refunds == []


def test_cancel_paid_records_refund(shop):
    o = shop.checkout([("BOOK", 1), ("MUG", 1)], "Kim")
    shop.pay(o.id)
    shop.cancel(o.id)
    assert o.status == "cancelled"
    (r,) = shop.refunds
    assert r.reason == "cancel" and r.amount == o.total and r.shipping == o.shipping


def test_partial_refund_plain_line(shop):
    o = shop.checkout([("MUG", 3)], "Kim")
    shop.pay(o.id)
    shop.ship(o.id)
    r = shop.refund(o.id, {"MUG": 1})
    assert (r.net, r.tax, r.shipping, r.amount) == (D("8.50"), D("1.62"), D("0"), D("10.12"))
    assert o.status == "shipped"
    with pytest.raises(ValidationError):
        shop.refund(o.id, {"MUG": 3})


def test_full_refund(shop):
    o = shop.checkout([("BOOK", 1), ("MUG", 1)], "Kim")
    shop.pay(o.id)
    shop.ship(o.id)
    r = shop.refund(o.id)
    assert r.amount == o.total and o.status == "refunded"
    with pytest.raises(InvalidState):
        shop.refund(o.id)


def test_refund_restock_after_ship(shop):
    o = shop.checkout([("MUG", 2)], "Kim")
    shop.pay(o.id)
    shop.ship(o.id)
    shop.refund(o.id, {"MUG": 1}, restock=True)
    assert shop.inventory.on_hand["MUG"] == 99


def test_refund_before_ship_releases_reservation(shop):
    o = shop.checkout([("MUG", 2)], "Kim")
    shop.pay(o.id)
    shop.refund(o.id, {"MUG": 1})
    assert shop.inventory.reserved == {"MUG": 1}


def test_refund_pending_not_allowed(shop):
    o = shop.checkout([("MUG", 2)], "Kim")
    with pytest.raises(InvalidState):
        shop.refund(o.id, {"MUG": 1})


def test_expire_pending(shop, clock):
    old = shop.checkout([("BOOK", 1)], "Kim")
    clock.t += timedelta(hours=20)
    young = shop.checkout([("MUG", 1)], "Lee")
    clock.t += timedelta(hours=5)
    assert shop.expire_pending(timedelta(hours=24)) == [old.id]
    assert old.status == "cancelled" and young.status == "pending"
    assert shop.inventory.reserved == {"MUG": 1}


def test_quote_matches_checkout(shop):
    shop.add_coupon("SAVE10", "percent", "10")
    q = shop.quote([("BOOK", 1), ("TEA", 12)], coupons=["SAVE10"])
    o = shop.checkout([("BOOK", 1), ("TEA", 12)], "Kim", coupons=["SAVE10"])
    assert [(x.sku, x.unit_price, x.discount, x.tax) for x in q.lines] == \
           [(x.sku, x.unit_price, x.discount, x.tax) for x in o.lines]
    assert (q.shipping, q.tax, q.total) == (o.shipping, o.tax, o.total)


def test_reprice_pending(shop):
    o = shop.checkout([("MUG", 2)], "Kim")
    shop.catalog.set_price("MUG", "9.00")
    shop.reprice(o.id)
    assert o.lines[0].unit_price == D("9.00") and o.subtotal == D("18.00")
    shop.pay(o.id)
    with pytest.raises(InvalidState):
        shop.reprice(o.id)
